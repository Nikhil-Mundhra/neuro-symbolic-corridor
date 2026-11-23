"""Time-Expanded HiGHS MILP Optimizer with Benders-Style Z3 Lazy Cuts."""

from __future__ import annotations

import heapq
from dataclasses import dataclass

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
from app.network import (
    CANDIDATE_ROUTES,
    RED_SEA_EDGE_IDS,
    TimeExpandedGraph,
    build_time_expanded_graph,
    get_edge_map,
)
from app.z3_compiler import (
    CEPA_MFN_PENALTY_RATE,
    CEPA_MIN_VALUE_ADD_PCT,
    DWELL_THERMAL_DRIFT_C_PER_HOUR,
    Z3ConflictAnalysis,
    _edge_arc_physics,
    compute_route_physics,
    verify_route_with_z3,
    verify_route_with_z3_and_core,
)

# UAE Dirham is pegged to the US Dollar at 3.6725 AED/USD; Phase 0/1 clearinghouse take-rate is 12%
# (target 10-15% range in ROADMAP.md).
AED_PER_USD = 3.6725
CLEARINGHOUSE_TAKE_RATE = 0.12
MAX_BENDERS_ITERATIONS = 64

_CANONICAL_ROUTES_BY_EDGES: dict[tuple[str, ...], tuple[str, str, bool]] = {
    tuple(str(eid) for eid in r["edge_ids"]): (  # type: ignore[attr-defined]
        str(r["route_id"]),
        str(r["route_name"]),
        bool(r["is_baseline"]),
    )
    for r in CANDIDATE_ROUTES
}


class NoFeasibleRouteError(ValueError):
    """Raised when all feasible network flows fail Z3 formal verification (UNSAT)."""


@dataclass(frozen=True)
class _FlowComponent:
    edges: list[CorridorEdge]
    arc_indices: tuple[int, ...]
    dwell_hours: float
    dwell_cost_per_teu: float
    teu_flow: int


@dataclass(frozen=True)
class _PhysicalEdgeCut:
    edge_indices: tuple[int, ...]


@dataclass(frozen=True)
class _WaveArcCut:
    arc_indices: tuple[int, ...]


_LazyCut = _PhysicalEdgeCut | _WaveArcCut


def _identify_route(
    edges: list[CorridorEdge],
    origin_node: str,
    dwell_hours: float = 0.0,
) -> tuple[str, str, bool]:
    """Return (route_id, route_name, is_baseline) using canonical labels when matched."""
    edge_key = tuple(e.id for e in edges)
    if edge_key in _CANONICAL_ROUTES_BY_EDGES and dwell_hours == 0.0:
        return _CANONICAL_ROUTES_BY_EDGES[edge_key]
    if edge_key in _CANONICAL_ROUTES_BY_EDGES and dwell_hours > 0.0:
        cid, cname, _ = _CANONICAL_ROUTES_BY_EDGES[edge_key]
        return (
            f"{cid}_W{int(round(dwell_hours))}H",
            f"{cname} (+{dwell_hours:.0f}h Wave Dwell)",
            False,
        )

    node_seq = [edges[0].source] + [e.target for e in edges] if edges else [origin_node]
    suffix = "_UNBONDED" if any(not e.has_continuous_customs_seal for e in edges) else ""
    dwell_tag = f"_W{int(round(dwell_hours))}H" if dwell_hours > 0.0 else ""
    route_id = f"ROUTE_TE_{'_'.join(node_seq)}{suffix}{dwell_tag}"
    dwell_note = f" (+{dwell_hours:.0f}h Dwell)" if dwell_hours > 0.0 else ""
    route_name = f"Time-Expanded Optimal ({' → '.join(node_seq)}{dwell_note})"
    return route_id, route_name, False


def _evaluate_path_economics(
    route_id: str,
    route_name: str,
    edges: list[CorridorEdge],
    is_baseline: bool,
    shipment: ShipmentSpec,
    disruption: DisruptionState,
    teu_flow: int,
    dwell_hours: float = 0.0,
    dwell_cost_per_teu: float = 0.0,
    z3_cert: Z3ProofCertificate | None = None,
    analysis: Z3ConflictAnalysis | None = None,
) -> tuple[CandidatePathEvaluation, Z3ProofCertificate, Z3ConflictAnalysis]:
    """Compute full corridor economics and Z3 formal proof for a path component."""
    if z3_cert is None or analysis is None:
        z3_cert, analysis = verify_route_with_z3_and_core(
            route_id=route_id,
            route_name=route_name,
            edges=edges,
            shipment=shipment,
            disruption=disruption,
            dwell_hours=dwell_hours,
        )

    total_hours, arrival_temp_c, continuous_seal = compute_route_physics(
        edges, shipment, disruption, dwell_hours=dwell_hours
    )
    node_seq = [edges[0].source] + [e.target for e in edges] if edges else [shipment.origin_node]

    freight_cost = sum(e.base_cost_per_teu_usd * teu_flow for e in edges)
    if any(e.id in RED_SEA_EDGE_IDS for e in edges):
        freight_cost += disruption.red_sea_surcharge_usd * teu_flow

    delay_hours = 0.0
    for e in edges:
        if e.passes_hormuz:
            delay_hours += disruption.hormuz_delay_hours
        if e.touches_jebel_ali:
            delay_hours += disruption.jebel_ali_congestion_hours

    demurrage_cost = (
        (delay_hours / 24.0) * shipment.demurrage_usd_per_teu_day + dwell_cost_per_teu
    ) * teu_flow

    touches_oman = any(e.touches_oman for e in edges)
    tariff_penalty = 0.0
    if disruption.require_cepa_zero_tariff and (
        shipment.cepa_value_add_pct < CEPA_MIN_VALUE_ADD_PCT
        or (touches_oman and not continuous_seal)
    ):
        tariff_penalty = (
            shipment.cargo_value_usd * (teu_flow / shipment.teu_count) * CEPA_MFN_PENALTY_RATE
        )

    spoilage_exposure = 0.0
    if shipment.is_temp_sensitive and arrival_temp_c > shipment.max_temp_c:
        spoilage_exposure = (
            shipment.cargo_value_usd
            * (teu_flow / shipment.teu_count)
            * (shipment.spoilage_risk_pct_on_breach / 100.0)
        )

    total_economic_cost = freight_cost + demurrage_cost + tariff_penalty + spoilage_exposure
    candidate = CandidatePathEvaluation(
        route_id=route_id,
        route_name=route_name,
        node_sequence=node_seq,
        edge_ids=[e.id for e in edges],
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
    return candidate, z3_cert, analysis


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
    z3_cert = verify_route_with_z3(route_id, route_name, edges, shipment, disruption)
    cand, cert, _ = _evaluate_path_economics(
        route_id=route_id,
        route_name=route_name,
        edges=edges,
        is_baseline=is_baseline,
        shipment=shipment,
        disruption=disruption,
        teu_flow=shipment.teu_count,
        z3_cert=z3_cert,
        analysis=Z3ConflictAnalysis(False, [], [], False),
    )
    return cand, cert


def _solve_milp_for_alpha(
    feasible_candidates: list[CandidatePathEvaluation],
    alpha: float,
    value_of_time: float,
) -> tuple[int, float]:
    """Run SciPy/HiGHS MILP over Z3-verified SAT routes (retained for direct unit tests)."""
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


def _build_base_milp_structure(
    graph: TimeExpandedGraph,
    shipment: ShipmentSpec,
) -> tuple[int, Bounds, np.ndarray, list[LinearConstraint]]:
    """Build flow-conservation and arc-activation constraints for the Time-Expanded Graph."""
    n_arcs = len(graph.arcs)
    n_edges = len(graph.physical_edges)
    n_verts = len(graph.vertices)
    n_vars = 2 * n_arcs + n_edges
    teu_qty = shipment.teu_count

    lb = np.zeros(n_vars, dtype=np.float64)
    ub = np.ones(n_vars, dtype=np.float64)
    for idx, arc in enumerate(graph.arcs):
        ub[idx] = float(min(teu_qty, arc.capacity_teu))

    integrality = np.ones(n_vars, dtype=np.int32)
    bounds = Bounds(lb=lb, ub=ub)

    # 1. Flow conservation A_eq @ x = b_eq
    a_eq = np.zeros((n_verts, n_vars), dtype=np.float64)
    b_eq = np.zeros(n_verts, dtype=np.float64)
    for arc in graph.arcs:
        a_eq[arc.source_v, arc.arc_idx] += 1.0
        a_eq[arc.target_v, arc.arc_idx] -= 1.0
    b_eq[graph.source_vertex_idx] = float(teu_qty)
    b_eq[graph.sink_vertex_idx] = float(-teu_qty)
    eq_constraint = LinearConstraint(a_eq, lb=b_eq, ub=b_eq)

    # 2. Coupling constraints:
    #    - For each arc a: f_a - U_a * y_a <= 0  and  y_a - f_a <= 0
    #    - For each transit arc a of edge e: y_a - z_e <= 0
    ub_rows: list[np.ndarray] = []
    ub_rhs: list[float] = []

    for arc in graph.arcs:
        u_a = float(min(teu_qty, arc.capacity_teu))
        row_cap = np.zeros(n_vars, dtype=np.float64)
        row_cap[arc.arc_idx] = 1.0
        row_cap[n_arcs + arc.arc_idx] = -u_a
        ub_rows.append(row_cap)
        ub_rhs.append(0.0)

        row_min = np.zeros(n_vars, dtype=np.float64)
        row_min[arc.arc_idx] = -1.0
        row_min[n_arcs + arc.arc_idx] = 1.0
        ub_rows.append(row_min)
        ub_rhs.append(0.0)

        if arc.kind == "transit" and arc.edge is not None:
            e_idx = graph.edge_index_by_id[arc.edge.id]
            row_edge = np.zeros(n_vars, dtype=np.float64)
            row_edge[n_arcs + arc.arc_idx] = 1.0
            row_edge[2 * n_arcs + e_idx] = -1.0
            ub_rows.append(row_edge)
            ub_rhs.append(0.0)

    a_ub = np.vstack(ub_rows)
    ub_vec = np.array(ub_rhs, dtype=np.float64)
    ub_constraint = LinearConstraint(a_ub, lb=np.full(len(ub_rhs), -np.inf), ub=ub_vec)

    return n_vars, bounds, integrality, [eq_constraint, ub_constraint]


def _build_objective_vector(
    graph: TimeExpandedGraph,
    n_vars: int,
    alpha: float,
    shipment: ShipmentSpec,
) -> np.ndarray:
    """Build linear scalarized objective over flow and tiny GNN-guided tie-breakers."""
    n_arcs = len(graph.arcs)
    teu_qty = float(shipment.teu_count)
    vot = shipment.value_of_time_usd_per_hour
    # Strict interior tie-breaking preserves strict Pareto monotonicity at alpha=0.0 and 1.0
    alpha_eff = min(max(alpha, 1e-7), 1.0 - 1e-7)

    c = np.zeros(n_vars, dtype=np.float64)
    for arc in graph.arcs:
        c[arc.arc_idx] = alpha_eff * arc.cost_per_teu_usd + (1.0 - alpha_eff) * vot * (
            arc.hours / teu_qty
        )
        # Microscopic GNN risk + hop tie-breaker guides branching without distorting cost/time
        c[n_arcs + arc.arc_idx] = 1e-6 * arc.gnn_risk + 1e-7
    return c


def _cut_to_constraint(
    cut: _LazyCut,
    n_arcs: int,
    n_vars: int,
) -> LinearConstraint:
    row = np.zeros((1, n_vars), dtype=np.float64)
    if isinstance(cut, _PhysicalEdgeCut):
        for e_idx in cut.edge_indices:
            row[0, 2 * n_arcs + e_idx] = 1.0
        rhs = float(len(cut.edge_indices) - 1)
    else:
        for a_idx in cut.arc_indices:
            row[0, n_arcs + a_idx] = 1.0
        rhs = float(len(cut.arc_indices) - 1)
    return LinearConstraint(row, lb=np.array([-np.inf]), ub=np.array([rhs]))


def _decompose_flow(
    graph: TimeExpandedGraph,
    f_sol: np.ndarray,
) -> list[_FlowComponent]:
    """Decompose integer time-expanded flow solution into concrete paths + wave dwells."""
    rem = [max(0, int(round(float(f_sol[i])))) for i in range(len(graph.arcs))]
    out_arcs: list[list[int]] = [[] for _ in range(len(graph.vertices))]
    for arc in graph.arcs:
        out_arcs[arc.source_v].append(arc.arc_idx)

    components: list[_FlowComponent] = []
    while True:
        # Find an augmenting path from source_vertex_idx to sink_vertex_idx with rem > 0
        stack: list[tuple[int, list[int], set[int]]] = [
            (graph.source_vertex_idx, [], {graph.source_vertex_idx})
        ]
        found_path: list[int] | None = None
        while stack:
            v, path_arcs, visited = stack.pop()
            if v == graph.sink_vertex_idx:
                found_path = path_arcs
                break
            for a_idx in out_arcs[v]:
                if rem[a_idx] <= 0:
                    continue
                nxt = graph.arcs[a_idx].target_v
                if nxt in visited:
                    continue
                stack.append((nxt, [*path_arcs, a_idx], visited | {nxt}))

        if found_path is None:
            break

        delta = min(rem[a_idx] for a_idx in found_path)
        for a_idx in found_path:
            rem[a_idx] -= delta

        transit_edges: list[CorridorEdge] = []
        active_arc_indices: list[int] = []
        dwell_hours = 0.0
        dwell_cost = 0.0
        for a_idx in found_path:
            arc = graph.arcs[a_idx]
            if arc.kind == "transit" and arc.edge is not None:
                transit_edges.append(arc.edge)
                active_arc_indices.append(a_idx)
            elif arc.kind == "dwell":
                dwell_hours += arc.hours
                dwell_cost += arc.cost_per_teu_usd
                active_arc_indices.append(a_idx)

        components.append(
            _FlowComponent(
                edges=transit_edges,
                arc_indices=tuple(active_arc_indices),
                dwell_hours=dwell_hours,
                dwell_cost_per_teu=dwell_cost,
                teu_flow=delta,
            )
        )

    return components


def _aggregate_sat_components(
    comp_evals: list[tuple[_FlowComponent, CandidatePathEvaluation, Z3ProofCertificate]],
    shipment: ShipmentSpec,
) -> tuple[CandidatePathEvaluation, Z3ProofCertificate]:
    """Aggregate one or more SAT wave/path components into a single CandidatePathEvaluation."""
    if len(comp_evals) == 1:
        _, cand, cert = comp_evals[0]
        return cand, cert

    # Primary physical route = largest-TEU component (tie-break lowest hours)
    primary_comp, primary_cand, primary_cert = max(
        comp_evals,
        key=lambda item: (item[0].teu_flow, -item[1].total_hours),
    )
    total_teu = float(shipment.teu_count)
    weighted_hours = (
        sum(comp.teu_flow * cand.total_hours for comp, cand, _ in comp_evals) / total_teu
    )
    freight = sum(cand.freight_cost_usd for _, cand, _ in comp_evals)
    demurrage = sum(cand.demurrage_cost_usd for _, cand, _ in comp_evals)
    tariff = sum(cand.tariff_penalty_usd for _, cand, _ in comp_evals)
    spoilage = sum(cand.spoilage_exposure_usd for _, cand, _ in comp_evals)
    total_cost = freight + demurrage + tariff + spoilage
    max_temp = max(cand.predicted_arrival_temp_c for _, cand, _ in comp_evals)

    same_physical = all(
        [e.id for e in comp.edges] == primary_cand.edge_ids for comp, _, _ in comp_evals
    )
    wave_tag = f"MULTI_WAVE_{len(comp_evals)}W"
    if same_physical:
        base_id, base_name, _ = _identify_route(primary_comp.edges, shipment.origin_node, 0.0)
        route_id = f"{base_id}_{wave_tag}"
        route_name = f"{base_name} ({len(comp_evals)}-Wave Capacity Split)"
    else:
        route_id = f"ROUTE_TE_SPLIT_{len(comp_evals)}P_{'_'.join(primary_cand.node_sequence)}"
        route_name = f"Multi-Path Capacity Split ({' → '.join(primary_cand.node_sequence)})"

    agg_cand = CandidatePathEvaluation(
        route_id=route_id,
        route_name=route_name,
        node_sequence=primary_cand.node_sequence,
        edge_ids=primary_cand.edge_ids,
        modes=primary_cand.modes,
        z3_status="SAT",
        z3_violation=None,
        total_hours=round(weighted_hours, 2),
        freight_cost_usd=round(freight, 2),
        demurrage_cost_usd=round(demurrage, 2),
        tariff_penalty_usd=round(tariff, 2),
        spoilage_exposure_usd=round(spoilage, 2),
        total_economic_cost_usd=round(total_cost, 2),
        predicted_arrival_temp_c=round(max_temp, 2),
        is_optimal=False,
        is_baseline=False,
    )
    agg_cert = Z3ProofCertificate(
        route_id=route_id,
        route_name=route_name,
        edge_ids=primary_cand.edge_ids,
        status="SAT",
        checks=primary_cert.checks,
        smtlib_excerpt=primary_cert.smtlib_excerpt,
        violation_summary=None,
    )
    return agg_cand, agg_cert


def _dijkstra_min_metric(
    adj: dict[str, list[tuple[str, float]]],
    origin: str,
    destination: str,
) -> float:
    """Return shortest nonnegative weighted path distance from origin to destination."""
    if origin == destination:
        return 0.0
    dist: dict[str, float] = {origin: 0.0}
    heap: list[tuple[float, str]] = [(0.0, origin)]
    while heap:
        cost, u = heapq.heappop(heap)
        if u == destination:
            return cost
        if cost > dist.get(u, float("inf")):
            continue
        for v, w in adj.get(u, ()):
            nxt = cost + w
            if nxt < dist.get(v, float("inf")):
                dist[v] = nxt
                heapq.heappush(heap, (nxt, v))
    return float("inf")


def _min_path_physics(
    graph: TimeExpandedGraph,
    shipment: ShipmentSpec,
    disruption: DisruptionState,
) -> tuple[float, float]:
    """Compute physical lower bounds (min_transit_hours, min_temp_delta_c) on origin->destination."""
    hours_adj: dict[str, list[tuple[str, float]]] = {}
    temp_adj: dict[str, list[tuple[str, float]]] = {}
    for edge in graph.physical_edges:
        arc_h, arc_temp = _edge_arc_physics(edge, shipment, disruption)
        hours_adj.setdefault(edge.source, []).append((edge.target, arc_h))
        temp_adj.setdefault(edge.source, []).append((edge.target, arc_temp))
    return (
        _dijkstra_min_metric(hours_adj, graph.origin_node, graph.destination_node),
        _dijkstra_min_metric(temp_adj, graph.origin_node, graph.destination_node),
    )


def _register_lazy_cut(
    cut: _LazyCut,
    lazy_cuts: list[_LazyCut],
    cut_constraints: list[LinearConstraint],
    n_arcs: int,
    n_vars: int,
) -> bool:
    """Append a lazy cut if not already registered, returning True if added."""
    if cut in lazy_cuts:
        return False
    lazy_cuts.append(cut)
    cut_constraints.append(_cut_to_constraint(cut, n_arcs, n_vars))
    return True


def _add_wave_dwell_cuts(
    comp: _FlowComponent,
    graph: TimeExpandedGraph,
    analysis: Z3ConflictAnalysis,
    shipment: ShipmentSpec,
    min_transit_hours: float,
    min_transit_temp_delta: float,
    transit_arc_lookup: dict[tuple[str, int], int],
    sink_arc_by_wave: dict[int, int],
    lazy_cuts: list[_LazyCut],
    cut_constraints: list[LinearConstraint],
    n_arcs: int,
    n_vars: int,
) -> bool:
    """Emit transit-only wave cuts, monotonic higher-wave cuts, and sound sink-wave bounds."""
    added = False
    transit_arcs = [a for a in comp.arc_indices if graph.arcs[a].kind == "transit"]

    if transit_arcs:
        # Cut exact transit-arc wave assignment (excludes dwell arcs to prune symmetric node dwells)
        added |= _register_lazy_cut(
            _WaveArcCut(arc_indices=tuple(sorted(set(transit_arcs)))),
            lazy_cuts,
            cut_constraints,
            n_arcs,
            n_vars,
        )
        waves = [graph.arcs[a].wave for a in transit_arcs]
        edge_ids = [graph.arcs[a].edge.id for a in transit_arcs if graph.arcs[a].edge is not None]
        max_w = max(waves)

        # Cut strictly later shifted wave assignments and uniform higher waves (monotone dwell)
        for shift in range(1, graph.num_waves - max_w):
            shifted = tuple(
                sorted(
                    {
                        transit_arc_lookup[(eid, w + shift)]
                        for eid, w in zip(edge_ids, waves, strict=True)
                    }
                )
            )
            added |= _register_lazy_cut(
                _WaveArcCut(arc_indices=shifted),
                lazy_cuts,
                cut_constraints,
                n_arcs,
                n_vars,
            )

        start_uniform_w = max_w + (1 if len(set(waves)) == 1 else 0)
        for w_higher in range(start_uniform_w, graph.num_waves):
            uniform = tuple(sorted({transit_arc_lookup[(eid, w_higher)] for eid in edge_ids}))
            added |= _register_lazy_cut(
                _WaveArcCut(arc_indices=uniform),
                lazy_cuts,
                cut_constraints,
                n_arcs,
                n_vars,
            )
    else:
        added |= _register_lazy_cut(
            _WaveArcCut(arc_indices=tuple(sorted(set(comp.arc_indices)))),
            lazy_cuts,
            cut_constraints,
            n_arcs,
            n_vars,
        )

    if analysis.requires_dwell_for_violation:
        for w, sink_idx in sink_arc_by_wave.items():
            w_dwell = w * graph.wave_dwell_hours
            sla_impossible = round(min_transit_hours + w_dwell, 2) > shipment.max_transit_hours
            temp_impossible = (
                shipment.is_temp_sensitive
                and round(
                    shipment.initial_temp_c
                    + min_transit_temp_delta
                    + DWELL_THERMAL_DRIFT_C_PER_HOUR * w_dwell,
                    2,
                )
                > shipment.max_temp_c
            )
            if sla_impossible or temp_impossible:
                added |= _register_lazy_cut(
                    _WaveArcCut(arc_indices=(sink_idx,)),
                    lazy_cuts,
                    cut_constraints,
                    n_arcs,
                    n_vars,
                )

    return added


def _solve_time_expanded_benders(
    graph: TimeExpandedGraph,
    n_vars: int,
    bounds: Bounds,
    integrality: np.ndarray,
    base_constraints: list[LinearConstraint],
    alpha: float,
    shipment: ShipmentSpec,
    disruption: DisruptionState,
    lazy_cuts: list[_LazyCut],
    cut_constraints: list[LinearConstraint],
    eval_cache: dict[
        tuple[tuple[str, ...], float],
        tuple[CandidatePathEvaluation, Z3ProofCertificate, Z3ConflictAnalysis],
    ],
    recorded_routes: dict[str, tuple[CandidatePathEvaluation, Z3ProofCertificate]],
) -> tuple[CandidatePathEvaluation, Z3ProofCertificate, float]:
    """Solve Time-Expanded MILP with iterative Benders Z3 lazy-cut generation until SAT."""
    n_arcs = len(graph.arcs)
    c = _build_objective_vector(graph, n_vars, alpha, shipment)
    transit_arc_lookup = {
        (arc.edge.id, arc.wave): arc.arc_idx
        for arc in graph.arcs
        if arc.kind == "transit" and arc.edge is not None
    }
    sink_arc_by_wave = {arc.wave: arc.arc_idx for arc in graph.arcs if arc.kind == "sink"}
    min_transit_hours, min_transit_temp_delta = _min_path_physics(graph, shipment, disruption)

    for _ in range(MAX_BENDERS_ITERATIONS):
        res = milp(
            c=c,
            integrality=integrality,
            bounds=bounds,
            constraints=[*base_constraints, *cut_constraints],
            options={"mip_rel_gap": 0.0},
        )
        if not res.success or res.x is None:
            raise NoFeasibleRouteError(
                "No feasible route: all corridor paths violate Z3 formal verification (UNSAT) or capacity limits."
            )

        mip_gap_pct = round(abs(float(getattr(res, "mip_gap", 0.0) or 0.0)) * 100.0, 4)
        components = _decompose_flow(graph, res.x[:n_arcs])
        if not components:
            raise NoFeasibleRouteError("No feasible route: flow decomposition yielded empty route.")

        comp_evals: list[tuple[_FlowComponent, CandidatePathEvaluation, Z3ProofCertificate]] = []
        new_cuts_added = False

        for comp in components:
            edge_key = tuple(e.id for e in comp.edges)
            dwell_key = round(comp.dwell_hours, 2)
            cache_key = (edge_key, dwell_key)
            route_id, route_name, is_baseline = _identify_route(
                comp.edges, shipment.origin_node, comp.dwell_hours
            )

            # Evaluate Z3 compliance at exact component (or full-shipment) physics
            if cache_key in eval_cache and comp.teu_flow == shipment.teu_count:
                cand, cert, analysis = eval_cache[cache_key]
            else:
                cand, cert, analysis = _evaluate_path_economics(
                    route_id=route_id,
                    route_name=route_name,
                    edges=comp.edges,
                    is_baseline=is_baseline,
                    shipment=shipment,
                    disruption=disruption,
                    teu_flow=comp.teu_flow,
                    dwell_hours=comp.dwell_hours,
                    dwell_cost_per_teu=comp.dwell_cost_per_teu,
                )
                if comp.teu_flow == shipment.teu_count:
                    eval_cache[cache_key] = (cand, cert, analysis)

            if route_id not in recorded_routes and comp.teu_flow == shipment.teu_count:
                recorded_routes[route_id] = (cand, cert)

            if cert.status == "UNSAT":
                if analysis.is_global_infeasible:
                    raise NoFeasibleRouteError(
                        f"No feasible route: shipment parameters are globally Z3 UNSAT ({cert.violation_summary})."
                    )

                added_for_comp = False
                if not analysis.requires_dwell_for_violation:
                    for conflict_eids in analysis.minimal_conflict_edge_sets:
                        e_indices = tuple(
                            sorted(graph.edge_index_by_id[eid] for eid in conflict_eids)
                        )
                        if _register_lazy_cut(
                            _PhysicalEdgeCut(edge_indices=e_indices),
                            lazy_cuts,
                            cut_constraints,
                            n_arcs,
                            n_vars,
                        ):
                            new_cuts_added = True
                            added_for_comp = True

                if not added_for_comp and comp.arc_indices:
                    new_cuts_added |= _add_wave_dwell_cuts(
                        comp=comp,
                        graph=graph,
                        analysis=analysis,
                        shipment=shipment,
                        min_transit_hours=min_transit_hours,
                        min_transit_temp_delta=min_transit_temp_delta,
                        transit_arc_lookup=transit_arc_lookup,
                        sink_arc_by_wave=sink_arc_by_wave,
                        lazy_cuts=lazy_cuts,
                        cut_constraints=cut_constraints,
                        n_arcs=n_arcs,
                        n_vars=n_vars,
                    )

            comp_evals.append((comp, cand, cert))

        if all(cert.status == "SAT" for _, _, cert in comp_evals):
            agg_cand, agg_cert = _aggregate_sat_components(comp_evals, shipment)
            if agg_cand.route_id not in recorded_routes:
                recorded_routes[agg_cand.route_id] = (agg_cand, agg_cert)
            return agg_cand, agg_cert, mip_gap_pct

        if not new_cuts_added:
            raise NoFeasibleRouteError(
                "No feasible route: Z3 rejected candidate flow without reducible cut."
            )

    raise NoFeasibleRouteError(
        "No feasible route: exceeded Benders lazy-cut iteration limit (UNSAT)."
    )


def solve_corridor(
    shipment: ShipmentSpec,
    disruption: DisruptionState,
    pareto_alpha: float,
    gnn_metrics: GNNWarmStartMetrics | None = None,
    edges: list[CorridorEdge] | None = None,
) -> tuple[
    list[CandidatePathEvaluation],
    list[Z3ProofCertificate],
    CandidatePathEvaluation,
    list[ParetoPoint],
    UnitEconomics,
    float,
]:
    """Solve Time-Expanded MILP with Benders-style Z3 lazy cuts, Pareto sweep, and economics."""
    try:
        graph = build_time_expanded_graph(
            origin_node=shipment.origin_node,
            destination_node=shipment.destination_node,
            shipment=shipment,
            disruption=disruption,
            edges=edges,
            gnn_metrics=gnn_metrics,
        )
    except ValueError as exc:
        raise NoFeasibleRouteError(str(exc)) from exc

    n_vars, bounds, integrality, base_constraints = _build_base_milp_structure(graph, shipment)
    lazy_cuts: list[_LazyCut] = []
    cut_constraints: list[LinearConstraint] = []
    eval_cache: dict[
        tuple[tuple[str, ...], float],
        tuple[CandidatePathEvaluation, Z3ProofCertificate, Z3ConflictAnalysis],
    ] = {}
    recorded_routes: dict[str, tuple[CandidatePathEvaluation, Z3ProofCertificate]] = {}

    # 1. Solve primary Time-Expanded MILP + Z3 Benders lazy-cut loop at requested pareto_alpha
    optimal_cand, _, mip_gap = _solve_time_expanded_benders(
        graph=graph,
        n_vars=n_vars,
        bounds=bounds,
        integrality=integrality,
        base_constraints=base_constraints,
        alpha=pareto_alpha,
        shipment=shipment,
        disruption=disruption,
        lazy_cuts=lazy_cuts,
        cut_constraints=cut_constraints,
        eval_cache=eval_cache,
        recorded_routes=recorded_routes,
    )

    # 2. Compute exact Pareto frontier across alpha in [0.0, 0.25, 0.5, 0.75, 1.0]
    pareto_points: list[ParetoPoint] = []
    for alpha_step in (0.0, 0.25, 0.5, 0.75, 1.0):
        if abs(alpha_step - pareto_alpha) < 1e-9:
            chosen_cand = optimal_cand
        else:
            chosen_cand, _, _ = _solve_time_expanded_benders(
                graph=graph,
                n_vars=n_vars,
                bounds=bounds,
                integrality=integrality,
                base_constraints=base_constraints,
                alpha=alpha_step,
                shipment=shipment,
                disruption=disruption,
                lazy_cuts=lazy_cuts,
                cut_constraints=cut_constraints,
                eval_cache=eval_cache,
                recorded_routes=recorded_routes,
            )
        pareto_points.append(
            ParetoPoint(
                alpha=alpha_step,
                route_id=chosen_cand.route_id,
                route_name=chosen_cand.route_name,
                total_hours=chosen_cand.total_hours,
                total_economic_cost_usd=chosen_cand.total_economic_cost_usd,
            )
        )

    # 3. Audit benchmark reference corridors for INNSA -> EUFRA comparison & baseline economics
    if edges is None and shipment.origin_node == "INNSA" and shipment.destination_node == "EUFRA":
        edge_map = get_edge_map()
        for route_def in CANDIDATE_ROUTES:
            rid = str(route_def["route_id"])
            if rid in recorded_routes:
                continue
            edge_id_tuple = tuple(str(eid) for eid in route_def["edge_ids"])  # type: ignore[attr-defined]
            r_edges = [edge_map[eid] for eid in edge_id_tuple]
            min_cap = min(e.capacity_teu for e in r_edges)
            # Only add single-wave reference routes that respect capacity (plus baseline & unbonded audit)
            if min_cap >= shipment.teu_count or rid in (
                "ROUTE_BASELINE_HORMUZ_SEA",
                "ROUTE_SOHAR_UNBONDED_SPOT_TRAP",
            ):
                cached = eval_cache.get((edge_id_tuple, 0.0))
                if cached is not None:
                    ref_cand, ref_cert, _ = cached
                else:
                    ref_cand, ref_cert, _ = _evaluate_path_economics(
                        route_id=rid,
                        route_name=str(route_def["route_name"]),
                        edges=r_edges,
                        is_baseline=bool(route_def["is_baseline"]),
                        shipment=shipment,
                        disruption=disruption,
                        teu_flow=shipment.teu_count,
                    )
                recorded_routes[rid] = (ref_cand, ref_cert)

    candidates = [pair[0] for pair in recorded_routes.values()]
    certificates = [pair[1] for pair in recorded_routes.values()]

    # Mark the exact optimal candidate as is_optimal=True
    optimal_route = next(c for c in candidates if c.route_id == optimal_cand.route_id)
    optimal_route.is_optimal = True

    baseline = next(
        (c for c in candidates if c.is_baseline),
        max(candidates, key=lambda c: c.total_economic_cost_usd),
    )
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
