"""HiGHS MILP Optimizer and Shadow-Mode Unit Economics Engine."""

from __future__ import annotations

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from app.models import (
    CandidatePathEvaluation,
    CorridorEdge,
    DisruptionState,
    GNNWarmStartMetrics,
    ParetoPoint,
    ShipmentSpec,
    UnitEconomics,
    Z3ProofCertificate,
)
from app.network import CANDIDATE_ROUTES, get_edge_map
from app.z3_compiler import (
    CEPA_MFN_PENALTY_RATE,
    CEPA_MIN_VALUE_ADD_PCT,
    compute_route_physics,
    verify_route_with_z3,
)

# UAE Dirham is pegged to the US Dollar at 3.6725 AED/USD; Phase 0 clearinghouse take-rate is 12%
# (target 10-15% range in ROADMAP.md).
AED_PER_USD = 3.6725
CLEARINGHOUSE_TAKE_RATE = 0.12


class NoFeasibleRouteError(ValueError):
    """Raised when all candidate routes fail Z3 formal verification (UNSAT)."""


def _evaluate_candidate(
    route_id: str,
    route_name: str,
    edge_ids: list[str],
    is_baseline: bool,
    edge_map: dict[str, CorridorEdge],
    shipment: ShipmentSpec,
    disruption: DisruptionState,
) -> tuple[CandidatePathEvaluation, Z3ProofCertificate]:
    edges = [edge_map[eid] for eid in edge_ids]
    node_seq = [edges[0].source] + [e.target for e in edges]

    z3_cert = verify_route_with_z3(route_id, route_name, edges, shipment, disruption)
    total_hours, arrival_temp_c, continuous_seal = compute_route_physics(
        edges, shipment, disruption
    )

    freight_cost = sum(e.base_cost_per_teu_usd * shipment.teu_count for e in edges)
    if any(e.id in ("E_AEJEA_EUFRA_SEA", "E_AEKHL_EUFRA_SEA") for e in edges):
        freight_cost += disruption.red_sea_surcharge_usd * shipment.teu_count

    delay_hours = 0.0
    for e in edges:
        if e.passes_hormuz:
            delay_hours += disruption.hormuz_delay_hours
        if e.touches_jebel_ali:
            delay_hours += disruption.jebel_ali_congestion_hours

    demurrage_cost = (delay_hours / 24.0) * shipment.demurrage_usd_per_teu_day * shipment.teu_count

    touches_oman = any(e.touches_oman for e in edges)
    tariff_penalty = 0.0
    if disruption.require_cepa_zero_tariff and (
        shipment.cepa_value_add_pct < CEPA_MIN_VALUE_ADD_PCT
        or (touches_oman and not continuous_seal)
    ):
        tariff_penalty = shipment.cargo_value_usd * CEPA_MFN_PENALTY_RATE

    spoilage_exposure = 0.0
    if shipment.is_temp_sensitive and arrival_temp_c > shipment.max_temp_c:
        spoilage_exposure = shipment.cargo_value_usd * (
            shipment.spoilage_risk_pct_on_breach / 100.0
        )

    total_economic_cost = freight_cost + demurrage_cost + tariff_penalty + spoilage_exposure

    candidate = CandidatePathEvaluation(
        route_id=route_id,
        route_name=route_name,
        node_sequence=node_seq,
        edge_ids=edge_ids,
        modes=[e.mode for e in edges],
        z3_status=z3_cert.status,
        z3_violation=z3_cert.violation_summary,
        total_hours=round(total_hours, 2),
        freight_cost_usd=round(freight_cost, 2),
        demurrage_cost_usd=round(demurrage_cost, 2),
        tariff_penalty_usd=round(tariff_penalty, 2),
        spoilage_exposure_usd=round(spoilage_exposure, 2),
        total_economic_cost_usd=round(total_economic_cost, 2),
        predicted_arrival_temp_c=round(arrival_temp_c, 2),
        is_optimal=False,
        is_baseline=is_baseline,
    )
    return candidate, z3_cert


def _solve_milp_for_alpha(
    feasible_candidates: list[CandidatePathEvaluation],
    alpha: float,
    value_of_time: float,
) -> tuple[int, float]:
    """Run SciPy/HiGHS MILP over Z3-verified SAT routes."""
    n = len(feasible_candidates)
    if n == 1:
        return 0, 0.0

    # Objective: alpha * EconomicCost + (1 - alpha) * ValueOfTime * Hours
    c = np.array(
        [
            alpha * cand.total_economic_cost_usd + (1.0 - alpha) * value_of_time * cand.total_hours
            for cand in feasible_candidates
        ],
        dtype=np.float64,
    )
    integrality = np.ones(n, dtype=np.int32)
    bounds = Bounds(lb=np.zeros(n), ub=np.ones(n))
    constraints = LinearConstraint(np.ones((1, n)), lb=np.array([1.0]), ub=np.array([1.0]))

    res = milp(c=c, integrality=integrality, bounds=bounds, constraints=constraints)
    if not res.success or res.x is None:
        best_idx = int(np.argmin(c))
        return best_idx, 0.0

    best_idx = int(np.argmax(res.x))
    return best_idx, 0.0


def solve_corridor(
    shipment: ShipmentSpec,
    disruption: DisruptionState,
    pareto_alpha: float,
    gnn_metrics: GNNWarmStartMetrics | None = None,
) -> tuple[
    list[CandidatePathEvaluation],
    list[Z3ProofCertificate],
    CandidatePathEvaluation,
    list[ParetoPoint],
    UnitEconomics,
    float,
]:
    """Evaluate all routes via Z3 SMT, solve MILP via HiGHS, and compute Pareto + Unit Economics."""
    edge_map = get_edge_map()
    candidates: list[CandidatePathEvaluation] = []
    certificates: list[Z3ProofCertificate] = []

    ordered_routes = list(CANDIDATE_ROUTES)
    if gnn_metrics is not None and gnn_metrics.edge_risk_scores:
        # Warm-start ordering: evaluate lowest-risk routes first based on T-GNN edge scores
        ordered_routes.sort(
            key=lambda r: max(
                (gnn_metrics.edge_risk_scores.get(eid, 0.5) for eid in r["edge_ids"]),  # type: ignore[attr-defined]
                default=0.5,
            )
        )

    for route_def in ordered_routes:
        cand, cert = _evaluate_candidate(
            route_id=str(route_def["route_id"]),
            route_name=str(route_def["route_name"]),
            edge_ids=list(route_def["edge_ids"]),  # type: ignore[arg-type]
            is_baseline=bool(route_def["is_baseline"]),
            edge_map=edge_map,
            shipment=shipment,
            disruption=disruption,
        )
        candidates.append(cand)
        certificates.append(cert)

    sat_candidates = [c for c in candidates if c.z3_status == "SAT"]
    if not sat_candidates:
        raise NoFeasibleRouteError(
            "No feasible route: all candidate routes failed Z3 formal verification (UNSAT)."
        )

    best_idx, mip_gap = _solve_milp_for_alpha(
        sat_candidates, pareto_alpha, shipment.value_of_time_usd_per_hour
    )
    optimal_route = sat_candidates[best_idx]
    optimal_route.is_optimal = True

    pareto_points: list[ParetoPoint] = []
    for alpha_step in (0.0, 0.25, 0.5, 0.75, 1.0):
        idx, _ = _solve_milp_for_alpha(
            sat_candidates, alpha_step, shipment.value_of_time_usd_per_hour
        )
        chosen = sat_candidates[idx]
        pareto_points.append(
            ParetoPoint(
                alpha=alpha_step,
                route_id=chosen.route_id,
                route_name=chosen.route_name,
                total_hours=chosen.total_hours,
                total_economic_cost_usd=chosen.total_economic_cost_usd,
            )
        )

    baseline = next((c for c in candidates if c.is_baseline), candidates[0])
    net_savings_usd = max(
        0.0, baseline.total_economic_cost_usd - optimal_route.total_economic_cost_usd
    )
    demurrage_prevented = max(0.0, baseline.demurrage_cost_usd - optimal_route.demurrage_cost_usd)
    spoilage_prevented = max(
        0.0, baseline.spoilage_exposure_usd - optimal_route.spoilage_exposure_usd
    )
    hours_saved = max(0.0, baseline.total_hours - optimal_route.total_hours)
    platform_fee_usd = net_savings_usd * CLEARINGHOUSE_TAKE_RATE

    unit_economics = UnitEconomics(
        baseline_route_name=baseline.route_name,
        baseline_total_cost_usd=round(baseline.total_economic_cost_usd, 2),
        baseline_hours=round(baseline.total_hours, 2),
        optimal_route_name=optimal_route.route_name,
        optimal_total_cost_usd=round(optimal_route.total_economic_cost_usd, 2),
        optimal_hours=round(optimal_route.total_hours, 2),
        net_savings_usd=round(net_savings_usd, 2),
        net_savings_aed=round(net_savings_usd * AED_PER_USD, 2),
        demurrage_prevented_usd=round(demurrage_prevented, 2),
        spoilage_prevented_usd=round(spoilage_prevented, 2),
        hours_saved=round(hours_saved, 2),
        clearinghouse_take_rate_pct=CLEARINGHOUSE_TAKE_RATE * 100.0,
        platform_fee_usd=round(platform_fee_usd, 2),
        platform_fee_aed=round(platform_fee_usd * AED_PER_USD, 2),
    )

    return candidates, certificates, optimal_route, pareto_points, unit_economics, mip_gap
