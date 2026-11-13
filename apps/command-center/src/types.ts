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
