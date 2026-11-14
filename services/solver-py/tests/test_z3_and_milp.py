"""Unit tests for Z3 SMT Compiler and HiGHS MILP Solver."""

from __future__ import annotations

import pytest

from app.milp_solver import (
    NoFeasibleRouteError,
    _evaluate_candidate,
    _solve_milp_for_alpha,
    solve_corridor,
)
from app.models import DisruptionState, ShipmentSpec
from app.network import get_edge_map
from app.parser import get_scenarios
from app.z3_compiler import compute_route_physics, verify_route_with_z3


def test_compute_route_physics_and_z3_cepa_value_add_failure() -> None:
    edge_map = get_edge_map()
    edges = [
        edge_map["E_INNSA_AEFJR_SEA"],
        edge_map["E_AEFJR_AEAUH_RAIL"],
        edge_map["E_AEAUH_EUFRA_AIR"],
    ]

    low_cepa_shipment = ShipmentSpec(
        bol_number="BOL-LOW-CEPA",
        shipper="Exporter",
        consignee="Importer",
        cargo_description="Industrial Valves",
        hs_code="8481.80.00",
        cepa_value_add_pct=25.0,  # Below 40% UAE-India CEPA threshold
        is_temp_sensitive=False,
        max_transit_hours=200.0,
    )
    disruption = DisruptionState(
        hormuz_delay_hours=0.0,
        jebel_ali_congestion_hours=0.0,
        reefer_fault=False,
        require_cepa_zero_tariff=True,
    )

    hours, temp, seal = compute_route_physics(edges, low_cepa_shipment, disruption)
    assert hours == 92.0
    assert seal is True
    assert temp == low_cepa_shipment.initial_temp_c

    cert = verify_route_with_z3("R_TEST", "Test Route", edges, low_cepa_shipment, disruption)
    assert cert.status == "UNSAT"
    assert "CEPA" in (cert.violation_summary or "")


def test_z3_allows_route_when_cepa_not_required() -> None:
    edge_map = get_edge_map()
    edges = [
        edge_map["E_INNSA_AEFJR_SEA"],
        edge_map["E_AEFJR_AEAUH_RAIL"],
        edge_map["E_AEAUH_EUFRA_AIR"],
    ]
    shipment = get_scenarios()[1].shipment.model_copy(update={"cepa_value_add_pct": 20.0})
    disruption = DisruptionState(
        hormuz_delay_hours=0.0,
        jebel_ali_congestion_hours=0.0,
        reefer_fault=False,
        require_cepa_zero_tariff=False,
    )

    cert = verify_route_with_z3("R_NO_CEPA", "No CEPA", edges, shipment, disruption)
    assert cert.status == "SAT"


def test_milp_helpers_and_pareto_sweep() -> None:
    edge_map = get_edge_map()
    pharma = get_scenarios()[0].shipment
    disruption = get_scenarios()[0].default_disruption

    cand, cert = _evaluate_candidate(
        route_id="ROUTE_FUJAIRAH_ETIHAD_AIR_BRIDGE",
        route_name="Fujairah Air Bridge",
        edge_ids=["E_INNSA_AEFJR_SEA", "E_AEFJR_AEAUH_RAIL", "E_AEAUH_EUFRA_AIR"],
        is_baseline=False,
        edge_map=edge_map,
        shipment=pharma,
        disruption=disruption,
    )
    assert cert.status == "SAT"
    assert cand.tariff_penalty_usd == 0.0

    # Single-candidate MILP edge case
    idx, gap = _solve_milp_for_alpha([cand], 0.5, pharma.value_of_time_usd_per_hour)
    assert idx == 0
    assert gap == 0.0

    # Full solve_corridor checks Pareto frontier and extreme SLA fallback
    _, _, opt, pareto, econ, _ = solve_corridor(pharma, disruption, 0.5)
    assert opt.is_optimal is True
    assert len(pareto) == 5
    assert econ.platform_fee_usd == round(econ.net_savings_usd * 0.12, 2)

    # Impossible SLA pushes all routes to UNSAT -> must raise NoFeasibleRouteError
    impossible_sla = pharma.model_copy(update={"max_transit_hours": 10.0})
    with pytest.raises(NoFeasibleRouteError, match="UNSAT"):
        solve_corridor(impossible_sla, disruption, 0.5)
