"""Unit tests for Customs Payload Builder and FastAPI endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.customs_payloads import build_customs_payloads
from app.main import app
from app.milp_solver import solve_corridor
from app.models import DisruptionState, TransportMode
from app.parser import get_scenarios

client = TestClient(app)


def test_customs_payloads_with_and_without_air_leg() -> None:
    bulk = get_scenarios()[2]
    _, certs, opt_sea, _, _, _ = solve_corridor(bulk.shipment, bulk.default_disruption, 0.9)
    assert TransportMode.AIR_CARGO not in opt_sea.modes
    cert_sea = next(c for c in certs if c.route_id == opt_sea.route_id)
    payloads_sea = build_customs_payloads("solve-sea-1", bulk.shipment, opt_sea, cert_sea)
    assert payloads_sea.etihad_cargo_eawb is None
    assert payloads_sea.dubai_trade_mirsal2["cepa_claim"]["z3_proof_status"] == "SAT"

    pharma = get_scenarios()[0]
    _, certs_p, opt_air, _, _, _ = solve_corridor(pharma.shipment, pharma.default_disruption, 0.5)
    assert TransportMode.AIR_CARGO in opt_air.modes
    cert_air = next(c for c in certs_p if c.route_id == opt_air.route_id)
    payloads_air = build_customs_payloads("solve-air-1", pharma.shipment, opt_air, cert_air)
    assert payloads_air.etihad_cargo_eawb is not None
    assert payloads_air.etihad_cargo_eawb["product_tier"] == "PharmaLife Active 2-8C"


def test_fastapi_endpoints_scenarios_parse_and_validation() -> None:
    scen_resp = client.get("/scenarios")
    assert scen_resp.status_code == 200
    assert len(scen_resp.json()) == 3

    parse_resp = client.post(
        "/parse-bol",
        json={"raw_text": "BILL OF LADING: BOL-99\nCARGO: Pharma Cold-Chain\nQUANTITY: 2 TEU"},
    )
    assert parse_resp.status_code == 200
    assert parse_resp.json()["shipment"]["bol_number"] == "BOL-99"

    bad_resp = client.post("/parse-bol", json={"raw_text": "abc"})
    assert bad_resp.status_code == 422

    bad_solve = client.post(
        "/solve",
        json={
            "shipment": get_scenarios()[0].shipment.model_dump(),
            "disruption": DisruptionState().model_dump(),
            "pareto_alpha": 1.5,
        },
    )
    assert bad_solve.status_code == 422
