"""Property-based & formal invariant fuzzing suite (L1.5 Granularity Layer).

Uses Hypothesis to fuzz shipment specifications, disruption telemetry, and Pareto weights
to verify that the Neuro-Symbolic Corridor Solver's core mathematical and regulatory
invariants hold across the entire input space.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.gnn_warmstart import compute_gnn_warmstart
from app.milp_solver import _solve_milp_for_alpha, solve_corridor
from app.models import DisruptionState, ShipmentSpec
from app.network import CANDIDATE_ROUTES, CORRIDOR_EDGES, get_edge_map
from app.parser import parse_bol_text
from app.z3_compiler import verify_route_with_z3

# --- Hypothesis Strategies ---

shipment_strategy = st.builds(
    ShipmentSpec,
    bol_number=st.from_regex(r"BOL-[A-Z]{4}-[0-9]{4}", fullmatch=True),
    shipper=st.just("Cipla Biologics Exports Pvt Ltd"),
    consignee=st.just("EuroMed ColdChain Distribution GmbH"),
    cargo_description=st.sampled_from(
        [
            "Monoclonal Antibody Biologics",
            "Precision EV Reduction Gearboxes",
            "High-Density Polypropylene Resins",
        ]
    ),
    hs_code=st.sampled_from(["3002.15.00", "8708.40.00", "3902.10.00", "3004.31.00"]),
    origin_node=st.just("INNSA"),
    destination_node=st.just("EUFRA"),
    teu_count=st.integers(min_value=1, max_value=250),
    cargo_value_usd=st.floats(
        min_value=25_000.0, max_value=10_000_000.0, allow_nan=False, allow_infinity=False
    ),
    cepa_value_add_pct=st.floats(
        min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False
    ),
    is_temp_sensitive=st.booleans(),
    initial_temp_c=st.floats(min_value=2.0, max_value=6.0, allow_nan=False, allow_infinity=False),
    max_temp_c=st.floats(min_value=7.0, max_value=35.0, allow_nan=False, allow_infinity=False),
    max_transit_hours=st.floats(
        min_value=100.0, max_value=650.0, allow_nan=False, allow_infinity=False
    ),
    demurrage_usd_per_teu_day=st.floats(
        min_value=50.0, max_value=600.0, allow_nan=False, allow_infinity=False
    ),
    spoilage_risk_pct_on_breach=st.floats(
        min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False
    ),
    value_of_time_usd_per_hour=st.floats(
        min_value=25.0, max_value=1000.0, allow_nan=False, allow_infinity=False
    ),
)

disruption_strategy = st.builds(
    DisruptionState,
    hormuz_delay_hours=st.floats(
        min_value=0.0, max_value=240.0, allow_nan=False, allow_infinity=False
    ),
    jebel_ali_congestion_hours=st.floats(
        min_value=0.0, max_value=168.0, allow_nan=False, allow_infinity=False
    ),
    red_sea_surcharge_usd=st.floats(
        min_value=0.0, max_value=10_000.0, allow_nan=False, allow_infinity=False
    ),
    reefer_fault=st.booleans(),
    reefer_ambient_drift_c_per_hour=st.floats(
        min_value=0.0, max_value=1.5, allow_nan=False, allow_infinity=False
    ),
    require_cepa_zero_tariff=st.booleans(),
)


@pytest.mark.property
@settings(max_examples=35, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    shipment=shipment_strategy,
    disruption=disruption_strategy,
)
def test_property_zero_regulatory_hallucination_unbonded_always_unsat(
    shipment: ShipmentSpec,
    disruption: DisruptionState,
) -> None:
    """INVARIANT 1: Any route traversing an unbonded spot leg MUST be proven UNSAT by Z3."""
    edge_map = get_edge_map()
    unbonded_route = next(
        r for r in CANDIDATE_ROUTES if r["route_id"] == "ROUTE_SOHAR_UNBONDED_SPOT_TRAP"
    )
    edges = [edge_map[eid] for eid in unbonded_route["edge_ids"]]  # type: ignore[index]

    cert = verify_route_with_z3(
        route_id="ROUTE_SOHAR_UNBONDED_SPOT_TRAP",
        route_name="Unbonded Trap",
        edges=edges,
        shipment=shipment,
        disruption=disruption,
    )
    assert cert.status == "UNSAT"
    checks_by_id = {c.rule_id: c for c in cert.checks}
    assert checks_by_id["GCC_CUSTOMS_ETIR_SEAL"].passed is False
    assert cert.violation_summary is not None


@pytest.mark.property
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    shipment=shipment_strategy,
    disruption=disruption_strategy,
    alpha=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
def test_property_milp_optimality_and_pareto_monotonicity(
    shipment: ShipmentSpec,
    disruption: DisruptionState,
    alpha: float,
) -> None:
    """INVARIANT 2 & 3:
    - When SAT routes exist, the selected optimal route MUST be SAT and never be an UNSAT route.
    - Across the Pareto frontier (alpha increasing from 0 -> 1, weighting economic cost over speed),
      total_economic_cost_usd must be non-increasing and total_hours must be non-decreasing.
    - Unit economics net savings and prevented costs are strictly non-negative.
    """
    candidates, certificates, optimal, pareto, econ, mip_gap = solve_corridor(
        shipment, disruption, alpha
    )

    assert len(candidates) == len(CANDIDATE_ROUTES)
    assert len(certificates) == len(CANDIDATE_ROUTES)
    assert mip_gap == 0.0

    sat_candidates = [c for c in candidates if c.z3_status == "SAT"]
    if sat_candidates:
        assert optimal.z3_status == "SAT"
        # Verify MILP global optimality: no other SAT candidate has a strictly lower scalarized objective
        opt_obj = (
            alpha * optimal.total_economic_cost_usd
            + (1.0 - alpha) * shipment.value_of_time_usd_per_hour * optimal.total_hours
        )
        for cand in sat_candidates:
            cand_obj = (
                alpha * cand.total_economic_cost_usd
                + (1.0 - alpha) * shipment.value_of_time_usd_per_hour * cand.total_hours
            )
            assert opt_obj <= cand_obj + 1e-5

    # Pareto frontier monotonicity check:
    # As alpha increases from 0.0 (100% speed) to 1.0 (100% economic cost),
    # chosen routes cannot become more expensive in economic cost or faster in transit hours.
    assert len(pareto) == 5
    for i in range(len(pareto) - 1):
        p_curr = pareto[i]
        p_next = pareto[i + 1]
        assert p_curr.alpha < p_next.alpha
        assert p_next.total_economic_cost_usd <= p_curr.total_economic_cost_usd + 1e-5
        assert p_next.total_hours >= p_curr.total_hours - 1e-5

    # Unit economics non-negativity and AED peg invariants
    assert econ.net_savings_usd >= 0.0
    assert econ.demurrage_prevented_usd >= 0.0
    assert econ.spoilage_prevented_usd >= 0.0
    assert econ.hours_saved >= 0.0
    assert abs(econ.platform_fee_usd - round(econ.net_savings_usd * 0.12, 2)) <= 0.02


@pytest.mark.property
@settings(max_examples=40, deadline=None)
@given(
    shipment=shipment_strategy,
    disruption=disruption_strategy,
)
def test_property_gnn_warmstart_bounds_and_monotonic_congestion(
    shipment: ShipmentSpec,
    disruption: DisruptionState,
) -> None:
    """INVARIANT 4: T-GNN risk scores are bounded in (0, 1) and monotonic with Hormuz delay."""
    metrics = compute_gnn_warmstart(CORRIDOR_EDGES, disruption, shipment)
    assert metrics.fleet_scale_variables == len(CORRIDOR_EDGES) * 160
    assert 45.0 <= metrics.prune_ratio_pct <= 92.0
    assert 0 <= metrics.pruned_variables <= metrics.fleet_scale_variables
    for edge_id, score in metrics.edge_risk_scores.items():
        assert edge_id.startswith("E_")
        assert 0.0 <= score <= 1.0

    # Increasing Hormuz delay must never decrease the risk score on the Hormuz sea leg
    higher_hormuz = disruption.model_copy(
        update={"hormuz_delay_hours": min(240.0, disruption.hormuz_delay_hours + 48.0)}
    )
    metrics_high = compute_gnn_warmstart(CORRIDOR_EDGES, higher_hormuz, shipment)
    assert (
        metrics_high.edge_risk_scores["E_INNSA_AEJEA_SEA"]
        >= metrics.edge_risk_scores["E_INNSA_AEJEA_SEA"]
    )


@pytest.mark.property
@settings(max_examples=40, deadline=None)
@given(
    raw_text=st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),
        min_size=10,
        max_size=600,
    )
)
def test_property_bol_parser_never_hallucinates_invalid_schema(raw_text: str) -> None:
    """INVARIANT 5: Unstructured BoL parser always produces a valid Pydantic ShipmentSpec."""
    parsed = parse_bol_text(raw_text)
    assert 0.70 <= parsed.extraction_confidence <= 0.99
    assert 1 <= parsed.shipment.teu_count <= 500
    assert parsed.shipment.cargo_value_usd >= 10_000.0
    assert 0.0 <= parsed.shipment.cepa_value_add_pct <= 100.0
    assert parsed.shipment.max_transit_hours >= 12.0


@pytest.mark.unit
def test_milp_fallback_when_scipy_reports_unsuccessful(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify deterministic argmin fallback if scipy.optimize.milp returns success=False."""
    from types import SimpleNamespace

    import app.milp_solver as milp_mod
    from app.parser import get_scenarios

    pharma = get_scenarios()[0]
    candidates, _, _, _, _, _ = solve_corridor(pharma.shipment, pharma.default_disruption, 0.5)
    sat_cands = [c for c in candidates if c.z3_status == "SAT"]

    monkeypatch.setattr(
        milp_mod,
        "milp",
        lambda *args, **kwargs: SimpleNamespace(success=False, x=None),
    )
    idx, gap = _solve_milp_for_alpha(sat_cands, 0.5, pharma.shipment.value_of_time_usd_per_hour)
    assert 0 <= idx < len(sat_cands)
    assert gap == 0.0
