"""Strict Pydantic v2 schemas for the Neuro-Symbolic Corridor Solver."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TransportMode(str, Enum):
    SEA = "SEA"
    GREEN_CORRIDOR_TRUCK = "GREEN_CORRIDOR_TRUCK"
    ETIHAD_RAIL_BONDED = "ETIHAD_RAIL_BONDED"
    AIR_CARGO = "AIR_CARGO"
    UNBONDED_SPOT_TRUCK = "UNBONDED_SPOT_TRUCK"


class CorridorNode(BaseModel):
    id: str
    name: str
    code: str
    country: str
    role: str
    lon: float
    lat: float
    customs_zone: str
    daily_demurrage_usd: float = Field(ge=0)


class CorridorEdge(BaseModel):
    id: str
    source: str
    target: str
    mode: TransportMode
    label: str
    base_hours: float = Field(gt=0)
    base_cost_per_teu_usd: float = Field(ge=0)
    distance_km: float = Field(gt=0)
    co2_kg_per_teu: float = Field(ge=0)
    passes_hormuz: bool = False
    touches_jebel_ali: bool = False
    touches_oman: bool = False
    has_continuous_customs_seal: bool = True
    is_green_corridor: bool = False
    active_cold_chain: bool = True
    thermal_drift_c_per_hour: float = Field(default=0.0, ge=0.0)
    capacity_teu: int = Field(default=500, ge=1)
    waypoints: list[list[float]] = Field(default_factory=list)


class CorridorTopology(BaseModel):
    nodes: list[CorridorNode]
    edges: list[CorridorEdge]


class DisruptionState(BaseModel):
    hormuz_delay_hours: float = Field(default=72.0, ge=0.0, le=240.0)
    jebel_ali_congestion_hours: float = Field(default=24.0, ge=0.0, le=168.0)
    red_sea_surcharge_usd: float = Field(default=1800.0, ge=0.0, le=10000.0)
    reefer_fault: bool = Field(default=True)
    reefer_ambient_drift_c_per_hour: float = Field(default=0.035, ge=0.0, le=5.0)
    require_cepa_zero_tariff: bool = Field(default=True)


class ShipmentSpec(BaseModel):
    bol_number: str
    shipper: str
    consignee: str
    cargo_description: str
    hs_code: str = Field(min_length=6, max_length=12)
    origin_node: str = "INNSA"
    destination_node: str = "EUFRA"
    teu_count: int = Field(default=4, ge=1, le=500)
    cargo_value_usd: float = Field(default=1_850_000.0, gt=0)
    cepa_value_add_pct: float = Field(default=48.5, ge=0.0, le=100.0)
    is_temp_sensitive: bool = True
    initial_temp_c: float = 3.5
    max_temp_c: float = 8.0
    max_transit_hours: float = Field(default=144.0, gt=0)
    demurrage_usd_per_teu_day: float = Field(default=250.0, ge=0)
    spoilage_risk_pct_on_breach: float = Field(default=100.0, ge=0, le=100.0)
    value_of_time_usd_per_hour: float = Field(default=320.0, ge=0)


class Z3RuleCheck(BaseModel):
    rule_id: str
    law_reference: str
    passed: bool
    detail: str


class Z3ProofCertificate(BaseModel):
    route_id: str
    route_name: str
    edge_ids: list[str]
    status: str  # "SAT" or "UNSAT"
    checks: list[Z3RuleCheck]
    smtlib_excerpt: str
    violation_summary: str | None = None


class GNNWarmStartMetrics(BaseModel):
    model_architecture: str
    fleet_scale_variables: int
    pruned_variables: int
    prune_ratio_pct: float
    predicted_bottleneck_nodes: list[str]
    edge_risk_scores: dict[str, float]


class CandidatePathEvaluation(BaseModel):
    route_id: str
    route_name: str
    node_sequence: list[str]
    edge_ids: list[str]
    modes: list[TransportMode]
    z3_status: str  # "SAT" | "UNSAT"
    z3_violation: str | None = None
    total_hours: float
    freight_cost_usd: float
    demurrage_cost_usd: float
    tariff_penalty_usd: float
    spoilage_exposure_usd: float
    total_economic_cost_usd: float
    predicted_arrival_temp_c: float
    is_optimal: bool = False
    is_baseline: bool = False


class ParetoPoint(BaseModel):
    alpha: float
    route_id: str
    route_name: str
    total_hours: float
    total_economic_cost_usd: float


class StageLatency(BaseModel):
    stage: str
    component: str
    duration_ms: float
    status: str


class UnitEconomics(BaseModel):
    baseline_route_name: str
    baseline_total_cost_usd: float
    baseline_hours: float
    optimal_route_name: str
    optimal_total_cost_usd: float
    optimal_hours: float
    net_savings_usd: float
    net_savings_aed: float
    demurrage_prevented_usd: float
    spoilage_prevented_usd: float
    hours_saved: float
    clearinghouse_take_rate_pct: float
    platform_fee_usd: float
    platform_fee_aed: float


class CustomsPayloads(BaseModel):
    dubai_trade_mirsal2: dict[str, Any]
    maqta_gateway_atlp: dict[str, Any]
    oman_green_corridor_etir: dict[str, Any]
    etihad_cargo_eawb: dict[str, Any] | None = None


class SolveRequest(BaseModel):
    shipment: ShipmentSpec
    disruption: DisruptionState
    pareto_alpha: float = Field(default=0.55, ge=0.0, le=1.0)


class SolveResponse(BaseModel):
    solve_id: str
    solver_engine: str
    optimality_gap_pct: float
    total_solver_ms: float
    optimal_route: CandidatePathEvaluation
    candidates: list[CandidatePathEvaluation]
    z3_certificates: list[Z3ProofCertificate]
    gnn_warmstart: GNNWarmStartMetrics
    pareto_frontier: list[ParetoPoint]
    unit_economics: UnitEconomics
    stage_latencies: list[StageLatency]
    customs_payloads: CustomsPayloads


class ParseBoLRequest(BaseModel):
    raw_text: str = Field(min_length=10)


class ParseBoLResponse(BaseModel):
    shipment: ShipmentSpec
    extraction_confidence: float
    extraction_ms: float
    extracted_tokens: list[str]


class ScenarioPreset(BaseModel):
    id: str
    title: str
    subtitle: str
    raw_bol_text: str
    shipment: ShipmentSpec
    default_disruption: DisruptionState
