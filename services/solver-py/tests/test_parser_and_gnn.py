"""Unit tests for Guided BoL Parser and T-GNN Warm-Start Pruner."""

from __future__ import annotations

from app.gnn_warmstart import compute_gnn_warmstart
from app.models import DisruptionState
from app.network import CORRIDOR_EDGES
from app.parser import get_scenarios, parse_bol_text


def test_get_scenarios_returns_three_presets() -> None:
    presets = get_scenarios()
    assert len(presets) == 3
    ids = {p.id for p in presets}
    assert ids == {"pharma-biologics-cepa", "auto-ev-drivetrain-cepa", "petchem-specialty-polymers"}


def test_parse_bol_text_non_pharma_defaults() -> None:
    raw = (
        "BILL OF LADING: BOL-AUTO-771\n"
        "SHIPPER: Tata AutoComp\n"
        "CONSIGNEE: Bosch GmbH\n"
        "CARGO: Cast Aluminum Housings\n"
        "HS CODE: 8708.99.00\n"
        "QUANTITY: 10 TEU\n"
        "VALUE: USD 450,000\n"
        "CEPA ORIGIN VALUE-ADD: 44.0%\n"
        "INITIAL TEMP: 25.0C\n"
        "MAX TEMP: 40.0C\n"
        "MAX TRANSIT SLA: 400 HOURS\n"
        "DEMURRAGE RATE: USD 210/TEU/DAY"
    )
    res = parse_bol_text(raw)
    assert res.shipment.bol_number == "BOL-AUTO-771"
    assert res.shipment.is_temp_sensitive is False
    assert res.shipment.teu_count == 10
    assert res.shipment.cargo_value_usd == 450_000.0
    assert res.shipment.cepa_value_add_pct == 44.0
    assert res.shipment.demurrage_usd_per_teu_day == 210.0
    assert res.extraction_ms >= 0.0
    assert len(res.extracted_tokens) >= 10


def test_parse_bol_text_pharma_keyword_forces_cold_chain_ceiling() -> None:
    raw = "SHIPPER: BioLab\nCARGO: Recombinant Vaccine Vial Batch\nMAX TEMP: 25.0C\n"
    res = parse_bol_text(raw)
    assert res.shipment.is_temp_sensitive is True
    assert res.shipment.max_temp_c == 8.0


def test_gnn_warmstart_nominal_vs_disrupted() -> None:
    pharma = get_scenarios()[0].shipment

    nominal = compute_gnn_warmstart(
        CORRIDOR_EDGES,
        DisruptionState(
            hormuz_delay_hours=0.0,
            jebel_ali_congestion_hours=0.0,
            reefer_fault=False,
            reefer_ambient_drift_c_per_hour=0.0,
        ),
        pharma,
    )
    assert nominal.predicted_bottleneck_nodes == ["NOMINAL_CORRIDOR"]
    assert 45.0 <= nominal.prune_ratio_pct <= 92.0
    assert all(0.0 <= score <= 1.0 for score in nominal.edge_risk_scores.values())

    disrupted = compute_gnn_warmstart(
        CORRIDOR_EDGES,
        DisruptionState(
            hormuz_delay_hours=96.0,
            jebel_ali_congestion_hours=48.0,
            reefer_fault=True,
            reefer_ambient_drift_c_per_hour=0.035,
        ),
        pharma,
    )
    assert "STRAIT_OF_HORMUZ" in disrupted.predicted_bottleneck_nodes
    assert "AEJEA" in disrupted.predicted_bottleneck_nodes
    assert "LONG_HAUL_REEFER_DECAY" in disrupted.predicted_bottleneck_nodes
    assert disrupted.edge_risk_scores["E_INNSA_AEJEA_SEA"] > nominal.edge_risk_scores["E_INNSA_AEJEA_SEA"]
    assert disrupted.pruned_variables >= nominal.pruned_variables
