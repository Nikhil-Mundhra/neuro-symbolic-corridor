"""Strict Pydantic v2 schemas for the Neuro-Symbolic Corridor Solver."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel


class TransportMode(StrEnum):
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


# ============================================================================
# Canonical DCSA eBL 3.0 / IATA ONE Record / GCC Customs & Telemetry Models
# ============================================================================

# ISO 6346 letter-to-integer map (A=10, skipping multiples of 11: 11, 22, 33)
_ISO6346_LETTER_VALUES: dict[str, int] = {}
_iso_val = 10
for _ascii_code in range(ord("A"), ord("Z") + 1):
    if _iso_val % 11 == 0:
        _iso_val += 1
    _ISO6346_LETTER_VALUES[chr(_ascii_code)] = _iso_val
    _iso_val += 1

_ISO6346_RE = re.compile(r"^[A-Z]{3}[UJZ]\d{7}$")
_GCC_HS12_RE = re.compile(r"^\d{12}$")
_WCO_HS6_RE = re.compile(r"^\d{6}$")
_UAE_TRN_RE = re.compile(r"^100\d{12}$")
_DUBAI_CODE_RE = re.compile(r"^AE-\d{7}$")
_UN_LOCODE_RE = re.compile(r"^[A-Z]{2}[A-Z2-9]{3}$")
_IMO_RE = re.compile(r"^IMO\d{7}$")
_BAPLIE_POS_RE = re.compile(r"^\d{7}(?:[A-Z]{2})?$")


def validate_iso6346(container_no: str) -> str:
    """Validate an 11-character ISO 6346 container identifier including modulo-11 check digit."""
    normalized = container_no.strip().upper().replace(" ", "")
    if not _ISO6346_RE.match(normalized):
        raise ValueError("Container number must match ISO 6346 ^[A-Z]{3}[UJZ]\\d{7}$")
    total = sum(
        (int(ch) if ch.isdigit() else _ISO6346_LETTER_VALUES[ch]) * (2**idx)
        for idx, ch in enumerate(normalized[:10])
    )
    expected = total % 11
    if expected == 10:
        expected = 0
    if int(normalized[10]) != expected:
        raise ValueError(
            f"ISO 6346 check digit mismatch: expected {expected}, got {normalized[10]}"
        )
    return normalized


class StrictModel(BaseModel):
    """Canonical strict model supporting both snake_case and camelCase JSON wire payloads."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class CanonicalTransportMode(StrEnum):
    OCEAN = "OCEAN"
    AIR = "AIR"
    RAIL = "RAIL"
    ROAD = "ROAD"
    MULTIMODAL_SEA_AIR = "MULTIMODAL_SEA_AIR"
    MULTIMODAL_SEA_RAIL = "MULTIMODAL_SEA_RAIL"


class PartyRole(StrEnum):
    SHIPPER = "SHP"
    CONSIGNEE = "CNE"
    NOTIFY_PARTY = "NTF"
    CARRIER = "CAR"
    CUSTOMS_BROKER = "BRK"


class DocumentStatus(StrEnum):
    DRAFTED = "DRFT"
    SUBMITTED = "SUBM"
    PENDING_APPROVAL = "PENA"
    PENDING_UPDATE = "PENU"
    CONFIRMED = "CONF"
    ISSUED = "ISSU"
    SURRENDERED = "SURR"
    RELEASED = "RELS"
    ON_HOLD = "HOLD"
    REJECTED = "REJE"
    VOID = "VOID"


class GCCCustomsRegime(StrEnum):
    IMPORT_LOCAL_ROW = "IMPORT_TO_LOCAL_FROM_ROW"
    IMPORT_REEXPORT_ROW = "IMPORT_FOR_REEXPORT_TO_LOCAL_FROM_ROW"
    EXPORT = "EXPORT"
    RE_EXPORT = "RE_EXPORT"
    IMPORT_FREE_ZONE = "IMPORT_FROM_ROW_TO_FREE_ZONE"
    FREE_ZONE_TRANSFER = "FREE_ZONE_TRANSFER"
    TRANSIT_INTRA_GCC = "TRANSIT_THROUGH_AND_INTRA_GCC"
    TEMPORARY_ADMISSION = "TEMPORARY_ADMISSION"
    SEA_AIR_TRANSSHIPMENT = "SEA_AIR_TRANSSHIPMENT"


class PartyIdentification(StrictModel):
    role: PartyRole
    legal_name: str = Field(min_length=2, max_length=255)
    address_line: str = Field(min_length=5, max_length=255)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    uae_trn: str | None = None
    uae_trn_fta_verified: bool = False
    dubai_customs_code: str | None = None
    eori_number: str | None = None
    oman_cr_number: str | None = None
    atlp_aeo_id: str | None = None

    @field_validator("uae_trn")
    @classmethod
    def _check_trn(cls, v: str | None) -> str | None:
        if v is not None and not _UAE_TRN_RE.match(v):
            raise ValueError("UAE TRN must be exactly 15 digits starting with 100")
        return v

    @field_validator("dubai_customs_code")
    @classmethod
    def _check_dxb_code(cls, v: str | None) -> str | None:
        if v is not None and not _DUBAI_CODE_RE.match(v):
            raise ValueError("Dubai Customs code must match AE-XXXXXXX")
        return v


class ReeferSpecification(StrictModel):
    min_temp_c: Decimal
    max_temp_c: Decimal
    setpoint_temp_c: Decimal | None = None
    humidity_pct: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("100"))

    @model_validator(mode="after")
    def _check_bounds(self) -> ReeferSpecification:
        if self.min_temp_c > self.max_temp_c:
            raise ValueError("min_temp_c cannot exceed max_temp_c")
        if self.setpoint_temp_c is not None and not (
            self.min_temp_c <= self.setpoint_temp_c <= self.max_temp_c
        ):
            raise ValueError("setpoint_temp_c must lie within [min_temp_c, max_temp_c]")
        return self


class HazmatSpecification(StrictModel):
    un_number: str = Field(pattern=r"^UN\d{4}$")
    un_hazmat_class: str = Field(min_length=1, max_length=8)
    packing_group: Literal["I", "II", "III"] | None = None
    proper_shipping_name: str = Field(min_length=3, max_length=255)
    msds_document_ref: str | None = None
    un383_certified: bool | None = None


class OriginPreferenceSpec(StrictModel):
    country_of_origin: str = Field(pattern=r"^[A-Z]{2}$")
    certificate_of_origin_no: str | None = None
    preferential_cepa_claimed: bool = False
    cepa_agreement_code: str | None = None
    cepa_value_add_pct: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("100"))

    @model_validator(mode="after")
    def _check_cepa(self) -> OriginPreferenceSpec:
        if self.preferential_cepa_claimed:
            if not self.certificate_of_origin_no:
                raise ValueError(
                    "certificate_of_origin_no is mandatory when preferential_cepa_claimed=True"
                )
            if self.cepa_value_add_pct is None:
                raise ValueError(
                    "cepa_value_add_pct cannot be null or defaulted when preferential_cepa_claimed=True"
                )
        return self


class ConsignmentItem(StrictModel):
    item_id: str = Field(min_length=1, max_length=64)
    goods_description: str = Field(min_length=5, max_length=512)
    hs_code_gcc12: str | None = None
    hs_code_wco6: str | None = None
    quantity: Decimal = Field(gt=Decimal("0"))
    package_type: str = Field(min_length=2, max_length=32)
    gross_weight_kg: Decimal = Field(gt=Decimal("0"))
    net_weight_kg: Decimal = Field(gt=Decimal("0"))
    customs_value_amount: Decimal = Field(gt=Decimal("0"))
    customs_value_currency: str = Field(pattern=r"^[A-Z]{3}$")
    origin: OriginPreferenceSpec
    is_reefer: bool = False
    reefer_spec: ReeferSpecification | None = None
    is_dangerous_goods: bool = False
    hazmat_spec: HazmatSpecification | None = None
    regulatory_permits: list[str] = Field(default_factory=list)

    @field_validator("hs_code_gcc12")
    @classmethod
    def _check_hs12(cls, v: str | None) -> str | None:
        if v is not None and not _GCC_HS12_RE.match(v):
            raise ValueError("GCC/UAE/Oman HS code must be exactly 12 digits")
        return v

    @field_validator("hs_code_wco6")
    @classmethod
    def _check_hs6(cls, v: str | None) -> str | None:
        if v is not None and not _WCO_HS6_RE.match(v):
            raise ValueError("WCO HS code must be exactly 6 digits")
        return v

    @model_validator(mode="after")
    def _check_item_physics_and_flags(self) -> ConsignmentItem:
        if self.net_weight_kg > self.gross_weight_kg:
            raise ValueError("net_weight_kg cannot exceed gross_weight_kg")
        if self.is_reefer and self.reefer_spec is None:
            raise ValueError("reefer_spec required when is_reefer=True")
        if self.is_dangerous_goods and self.hazmat_spec is None:
            raise ValueError("hazmat_spec required when is_dangerous_goods=True")
        return self


class UtilizedTransportEquipment(StrictModel):
    equipment_reference: str
    iso_size_type_code: str = Field(pattern=r"^[A-Z0-9]{4}$")
    seal_numbers: list[str] = Field(default_factory=list)
    tare_weight_kg: Decimal | None = Field(default=None, gt=Decimal("0"))
    verified_gross_mass_kg: Decimal | None = Field(default=None, gt=Decimal("0"))
    stowage_baplie_pos: str | None = None

    @field_validator("equipment_reference")
    @classmethod
    def _check_container(cls, v: str) -> str:
        return validate_iso6346(v)

    @field_validator("stowage_baplie_pos")
    @classmethod
    def _check_baplie(cls, v: str | None) -> str | None:
        if v is not None and not _BAPLIE_POS_RE.match(v):
            raise ValueError("Stowage position must conform to SMDG BAPLIE BBBRRTT[DD]")
        return v


class ChangeOfDestinationSpec(StrictModel):
    vessel_imo: str
    voyage_number: str = Field(min_length=1, max_length=32)
    container_iso6346: str
    stowage_baplie_pos: str
    accessible_without_restow: bool
    estimated_restow_moves: int = Field(ge=0)
    carrier_cod_cutoff_utc: datetime
    original_port_of_discharge: str
    requested_port_of_discharge: str
    cod_request_submitted_utc: datetime

    @field_validator("vessel_imo")
    @classmethod
    def _check_imo(cls, v: str) -> str:
        if not _IMO_RE.match(v.upper()):
            raise ValueError("vessel_imo must match ^IMO\\d{7}$")
        return v.upper()

    @field_validator("container_iso6346")
    @classmethod
    def _check_cod_container(cls, v: str) -> str:
        return validate_iso6346(v)

    @field_validator("stowage_baplie_pos")
    @classmethod
    def _check_cod_baplie(cls, v: str) -> str:
        if not _BAPLIE_POS_RE.match(v):
            raise ValueError("stowage_baplie_pos must conform to BBBRRTT[DD]")
        return v

    @field_validator("original_port_of_discharge", "requested_port_of_discharge")
    @classmethod
    def _check_locode(cls, v: str) -> str:
        if not _UN_LOCODE_RE.match(v.upper()):
            raise ValueError("Port code must be a valid 5-char UN/LOCODE")
        return v.upper()

    @model_validator(mode="after")
    def _check_cod_cutoff_and_restow(self) -> ChangeOfDestinationSpec:
        if self.cod_request_submitted_utc > self.carrier_cod_cutoff_utc:
            raise ValueError("COD request timestamp exceeds carrier_cod_cutoff_utc")
        if self.accessible_without_restow and self.estimated_restow_moves > 0:
            raise ValueError("estimated_restow_moves must be 0 when accessible_without_restow=True")
        return self


class TransportLeg(StrictModel):
    leg_sequence: int = Field(ge=1)
    mode: CanonicalTransportMode
    origin_locode: str = Field(pattern=r"^[A-Z]{2}[A-Z2-9]{3}$")
    destination_locode: str = Field(pattern=r"^[A-Z]{2}[A-Z2-9]{3}$")
    carrier_code: str = Field(min_length=2, max_length=16)
    voyage_or_flight_number: str = Field(min_length=2, max_length=32)
    scheduled_departure_utc: datetime
    scheduled_arrival_utc: datetime


class ShipmentRequest(StrictModel):
    internal_request_id: str = Field(min_length=4, max_length=64)
    transport_mode: CanonicalTransportMode
    transport_document_ref: str = Field(min_length=4, max_length=64)
    document_status: DocumentStatus = DocumentStatus.DRAFTED
    customs_regime: GCCCustomsRegime | None = None
    issue_date: date
    incoterms_code: str = Field(pattern=r"^[A-Z]{3}$")
    mofaic_attested_invoice: bool | None = None
    mofaic_attestation_ref: str | None = None
    parties: list[PartyIdentification] = Field(min_length=2)
    legs: list[TransportLeg] = Field(min_length=1)
    consignment_items: list[ConsignmentItem] = Field(min_length=1)
    utilized_equipments: list[UtilizedTransportEquipment] = Field(default_factory=list)
    cod_amendment: ChangeOfDestinationSpec | None = None

    @model_validator(mode="after")
    def _check_required_party_roles(self) -> ShipmentRequest:
        roles = {p.role for p in self.parties}
        if PartyRole.SHIPPER not in roles or PartyRole.CONSIGNEE not in roles:
            raise ValueError("parties must include both SHIPPER (SHP) and CONSIGNEE (CNE)")
        return self


class MissingComplianceField(StrictModel):
    field_path: str
    reason_code: Literal[
        "MISSING_MANDATORY_FIELD",
        "AMBIGUOUS_CANDIDATES",
        "UNVERIFIED_FORMAT",
        "CONFLICTING_DOCUMENT_VALUES",
        "CUTOFF_VIOLATION",
    ]
    message: str
    candidate_values: list[str] = Field(default_factory=list)
    regulatory_reference: str


class ValidationHold(StrictModel):
    status: Literal["VALIDATION_HOLD"] = "VALIDATION_HOLD"
    autonomous_dispatch_blocked: Literal[True] = True
    requires_human_review: Literal[True] = True
    internal_request_id: str
    held_at_utc: datetime
    missing_compliance_fields: list[MissingComplianceField] = Field(min_length=1)


MissingComplianceFields = ValidationHold


class EdgeTelemetryOverride(BaseModel):
    edge_id: str
    base_hours: float | None = None
    base_cost_per_teu_usd: float | None = None
    thermal_drift_c_per_hour: float | None = None
    capacity_teu: int | None = None
    source_provider: str
    updated_at_utc: str


class TelemetrySnapshot(BaseModel):
    disruption: DisruptionState
    edge_overrides: dict[str, EdgeTelemetryOverride] = Field(default_factory=dict)
    last_updated_utc: str
    active_sources: list[str] = Field(default_factory=list)
    event_count: int = 0
