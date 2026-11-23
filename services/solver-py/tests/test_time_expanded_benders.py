"""Tests for Time-Expanded Network Flow MILP, AEDWC discovery, capacity splits, and Z3 lazy cuts."""

from __future__ import annotations

import pytest

from app.customs_payloads import build_customs_payloads
from app.gnn_warmstart import compute_gnn_warmstart
from app.milp_solver import NoFeasibleRouteError, solve_corridor
from app.models import DisruptionState, GNNWarmStartMetrics, ShipmentSpec
from app.network import (
    AEDWC_EXTENSION_EDGES,
    CORRIDOR_EDGES,
    build_time_expanded_graph,
    get_edge_map,
    get_node_map,
)
from app.parser import get_scenarios
from app.z3_compiler import verify_route_with_z3_and_core


@pytest.mark.unit
def test_benders_lazy_cut_rejects_unbonded_and_discovers_arbitrary_od() -> None:
    """Relaxed MILP initially prefers cheap unbonded leg; Z3 lazy cut forces bonded Green Corridor."""
    shipment = ShipmentSpec(
        bol_number="BOL-OD-OMSOH-AEKHL",
        shipper="Sohar Industrial Exports",
        consignee="KIZAD Logistics Hub",
        cargo_description="Precision EV Components",
        hs_code="8708.40.00",
        origin_node="OMSOH",
        destination_node="AEKHL",
        teu_count=10,
        cargo_value_usd=500_000.0,
        cepa_value_add_pct=50.0,
        is_temp_sensitive=False,
        max_transit_hours=24.0,
        value_of_time_usd_per_hour=50.0,
    )
    disruption = DisruptionState(
        hormuz_delay_hours=0.0,
        jebel_ali_congestion_hours=0.0,
        red_sea_surcharge_usd=0.0,
        reefer_fault=False,
        reefer_ambient_drift_c_per_hour=0.0,
        require_cepa_zero_tariff=True,
    )

    # alpha=1.0 makes unbonded truck ($240/TEU) strictly cheaper than Green Corridor ($390/TEU)
    # in the relaxed MILP, forcing a Benders Z3 lazy-cut iteration.
    candidates, certs, optimal, pareto, econ, mip_gap = solve_corridor(
        shipment, disruption, pareto_alpha=1.0
    )

    assert mip_gap == 0.0
    assert optimal.z3_status == "SAT"
    assert optimal.edge_ids == ["E_OMSOH_AEWAJ_GREEN", "E_AEWAJ_AEKHL_GREEN"]
    assert optimal.node_sequence == ["OMSOH", "AEWAJ", "AEKHL"]
    assert len(pareto) == 5
    assert econ.net_savings_usd >= 0.0

    # Verify the unbonded route was explored and rejected by Z3 with UNSAT certificate
    unsat_certs = [c for c in certs if c.status == "UNSAT"]
    assert any("E_OMSOH_AEWAJ_UNBONDED" in c.edge_ids for c in unsat_certs)
    assert any(c.z3_status == "UNSAT" for c in candidates)


@pytest.mark.unit
def test_dynamic_route_discovery_through_aedwc_and_non_hardcoded_paths() -> None:
    """Time-expanded MILP discovers non-hardcoded routes including AEDWC without CANDIDATE_ROUTES."""
    pharma = get_scenarios()[0]
    extended_edges = CORRIDOR_EDGES + AEDWC_EXTENSION_EDGES

    # 1. Arbitrary O-D from AEJEA -> EUFRA under strict 20h SLA forces AEJEA -> AEDWC -> EUFRA
    aejea_shipment = pharma.shipment.model_copy(
        update={
            "origin_node": "AEJEA",
            "destination_node": "EUFRA",
            "teu_count": 10,
            "max_transit_hours": 20.0,
        }
    )
    clear_disruption = DisruptionState(
        hormuz_delay_hours=0.0,
        jebel_ali_congestion_hours=0.0,
        red_sea_surcharge_usd=0.0,
        reefer_fault=True,
        reefer_ambient_drift_c_per_hour=0.035,
        require_cepa_zero_tariff=True,
    )
    _, _, opt_dwc, _, _, _ = solve_corridor(
        aejea_shipment, clear_disruption, pareto_alpha=0.5, edges=extended_edges
    )
    assert opt_dwc.z3_status == "SAT"
    assert opt_dwc.node_sequence == ["AEJEA", "AEDWC", "EUFRA"]
    assert opt_dwc.edge_ids == ["E_AEJEA_AEDWC_SHUTTLE", "E_AEDWC_EUFRA_AIR"]

    # 2. 250 TEU from INNSA -> EUFRA with 95h SLA: AEAUH air (cap=120) takes 120 TEU on wave 0 and
    #    Time-Expanded MILP dynamically routes the remaining 130 TEU via INNSA -> AEFJR -> AEDWC -> EUFRA (cap=180).
    large_pharma = pharma.shipment.model_copy(
        update={
            "teu_count": 250,
            "max_transit_hours": 95.0,
        }
    )
    _, _, opt_innsa_dwc, _, _, _ = solve_corridor(
        large_pharma, pharma.default_disruption, pareto_alpha=0.5, edges=extended_edges
    )
    assert opt_innsa_dwc.z3_status == "SAT"
    assert opt_innsa_dwc.node_sequence == ["INNSA", "AEFJR", "AEDWC", "EUFRA"]
    assert opt_innsa_dwc.edge_ids == [
        "E_INNSA_AEFJR_SEA",
        "E_AEFJR_AEDWC_RAIL",
        "E_AEDWC_EUFRA_AIR",
    ]

    # 3. Non-hardcoded path on default 15-edge graph: OMSOH -> AEAUH (not in CANDIDATE_ROUTES)
    omsoh_to_auh = pharma.shipment.model_copy(
        update={
            "origin_node": "OMSOH",
            "destination_node": "AEAUH",
            "teu_count": 20,
            "max_transit_hours": 24.0,
        }
    )
    _, _, opt_non_hardcoded, _, _, _ = solve_corridor(
        omsoh_to_auh, pharma.default_disruption, pareto_alpha=0.5
    )
    assert opt_non_hardcoded.z3_status == "SAT"
    assert opt_non_hardcoded.node_sequence == ["OMSOH", "AEWAJ", "AEKHL", "AEAUH"]


@pytest.mark.unit
def test_capacity_constraints_multi_wave_dwell_and_wave_cut_infeasibility() -> None:
    """Capacity > 120 TEU triggers multi-wave dwell at AEAUH demurrage; tight SLA rejects wave 1."""
    pharma = get_scenarios()[0]
    node_map = get_node_map()

    # 150 TEU > 120 capacity on E_AEAUH_EUFRA_AIR -> splits 120 on Wave 0 (92h) + 30 on Wave 1 (104h)
    split_shipment = pharma.shipment.model_copy(
        update={
            "teu_count": 150,
            "max_transit_hours": 115.0,
        }
    )
    _, certs, opt_split, pareto, _, mip_gap = solve_corridor(
        split_shipment, pharma.default_disruption, pareto_alpha=0.55
    )
    assert mip_gap == 0.0
    assert opt_split.z3_status == "SAT"
    # 30 TEUs dwell 12h at lowest-demurrage node INNSA (180/day) => 30 * (12 / 24) * 180 = 2,700 USD
    expected_dwell_demurrage = 30 * (12.0 / 24.0) * node_map["INNSA"].daily_demurrage_usd
    assert opt_split.demurrage_cost_usd == pytest.approx(expected_dwell_demurrage, abs=0.01)
    # Weighted hours = (120 * 92 + 30 * 104) / 150 = 94.4h
    assert opt_split.total_hours == pytest.approx(94.4, abs=0.01)
    assert any(c.route_id == opt_split.route_id for c in certs)
    assert len(pareto) == 5

    # Tight SLA (100h) passes Wave 0 (92h) but makes Wave 1 (104h) UNSAT -> WaveArcCut -> NoFeasibleRouteError
    tight_split = split_shipment.model_copy(update={"max_transit_hours": 100.0})
    with pytest.raises(NoFeasibleRouteError, match="UNSAT"):
        solve_corridor(tight_split, pharma.default_disruption, pareto_alpha=0.55)


@pytest.mark.unit
def test_multi_path_capacity_split_and_zero_edge_same_node() -> None:
    """Test multi-path split across distinct physical corridors and origin==destination edge case."""
    bulk = get_scenarios()[2]
    # 350 TEU from INNSA -> AEAUH: E_AEFJR_AEAUH_RAIL (cap=300) + E_AEFJR_AEKHL_RAIL/shuttle (50 TEU)
    split_paths_shipment = bulk.shipment.model_copy(
        update={
            "origin_node": "INNSA",
            "destination_node": "AEAUH",
            "teu_count": 350,
            "max_transit_hours": 120.0,
        }
    )
    _, certs, opt_multi, _, _, _ = solve_corridor(
        split_paths_shipment, bulk.default_disruption, pareto_alpha=0.5
    )
    assert opt_multi.z3_status == "SAT"
    assert "SPLIT" in opt_multi.route_id or "MULTI_WAVE" in opt_multi.route_id
    assert any(c.route_id == opt_multi.route_id for c in certs)

    # Same-node AEDWC -> AEDWC with customs payload generation
    same_node = bulk.shipment.model_copy(
        update={
            "origin_node": "AEDWC",
            "destination_node": "AEDWC",
            "teu_count": 2,
        }
    )
    _, certs_same, opt_same, _, _, _ = solve_corridor(
        same_node, bulk.default_disruption, pareto_alpha=0.5
    )
    assert opt_same.z3_status == "SAT"
    assert opt_same.node_sequence == ["AEDWC"]
    assert opt_same.edge_ids == []
    cert_same = next(c for c in certs_same if c.route_id == opt_same.route_id)
    payloads = build_customs_payloads("solve-same", same_node, opt_same, cert_same)
    assert payloads.maqta_gateway_atlp["terminal_code"] == "AEDWC"


@pytest.mark.unit
def test_z3_unsat_core_minimal_conflicts_and_haynes_mkt() -> None:
    """Verify Z3 assert_and_track extracts minimal conflict sets and Haynes MKT checks."""
    edge_map = get_edge_map()
    pharma = get_scenarios()[0].shipment
    disruption = get_scenarios()[0].default_disruption

    # 1. Unbonded spot truck yields size-1 minimal conflict [E_OMSOH_AEWAJ_UNBONDED]
    unbonded_edges = [
        edge_map["E_INNSA_OMSOH_SEA"],
        edge_map["E_OMSOH_AEWAJ_UNBONDED"],
        edge_map["E_AEWAJ_AEKHL_GREEN"],
        edge_map["E_AEKHL_AEAUH_SHUTTLE"],
        edge_map["E_AEAUH_EUFRA_AIR"],
    ]
    cert_u, analysis_u = verify_route_with_z3_and_core(
        "R_UNB", "Unbonded", unbonded_edges, pharma, disruption
    )
    assert cert_u.status == "UNSAT"
    assert analysis_u.is_global_infeasible is False
    assert ["E_OMSOH_AEWAJ_UNBONDED"] in analysis_u.minimal_conflict_edge_sets
    assert any("E_OMSOH_AEWAJ_UNBONDED" in lbl for lbl in analysis_u.unsat_core_labels)

    # 2. Baseline sea route yields minimal thermal + SLA conflict sets
    sea_edges = [edge_map["E_INNSA_AEJEA_SEA"], edge_map["E_AEJEA_EUFRA_SEA"]]
    cert_s, analysis_s = verify_route_with_z3_and_core(
        "R_SEA", "Sea", sea_edges, pharma, disruption
    )
    assert cert_s.status == "UNSAT"
    assert analysis_s.requires_dwell_for_violation is False
    assert len(analysis_s.minimal_conflict_edge_sets) >= 1

    # 3. Dwell-only thermal and SLA violation on otherwise SAT air bridge
    air_edges = [
        edge_map["E_INNSA_AEFJR_SEA"],
        edge_map["E_AEFJR_AEAUH_RAIL"],
        edge_map["E_AEAUH_EUFRA_AIR"],
    ]
    tight_temp_pharma = pharma.model_copy(update={"max_temp_c": 7.6, "max_transit_hours": 100.0})
    cert_d, analysis_d = verify_route_with_z3_and_core(
        "R_DWELL", "Dwell Breach", air_edges, tight_temp_pharma, disruption, dwell_hours=24.0
    )
    assert cert_d.status == "UNSAT"
    assert analysis_d.requires_dwell_for_violation is True

    # 4. Global infeasibility (invalid 5-digit HS code after stripping dots)
    bad_hs = pharma.model_copy(update={"hs_code": "3002.1"})
    cert_g, analysis_g = verify_route_with_z3_and_core(
        "R_HS", "Bad HS", air_edges, bad_hs, disruption
    )
    assert cert_g.status == "UNSAT"
    assert analysis_g.is_global_infeasible is True

    # 5. Global infeasibility via initial_temp_c > max_temp_c + Haynes MKT upper-knot coverage
    hot_pharma = pharma.model_copy(update={"initial_temp_c": 42.0, "max_temp_c": 8.0})
    _, analysis_hot = verify_route_with_z3_and_core(
        "R_HOT", "Hot Start", air_edges, hot_pharma, disruption
    )
    assert analysis_hot.is_global_infeasible is True


@pytest.mark.unit
def test_gnn_warmstart_preserves_global_optimality_and_invalid_nodes() -> None:
    """High GNN risk scores guide tie-breaking/ordering without sacrificing global optimality."""
    bulk = get_scenarios()[2]
    gnn = compute_gnn_warmstart(CORRIDOR_EDGES, bulk.default_disruption, bulk.shipment)
    # Artificially penalize Hormuz sea edge in GNN metrics while zero-disruption makes it globally cheapest
    adversarial_gnn = GNNWarmStartMetrics(
        model_architecture=gnn.model_architecture,
        fleet_scale_variables=gnn.fleet_scale_variables,
        pruned_variables=gnn.pruned_variables,
        prune_ratio_pct=gnn.prune_ratio_pct,
        predicted_bottleneck_nodes=gnn.predicted_bottleneck_nodes,
        edge_risk_scores={**gnn.edge_risk_scores, "E_INNSA_AEJEA_SEA": 0.99},
    )
    _, _, opt, _, _, _ = solve_corridor(
        bulk.shipment, bulk.default_disruption, pareto_alpha=0.85, gnn_metrics=adversarial_gnn
    )
    assert opt.route_id == "ROUTE_BASELINE_HORMUZ_SEA"

    # Unknown origin / destination nodes raise NoFeasibleRouteError cleanly
    bad_origin = bulk.shipment.model_copy(update={"origin_node": "UNKNOWN"})
    with pytest.raises(NoFeasibleRouteError, match="Unknown origin_node"):
        solve_corridor(bad_origin, bulk.default_disruption, pareto_alpha=0.5)

    bad_dest = bulk.shipment.model_copy(update={"destination_node": "UNKNOWN"})
    with pytest.raises(NoFeasibleRouteError, match="Unknown destination_node"):
        solve_corridor(bad_dest, bulk.default_disruption, pareto_alpha=0.5)

    # Edge referencing external node is ignored gracefully by build_time_expanded_graph
    dangling_edge = CORRIDOR_EDGES[0].model_copy(update={"id": "E_DANGLING", "source": "ZZZ"})
    graph = build_time_expanded_graph(
        "INNSA",
        "EUFRA",
        bulk.shipment,
        bulk.default_disruption,
        edges=[*CORRIDOR_EDGES, dangling_edge],
    )
    assert all(a.edge is None or a.edge.id != "E_DANGLING" for a in graph.arcs)
