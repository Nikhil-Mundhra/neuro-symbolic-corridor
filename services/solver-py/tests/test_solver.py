"""Comprehensive pytest suite for Neuro-Symbolic Corridor Solver."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.models import DisruptionState, SolveRequest
from app.parser import get_scenarios, parse_bol_text

client = TestClient(app)


def test_health_and_topology() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    topo = client.get("/topology").json()
    node_ids = {n["id"] for n in topo["nodes"]}
    assert {"INNSA", "OMSLL", "OMSOH", "AEFJR", "AEWAJ", "AEKHL", "AEJEA", "AEAUH", "EUFRA"}.issubset(node_ids)
    assert len(topo["edges"]) >= 12


def test_pharma_disruption_reroutes_and_proves_sea_unsat() -> None:
    pharma = get_scenarios()[0]
    req = SolveRequest(
        shipment=pharma.shipment,
        disruption=DisruptionState(
            hormuz_delay_hours=72.0,
            jebel_ali_congestion_hours=24.0,
            red_sea_surcharge_usd=1850.0,
            reefer_fault=True,
            reefer_ambient_drift_c_per_hour=0.035,
            require_cepa_zero_tariff=True,
        ),
        pareto_alpha=0.55,
    )
    resp = client.post("/solve", json=req.model_dump())
    assert resp.status_code == 200
    data = resp.json()

    # Sub-200ms core solver latency
    assert data["total_solver_ms"] < 250.0

    # Baseline all-sea route MUST be UNSAT in Z3 due to thermal excursion + SLA breach
    certs_by_id = {c["route_id"]: c for c in data["z3_certificates"]}
    assert certs_by_id["ROUTE_BASELINE_HORMUZ_SEA"]["status"] == "UNSAT"
    assert certs_by_id["ROUTE_SOHAR_UNBONDED_SPOT_TRAP"]["status"] == "UNSAT"

    # Optimal route must be SAT and use Fujairah or Sohar + Etihad Cargo Air Bridge
    opt = data["optimal_route"]
    assert opt["z3_status"] == "SAT"
    assert "AEAUH" in opt["node_sequence"]
    assert opt["predicted_arrival_temp_c"] <= pharma.shipment.max_temp_c
    assert data["unit_economics"]["net_savings_usd"] > 1_000_000.0
    assert data["customs_payloads"]["etihad_cargo_eawb"] is not None


def test_zero_disruption_bulk_selects_baseline_sea() -> None:
    bulk = get_scenarios()[2]
    req = SolveRequest(
        shipment=bulk.shipment,
        disruption=bulk.default_disruption,
        pareto_alpha=0.85,
    )
    resp = client.post("/solve", json=req.model_dump())
    assert resp.status_code == 200
    data = resp.json()

    assert data["optimal_route"]["route_id"] == "ROUTE_BASELINE_HORMUZ_SEA"
    assert data["optimal_route"]["z3_status"] == "SAT"


def test_unbonded_spot_truck_always_rejected_by_z3_under_cepa() -> None:
    auto = get_scenarios()[1]
    req = SolveRequest(
        shipment=auto.shipment,
        disruption=auto.default_disruption,
        pareto_alpha=0.5,
    )
    resp = client.post("/solve", json=req.model_dump())
    assert resp.status_code == 200
    data = resp.json()

    certs_by_id = {c["route_id"]: c for c in data["z3_certificates"]}
    unbonded = certs_by_id["ROUTE_SOHAR_UNBONDED_SPOT_TRAP"]
    assert unbonded["status"] == "UNSAT"
    assert "UNBONDED" in (unbonded["violation_summary"] or "").upper() or "CEPA" in (unbonded["violation_summary"] or "").upper()


def test_bol_parser_extracts_constraints() -> None:
    raw = (
        "BILL OF LADING: BOL-TEST-991\n"
        "SHIPPER: Dr Reddy Labs\n"
        "CONSIGNEE: Berlin Pharma\n"
        "CARGO: Insulin Cold-Chain Biologics\n"
        "HS CODE: 3004.31.00\n"
        "QUANTITY: 6 TEU\n"
        "VALUE: USD 2,400,000\n"
        "CEPA ORIGIN VALUE-ADD: 51.0%\n"
        "INITIAL TEMP: 3.0C\n"
        "MAX TEMP: 8.0C\n"
        "MAX TRANSIT SLA: 130 HOURS\n"
    )
    parsed = parse_bol_text(raw)
    assert parsed.shipment.bol_number == "BOL-TEST-991"
    assert parsed.shipment.teu_count == 6
    assert parsed.shipment.cargo_value_usd == 2_400_000.0
    assert parsed.shipment.is_temp_sensitive is True
    assert parsed.extraction_confidence >= 0.9
