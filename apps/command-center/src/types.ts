export type TransportMode =
  | 'SEA'
  | 'GREEN_CORRIDOR_TRUCK'
  | 'ETIHAD_RAIL_BONDED'
  | 'AIR_CARGO'
  | 'UNBONDED_SPOT_TRUCK';

export interface CorridorNode {
  id: string;
  name: string;
  code: string;
  country: string;
  role: string;
  lon: number;
  lat: number;
  customs_zone: string;
  daily_demurrage_usd: number;
}

export interface CorridorEdge {
  id: string;
  source: string;
  target: string;
  mode: TransportMode;
  label: string;
  base_hours: number;
  base_cost_per_teu_usd: number;
  distance_km: number;
  co2_kg_per_teu: number;
  passes_hormuz: boolean;
  touches_jebel_ali: boolean;
  touches_oman: boolean;
  has_continuous_customs_seal: boolean;
  is_green_corridor: boolean;
  active_cold_chain: boolean;
  thermal_drift_c_per_hour: number;
  capacity_teu: number;
  waypoints: number[][];
}

export interface CorridorTopology {
  nodes: CorridorNode[];
  edges: CorridorEdge[];
}

export interface DisruptionState {
  hormuz_delay_hours: number;
  jebel_ali_congestion_hours: number;
  red_sea_surcharge_usd: number;
  reefer_fault: boolean;
  reefer_ambient_drift_c_per_hour: number;
  require_cepa_zero_tariff: boolean;
}

export interface ShipmentSpec {
  bol_number: string;
  shipper: string;
  consignee: string;
  cargo_description: string;
  hs_code: string;
  origin_node: string;
  destination_node: string;
  teu_count: number;
  cargo_value_usd: number;
  cepa_value_add_pct: number;
  is_temp_sensitive: boolean;
  initial_temp_c: number;
  max_temp_c: number;
  max_transit_hours: number;
  demurrage_usd_per_teu_day: number;
  spoilage_risk_pct_on_breach: number;
  value_of_time_usd_per_hour: number;
}

export interface ScenarioPreset {
  id: string;
  title: string;
  subtitle: string;
  raw_bol_text: string;
  shipment: ShipmentSpec;
  default_disruption: DisruptionState;
}

export interface Z3RuleCheck {
  rule_id: string;
  law_reference: string;
  passed: boolean;
  detail: string;
}

export interface Z3ProofCertificate {
  route_id: string;
  route_name: string;
  edge_ids: string[];
  status: 'SAT' | 'UNSAT';
  checks: Z3RuleCheck[];
  smtlib_excerpt: string;
  violation_summary: string | null;
}

export interface GNNWarmStartMetrics {
  model_architecture: string;
  fleet_scale_variables: number;
  pruned_variables: number;
  prune_ratio_pct: number;
  predicted_bottleneck_nodes: string[];
  edge_risk_scores: Record<string, number>;
}

export interface CandidatePathEvaluation {
  route_id: string;
  route_name: string;
  node_sequence: string[];
  edge_ids: string[];
  modes: TransportMode[];
  z3_status: 'SAT' | 'UNSAT';
  z3_violation: string | null;
  total_hours: number;
  freight_cost_usd: number;
  demurrage_cost_usd: number;
  tariff_penalty_usd: number;
  spoilage_exposure_usd: number;
  total_economic_cost_usd: number;
  predicted_arrival_temp_c: number;
  is_optimal: boolean;
  is_baseline: boolean;
}

export interface ParetoPoint {
  alpha: number;
  route_id: string;
  route_name: string;
  total_hours: number;
  total_economic_cost_usd: number;
}

export interface StageTelemetry {
  stage: string;
  component: string;
  duration_ms: number;
  status: string;
}

export interface UnitEconomics {
  baseline_route_name: string;
  baseline_total_cost_usd: number;
  baseline_hours: number;
  optimal_route_name: string;
  optimal_total_cost_usd: number;
  optimal_hours: number;
  net_savings_usd: number;
  net_savings_aed: number;
  demurrage_prevented_usd: number;
  spoilage_prevented_usd: number;
  hours_saved: number;
  clearinghouse_take_rate_pct: number;
  platform_fee_usd: number;
  platform_fee_aed: number;
}

export interface CustomsPayloads {
  dubai_trade_mirsal2: Record<string, unknown>;
  maqta_gateway_atlp: Record<string, unknown>;
  oman_green_corridor_etir: Record<string, unknown>;
  etihad_cargo_eawb: Record<string, unknown> | null;
}

export interface SolveResponse {
  solve_id: string;
  solver_engine: string;
  optimality_gap_pct: number;
  total_solver_ms: number;
  optimal_route: CandidatePathEvaluation;
  candidates: CandidatePathEvaluation[];
  z3_certificates: Z3ProofCertificate[];
  gnn_warmstart: GNNWarmStartMetrics;
  pareto_frontier: ParetoPoint[];
  unit_economics: UnitEconomics;
  stage_latencies: StageTelemetry[];
  customs_payloads: CustomsPayloads;
}

export interface ApprovalReceipt {
  approved_by: string;
  approved_at_utc: string;
  transaction_hash: string;
  dispatched_apis: string[];
  etir_seal_id: string;
}

export interface WorkflowRun {
  workflow_id: string;
  status: 'PENDING' | 'SOLVED' | 'DISPATCHED_BONDED_CORRIDOR' | 'FAILED';
  created_at_utc: string;
  total_pipeline_ms: number;
  retry_count: number;
  stage_latencies: StageTelemetry[];
  solution: SolveResponse;
  approval_receipt?: ApprovalReceipt;
}

export type CanonicalTransportMode =
  | 'OCEAN'
  | 'AIR'
  | 'RAIL'
  | 'ROAD'
  | 'MULTIMODAL_SEA_AIR'
  | 'MULTIMODAL_SEA_RAIL';

export type PartyRole = 'SHP' | 'CNE' | 'NTF' | 'CAR' | 'BRK';

export type DocumentStatus =
  | 'DRFT'
  | 'SUBM'
  | 'PENA'
  | 'PENU'
  | 'CONF'
  | 'ISSU'
  | 'SURR'
  | 'RELS'
  | 'HOLD'
  | 'REJE'
  | 'VOID';

export type GCCCustomsRegime =
  | 'IMPORT_TO_LOCAL_FROM_ROW'
  | 'IMPORT_FOR_REEXPORT_TO_LOCAL_FROM_ROW'
  | 'EXPORT'
  | 'RE_EXPORT'
  | 'IMPORT_FROM_ROW_TO_FREE_ZONE'
  | 'FREE_ZONE_TRANSFER'
  | 'TRANSIT_THROUGH_AND_INTRA_GCC'
  | 'TEMPORARY_ADMISSION'
  | 'SEA_AIR_TRANSSHIPMENT';

export interface PartyIdentification {
  role: PartyRole;
  legal_name: string;
  address_line: string;
  country_code: string;
  uae_trn?: string | null;
  uae_trn_fta_verified: boolean;
  dubai_customs_code?: string | null;
  eori_number?: string | null;
  oman_cr_number?: string | null;
  atlp_aeo_id?: string | null;
}

export interface ReeferSpecification {
  min_temp_c: string | number;
  max_temp_c: string | number;
  setpoint_temp_c?: string | number | null;
  humidity_pct?: string | number | null;
}

export interface HazmatSpecification {
  un_number: string;
  un_hazmat_class: string;
  packing_group?: 'I' | 'II' | 'III' | null;
  proper_shipping_name: string;
  msds_document_ref?: string | null;
  un383_certified?: boolean | null;
}

export interface OriginPreferenceSpec {
  country_of_origin: string;
  certificate_of_origin_no?: string | null;
  preferential_cepa_claimed: boolean;
  cepa_agreement_code?: string | null;
  cepa_value_add_pct?: string | number | null;
}

export interface ConsignmentItem {
  item_id: string;
  goods_description: string;
  hs_code_gcc12?: string | null;
  hs_code_wco6?: string | null;
  quantity: string | number;
  package_type: string;
  gross_weight_kg: string | number;
  net_weight_kg: string | number;
  customs_value_amount: string | number;
  customs_value_currency: string;
  origin: OriginPreferenceSpec;
  is_reefer: boolean;
  reefer_spec?: ReeferSpecification | null;
  is_dangerous_goods: boolean;
  hazmat_spec?: HazmatSpecification | null;
  regulatory_permits: string[];
}

export interface UtilizedTransportEquipment {
  equipment_reference: string;
  iso_size_type_code: string;
  seal_numbers: string[];
  tare_weight_kg?: string | number | null;
  verified_gross_mass_kg?: string | number | null;
  stowage_baplie_pos?: string | null;
}

export interface ChangeOfDestinationSpec {
  vessel_imo: string;
  voyage_number: string;
  container_iso6346: string;
  stowage_baplie_pos: string;
  accessible_without_restow: boolean;
  estimated_restow_moves: number;
  carrier_cod_cutoff_utc: string;
  original_port_of_discharge: string;
  requested_port_of_discharge: string;
  cod_request_submitted_utc: string;
}

export interface TransportLeg {
  leg_sequence: number;
  mode: CanonicalTransportMode;
  origin_locode: string;
  destination_locode: string;
  carrier_code: string;
  voyage_or_flight_number: string;
  scheduled_departure_utc: string;
  scheduled_arrival_utc: string;
}

export interface ShipmentRequest {
  internal_request_id: string;
  transport_mode: CanonicalTransportMode;
  transport_document_ref: string;
  document_status: DocumentStatus;
  customs_regime?: GCCCustomsRegime | null;
  issue_date: string;
  incoterms_code: string;
  mofaic_attested_invoice?: boolean | null;
  mofaic_attestation_ref?: string | null;
  parties: PartyIdentification[];
  legs: TransportLeg[];
  consignment_items: ConsignmentItem[];
  utilized_equipments: UtilizedTransportEquipment[];
  cod_amendment?: ChangeOfDestinationSpec | null;
}

export type ValidationReasonCode =
  | 'MISSING_MANDATORY_FIELD'
  | 'AMBIGUOUS_CANDIDATES'
  | 'UNVERIFIED_FORMAT'
  | 'CONFLICTING_DOCUMENT_VALUES'
  | 'CUTOFF_VIOLATION';

export interface MissingComplianceField {
  field_path: string;
  reason_code: ValidationReasonCode;
  message: string;
  candidate_values: string[];
  regulatory_reference: string;
}

export interface ValidationHold {
  status: 'VALIDATION_HOLD';
  autonomous_dispatch_blocked: true;
  requires_human_review: true;
  internal_request_id: string;
  held_at_utc: string;
  missing_compliance_fields: MissingComplianceField[];
}

export type MissingComplianceFields = ValidationHold;

export interface EdgeTelemetryOverride {
  edge_id: string;
  base_hours?: number | null;
  base_cost_per_teu_usd?: number | null;
  thermal_drift_c_per_hour?: number | null;
  capacity_teu?: number | null;
  source_provider: string;
  updated_at_utc: string;
}

export interface TelemetrySnapshot {
  disruption: DisruptionState;
  edge_overrides: Record<string, EdgeTelemetryOverride>;
  last_updated_utc: string;
  active_sources: string[];
  event_count: number;
}
