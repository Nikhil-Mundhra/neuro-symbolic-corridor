"""Cross-Service Contract & Sub-400ms Stage SLA Benchmark Gates (L2 & L3 Granularity Layers).

1. L2 Tri-Lingual Contract Guardrail:
   Verifies that every Pydantic v2 model in `services/solver-py/app/models.py` stays in
   1-to-1 structural lockstep with the TypeScript interfaces in `apps/command-center/src/types.ts`
   and the Go structs in `services/gateway-go/workflow.go`.
2. L3 Stage-by-Stage Latency SLA Gate:
   Runs a 50-iteration statistical benchmark across all scenarios and verifies P99 latencies
   against the architectural budgets in AGENTS.md:
   - Stage 2 (Guided BoL Schema Extraction): < 25 ms
   - Stage 3 (T-GNN Warm-Start Variable Pruning): < 30 ms
   - Stage 4 (Z3 SMT Formal Check + HiGHS MILP Optimization): < 200 ms
   - Stage 5 (Customs Payload Generation): < 50 ms
   - Total Python Solver P99: < 250 ms
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    CandidatePathEvaluation,
    ChangeOfDestinationSpec,
    ConsignmentItem,
    CorridorEdge,
    CorridorNode,
    CorridorTopology,
    CustomsPayloads,
    DisruptionState,
    EdgeTelemetryOverride,
    GNNWarmStartMetrics,
    HazmatSpecification,
    MissingComplianceField,
    OriginPreferenceSpec,
    ParetoPoint,
    PartyIdentification,
    ReeferSpecification,
    ScenarioPreset,
    ShipmentRequest,
    ShipmentSpec,
    SolveRequest,
    SolveResponse,
    StageLatency,
    TelemetrySnapshot,
    TransportLeg,
    UnitEconomics,
    UtilizedTransportEquipment,
    ValidationHold,
    Z3ProofCertificate,
    Z3RuleCheck,
)
from app.parser import get_scenarios, parse_bol_text

REPO_ROOT = Path(__file__).resolve().parents[3]
TS_TYPES_PATH = REPO_ROOT / "apps" / "command-center" / "src" / "types.ts"
GO_WORKFLOW_PATH = REPO_ROOT / "services" / "gateway-go" / "workflow.go"

client = TestClient(app)


def _extract_ts_interface_fields(ts_source: str, interface_name: str) -> set[str]:
    pattern = rf"export interface {interface_name}\s*\{{([^}}]+)\}}"
    match = re.search(pattern, ts_source, flags=re.MULTILINE | re.DOTALL)
    assert match is not None, f"Missing TypeScript interface {interface_name} in types.ts"
    body = match.group(1)
    fields: set[str] = set()
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        field_match = re.match(r"^([a-zA-Z0-9_]+)\??\s*:", line)
        if field_match:
            fields.add(field_match.group(1))
    return fields


def _extract_go_json_tags(go_source: str, struct_name: str) -> set[str]:
    pattern = rf"type {struct_name} struct\s*\{{([^}}]+)\}}"
    match = re.search(pattern, go_source, flags=re.MULTILINE | re.DOTALL)
    assert match is not None, f"Missing Go struct {struct_name} in workflow.go"
    body = match.group(1)
    tags: set[str] = set()
    for tag_match in re.finditer(r'`json:"([a-zA-Z0-9_]+)', body):
        tags.add(tag_match.group(1))
    return tags


@pytest.mark.contract
def test_trilingual_schema_contract_parity() -> None:
    """Ensure zero schema drift across Python Pydantic v2, TypeScript interfaces, and Go structs."""
    assert TS_TYPES_PATH.exists(), f"Cannot find {TS_TYPES_PATH}"
    assert GO_WORKFLOW_PATH.exists(), f"Cannot find {GO_WORKFLOW_PATH}"

    ts_source = TS_TYPES_PATH.read_text(encoding="utf-8")
    go_source = GO_WORKFLOW_PATH.read_text(encoding="utf-8")

    # 1. Verify Python Pydantic <-> TypeScript interface exact field parity
    model_to_ts_interface = [
        (CorridorNode, "CorridorNode"),
        (CorridorEdge, "CorridorEdge"),
        (CorridorTopology, "CorridorTopology"),
        (DisruptionState, "DisruptionState"),
        (ShipmentSpec, "ShipmentSpec"),
        (ScenarioPreset, "ScenarioPreset"),
        (Z3RuleCheck, "Z3RuleCheck"),
        (Z3ProofCertificate, "Z3ProofCertificate"),
        (GNNWarmStartMetrics, "GNNWarmStartMetrics"),
        (CandidatePathEvaluation, "CandidatePathEvaluation"),
        (ParetoPoint, "ParetoPoint"),
        (StageLatency, "StageTelemetry"),
        (UnitEconomics, "UnitEconomics"),
        (CustomsPayloads, "CustomsPayloads"),
        (SolveResponse, "SolveResponse"),
        (PartyIdentification, "PartyIdentification"),
        (ReeferSpecification, "ReeferSpecification"),
        (HazmatSpecification, "HazmatSpecification"),
        (OriginPreferenceSpec, "OriginPreferenceSpec"),
        (ConsignmentItem, "ConsignmentItem"),
        (UtilizedTransportEquipment, "UtilizedTransportEquipment"),
        (ChangeOfDestinationSpec, "ChangeOfDestinationSpec"),
        (TransportLeg, "TransportLeg"),
        (ShipmentRequest, "ShipmentRequest"),
        (MissingComplianceField, "MissingComplianceField"),
        (ValidationHold, "ValidationHold"),
        (EdgeTelemetryOverride, "EdgeTelemetryOverride"),
        (TelemetrySnapshot, "TelemetrySnapshot"),
    ]

    for py_model, ts_name in model_to_ts_interface:
        py_fields = set(py_model.model_fields.keys())
        ts_fields = _extract_ts_interface_fields(ts_source, ts_name)
        assert py_fields == ts_fields, (
            f"Schema drift between Python {py_model.__name__} and TypeScript {ts_name}: "
            f"py_only={py_fields - ts_fields}, ts_only={ts_fields - py_fields}"
        )

    # 2. Verify Go Gateway structs <-> TypeScript & Python telemetry & canonical contracts
    go_stage_fields = _extract_go_json_tags(go_source, "StageTelemetry")
    py_stage_fields = set(StageLatency.model_fields.keys())
    assert go_stage_fields == py_stage_fields

    go_wf_fields = _extract_go_json_tags(go_source, "WorkflowRun")
    ts_wf_fields = _extract_ts_interface_fields(ts_source, "WorkflowRun")
    assert go_wf_fields == ts_wf_fields

    go_receipt_fields = _extract_go_json_tags(go_source, "ApprovalReceipt")
    ts_receipt_fields = _extract_ts_interface_fields(ts_source, "ApprovalReceipt")
    assert go_receipt_fields == ts_receipt_fields

    for py_model, go_name in [
        (DisruptionState, "DisruptionState"),
        (EdgeTelemetryOverride, "EdgeTelemetryOverride"),
        (TelemetrySnapshot, "TelemetrySnapshot"),
        (PartyIdentification, "PartyIdentification"),
        (ReeferSpecification, "ReeferSpecification"),
        (HazmatSpecification, "HazmatSpecification"),
        (OriginPreferenceSpec, "OriginPreferenceSpec"),
        (ConsignmentItem, "ConsignmentItem"),
        (UtilizedTransportEquipment, "UtilizedTransportEquipment"),
        (ChangeOfDestinationSpec, "ChangeOfDestinationSpec"),
        (TransportLeg, "TransportLeg"),
        (ShipmentRequest, "ShipmentRequest"),
        (MissingComplianceField, "MissingComplianceField"),
        (ValidationHold, "ValidationHold"),
    ]:
        py_fields = set(py_model.model_fields.keys())
        go_fields = _extract_go_json_tags(go_source, go_name)
        assert py_fields == go_fields, (
            f"Schema drift between Python {py_model.__name__} and Go {go_name}: "
            f"py_only={py_fields - go_fields}, go_only={go_fields - py_fields}"
        )


@pytest.mark.sla
def test_stage_and_p99_latency_sla_budgets() -> None:
    """Verify P99 stage latencies across 45 solver invocations stay strictly within AGENTS.md budgets."""
    scenarios = get_scenarios()

    bol_latencies: list[float] = []
    gnn_latencies: list[float] = []
    z3_milp_latencies: list[float] = []
    customs_latencies: list[float] = []
    total_solver_latencies: list[float] = []

    # Warm-up run
    warmup_req = SolveRequest(
        shipment=scenarios[0].shipment,
        disruption=scenarios[0].default_disruption,
        pareto_alpha=0.55,
    )
    client.post("/solve", json=warmup_req.model_dump())

    for i in range(45):
        preset = scenarios[i % len(scenarios)]
        alpha = 0.15 + 0.17 * (i % 5)

        parsed = parse_bol_text(preset.raw_bol_text)
        bol_latencies.append(parsed.extraction_ms)

        req = SolveRequest(
            shipment=preset.shipment,
            disruption=preset.default_disruption,
            pareto_alpha=round(alpha, 2),
        )
        resp = client.post("/solve", json=req.model_dump())
        assert resp.status_code == 200
        payload = resp.json()

        total_solver_latencies.append(float(payload["total_solver_ms"]))
        stages_by_name = {s["stage"]: float(s["duration_ms"]) for s in payload["stage_latencies"]}
        gnn_latencies.append(stages_by_name["T-GNN Warm-Start"])
        z3_milp_latencies.append(stages_by_name["Z3 SMT + HiGHS MILP"])
        customs_latencies.append(stages_by_name["Customs Bridge"])

    p99_bol = float(np.percentile(bol_latencies, 99))
    p99_gnn = float(np.percentile(gnn_latencies, 99))
    p99_z3_milp = float(np.percentile(z3_milp_latencies, 99))
    p99_customs = float(np.percentile(customs_latencies, 99))
    p99_total = float(np.percentile(total_solver_latencies, 99))

    # Enforce AGENTS.md Stage Latency Budgets
    assert p99_bol < 25.0, f"Stage 2 BoL Parser P99 ({p99_bol:.2f}ms) exceeded 25ms SLA"
    assert p99_gnn < 30.0, f"Stage 3 T-GNN Warm-Start P99 ({p99_gnn:.2f}ms) exceeded 30ms SLA"
    assert p99_z3_milp < 200.0, f"Stage 4 Z3+MILP P99 ({p99_z3_milp:.2f}ms) exceeded 200ms SLA"
    assert p99_customs < 50.0, f"Stage 5 Customs Bridge P99 ({p99_customs:.2f}ms) exceeded 50ms SLA"
    assert p99_total < 250.0, f"Total Python Solver P99 ({p99_total:.2f}ms) exceeded 250ms budget"
