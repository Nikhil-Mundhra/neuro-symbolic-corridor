package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"math"
	"strings"
	"sync"
	"time"
)

// WorkflowStatus represents the deterministic Temporal-style execution state.
type WorkflowStatus string

const (
	StatusPending    WorkflowStatus = "PENDING"
	StatusSolved     WorkflowStatus = "SOLVED"
	StatusDispatched WorkflowStatus = "DISPATCHED_BONDED_CORRIDOR"
	StatusFailed     WorkflowStatus = "FAILED"
)

type StageTelemetry struct {
	Stage      string  `json:"stage"`
	Component  string  `json:"component"`
	DurationMs float64 `json:"duration_ms"`
	Status     string  `json:"status"`
}

type ApprovalReceipt struct {
	ApprovedBy      string   `json:"approved_by"`
	ApprovedAtUTC   string   `json:"approved_at_utc"`
	TransactionHash string   `json:"transaction_hash"`
	DispatchedAPIs  []string `json:"dispatched_apis"`
	ETIRSealID      string   `json:"etir_seal_id"`
}

type WorkflowRun struct {
	WorkflowID      string           `json:"workflow_id"`
	Status          WorkflowStatus   `json:"status"`
	CreatedAtUTC    string           `json:"created_at_utc"`
	TotalPipelineMs float64          `json:"total_pipeline_ms"`
	RetryCount      int              `json:"retry_count"`
	StageLatencies  []StageTelemetry `json:"stage_latencies"`
	Solution        json.RawMessage  `json:"solution"`
	ApprovalReceipt *ApprovalReceipt `json:"approval_receipt,omitempty"`
}

type DisruptionState struct {
	HormuzDelayHours           float64 `json:"hormuz_delay_hours"`
	JebelAliCongestionHours    float64 `json:"jebel_ali_congestion_hours"`
	RedSeaSurchargeUSD         float64 `json:"red_sea_surcharge_usd"`
	ReeferFault                bool    `json:"reefer_fault"`
	ReeferAmbientDriftCPerHour float64 `json:"reefer_ambient_drift_c_per_hour"`
	RequireCEPAZeroTariff      bool    `json:"require_cepa_zero_tariff"`
}

type EdgeTelemetryOverride struct {
	EdgeID               string   `json:"edge_id"`
	BaseHours            *float64 `json:"base_hours,omitempty"`
	BaseCostPerTEUUSD    *float64 `json:"base_cost_per_teu_usd,omitempty"`
	ThermalDriftCPerHour *float64 `json:"thermal_drift_c_per_hour,omitempty"`
	CapacityTEU          *int     `json:"capacity_teu,omitempty"`
	SourceProvider       string   `json:"source_provider"`
	UpdatedAtUTC         string   `json:"updated_at_utc"`
}

type TelemetrySnapshot struct {
	Disruption     DisruptionState                  `json:"disruption"`
	EdgeOverrides  map[string]EdgeTelemetryOverride `json:"edge_overrides"`
	LastUpdatedUTC string                           `json:"last_updated_utc"`
	ActiveSources  []string                         `json:"active_sources"`
	EventCount     int                              `json:"event_count"`
}

type PartyIdentification struct {
	Role              string  `json:"role"`
	LegalName         string  `json:"legal_name"`
	AddressLine       string  `json:"address_line"`
	CountryCode       string  `json:"country_code"`
	UaeTrn            *string `json:"uae_trn,omitempty"`
	UaeTrnFtaVerified bool    `json:"uae_trn_fta_verified"`
	DubaiCustomsCode  *string `json:"dubai_customs_code,omitempty"`
	EoriNumber        *string `json:"eori_number,omitempty"`
	OmanCrNumber      *string `json:"oman_cr_number,omitempty"`
	AtlpAeoID         *string `json:"atlp_aeo_id,omitempty"`
}

type ReeferSpecification struct {
	MinTempC      string  `json:"min_temp_c"`
	MaxTempC      string  `json:"max_temp_c"`
	SetpointTempC *string `json:"setpoint_temp_c,omitempty"`
	HumidityPct   *string `json:"humidity_pct,omitempty"`
}

type HazmatSpecification struct {
	UnNumber           string  `json:"un_number"`
	UnHazmatClass      string  `json:"un_hazmat_class"`
	PackingGroup       *string `json:"packing_group,omitempty"`
	ProperShippingName string  `json:"proper_shipping_name"`
	MsdsDocumentRef    *string `json:"msds_document_ref,omitempty"`
	Un383Certified     *bool   `json:"un383_certified,omitempty"`
}

type OriginPreferenceSpec struct {
	CountryOfOrigin         string  `json:"country_of_origin"`
	CertificateOfOriginNo   *string `json:"certificate_of_origin_no,omitempty"`
	PreferentialCepaClaimed bool    `json:"preferential_cepa_claimed"`
	CepaAgreementCode       *string `json:"cepa_agreement_code,omitempty"`
	CepaValueAddPct         *string `json:"cepa_value_add_pct,omitempty"`
}

type ConsignmentItem struct {
	ItemID               string               `json:"item_id"`
	GoodsDescription     string               `json:"goods_description"`
	HsCodeGcc12          *string              `json:"hs_code_gcc12,omitempty"`
	HsCodeWco6           *string              `json:"hs_code_wco6,omitempty"`
	Quantity             string               `json:"quantity"`
	PackageType          string               `json:"package_type"`
	GrossWeightKg        string               `json:"gross_weight_kg"`
	NetWeightKg          string               `json:"net_weight_kg"`
	CustomsValueAmount   string               `json:"customs_value_amount"`
	CustomsValueCurrency string               `json:"customs_value_currency"`
	Origin               OriginPreferenceSpec `json:"origin"`
	IsReefer             bool                 `json:"is_reefer"`
	ReeferSpec           *ReeferSpecification `json:"reefer_spec,omitempty"`
	IsDangerousGoods     bool                 `json:"is_dangerous_goods"`
	HazmatSpec           *HazmatSpecification `json:"hazmat_spec,omitempty"`
	RegulatoryPermits    []string             `json:"regulatory_permits"`
}

type UtilizedTransportEquipment struct {
	EquipmentReference  string   `json:"equipment_reference"`
	IsoSizeTypeCode     string   `json:"iso_size_type_code"`
	SealNumbers         []string `json:"seal_numbers"`
	TareWeightKg        *string  `json:"tare_weight_kg,omitempty"`
	VerifiedGrossMassKg *string  `json:"verified_gross_mass_kg,omitempty"`
	StowageBapliePos    *string  `json:"stowage_baplie_pos,omitempty"`
}

type ChangeOfDestinationSpec struct {
	VesselImo                string    `json:"vessel_imo"`
	VoyageNumber             string    `json:"voyage_number"`
	ContainerIso6346         string    `json:"container_iso6346"`
	StowageBapliePos         string    `json:"stowage_baplie_pos"`
	AccessibleWithoutRestow  bool      `json:"accessible_without_restow"`
	EstimatedRestowMoves     int       `json:"estimated_restow_moves"`
	CarrierCodCutoffUtc      time.Time `json:"carrier_cod_cutoff_utc"`
	OriginalPortOfDischarge  string    `json:"original_port_of_discharge"`
	RequestedPortOfDischarge string    `json:"requested_port_of_discharge"`
	CodRequestSubmittedUtc   time.Time `json:"cod_request_submitted_utc"`
}

type TransportLeg struct {
	LegSequence           int       `json:"leg_sequence"`
	Mode                  string    `json:"mode"`
	OriginLocode          string    `json:"origin_locode"`
	DestinationLocode     string    `json:"destination_locode"`
	CarrierCode           string    `json:"carrier_code"`
	VoyageOrFlightNumber  string    `json:"voyage_or_flight_number"`
	ScheduledDepartureUtc time.Time `json:"scheduled_departure_utc"`
	ScheduledArrivalUtc   time.Time `json:"scheduled_arrival_utc"`
}

type ShipmentRequest struct {
	InternalRequestID     string                       `json:"internal_request_id"`
	TransportMode         string                       `json:"transport_mode"`
	TransportDocumentRef  string                       `json:"transport_document_ref"`
	DocumentStatus        string                       `json:"document_status"`
	CustomsRegime         *string                      `json:"customs_regime,omitempty"`
	IssueDate             string                       `json:"issue_date"`
	IncotermsCode         string                       `json:"incoterms_code"`
	MofaicAttestedInvoice *bool                        `json:"mofaic_attested_invoice,omitempty"`
	MofaicAttestationRef  *string                      `json:"mofaic_attestation_ref,omitempty"`
	Parties               []PartyIdentification        `json:"parties"`
	Legs                  []TransportLeg               `json:"legs"`
	ConsignmentItems      []ConsignmentItem            `json:"consignment_items"`
	UtilizedEquipments    []UtilizedTransportEquipment `json:"utilized_equipments"`
	CodAmendment          *ChangeOfDestinationSpec     `json:"cod_amendment,omitempty"`
}

type MissingComplianceField struct {
	FieldPath           string   `json:"field_path"`
	ReasonCode          string   `json:"reason_code"`
	Message             string   `json:"message"`
	CandidateValues     []string `json:"candidate_values"`
	RegulatoryReference string   `json:"regulatory_reference"`
}

type ValidationHold struct {
	Status                    string                   `json:"status"`
	AutonomousDispatchBlocked bool                     `json:"autonomous_dispatch_blocked"`
	RequiresHumanReview       bool                     `json:"requires_human_review"`
	InternalRequestID         string                   `json:"internal_request_id"`
	HeldAtUtc                 time.Time                `json:"held_at_utc"`
	MissingComplianceFields   []MissingComplianceField `json:"missing_compliance_fields"`
}

type MissingComplianceFields = ValidationHold

// WorkflowStore provides thread-safe durable state management and SSE fan-out.
type WorkflowStore struct {
	mu          sync.RWMutex
	workflows   map[string]*WorkflowRun
	order       []string
	subscribers map[chan []byte]struct{}
	telemetry   TelemetrySnapshot
	db          PersistenceStore
}

func NewWorkflowStore() *WorkflowStore {
	return NewWorkflowStoreWithDB(nil)
}

func NewWorkflowStoreWithDB(db PersistenceStore) *WorkflowStore {
	store := &WorkflowStore{
		workflows:   make(map[string]*WorkflowRun),
		order:       make([]string, 0, 64),
		subscribers: make(map[chan []byte]struct{}),
		telemetry: TelemetrySnapshot{
			Disruption: DisruptionState{
				HormuzDelayHours:           72.0,
				JebelAliCongestionHours:    24.0,
				RedSeaSurchargeUSD:         1800.0,
				ReeferFault:                true,
				ReeferAmbientDriftCPerHour: 0.035,
				RequireCEPAZeroTariff:      true,
			},
			EdgeOverrides:  make(map[string]EdgeTelemetryOverride),
			LastUpdatedUTC: time.Now().UTC().Format(time.RFC3339),
			ActiveSources:  []string{},
			EventCount:     0,
		},
		db: db,
	}

	if db != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()

		if runs, err := db.LoadRecentWorkflows(ctx, 100); err != nil {
			log.Printf("warn: failed to hydrate workflows from persistence: %v", err)
		} else {
			for _, run := range runs {
				if run == nil || run.WorkflowID == "" {
					continue
				}
				if _, exists := store.workflows[run.WorkflowID]; !exists {
					store.order = append(store.order, run.WorkflowID)
				}
				store.workflows[run.WorkflowID] = run
			}
		}

		if snap, err := db.LoadTelemetrySnapshot(ctx); err != nil {
			log.Printf("warn: failed to hydrate telemetry snapshot from persistence: %v", err)
		} else if snap != nil {
			if snap.EdgeOverrides == nil {
				snap.EdgeOverrides = make(map[string]EdgeTelemetryOverride)
			}
			if snap.ActiveSources == nil {
				snap.ActiveSources = []string{}
			}
			store.telemetry = *snap
		}
	}

	return store
}

func (s *WorkflowStore) PersistenceMode() string {
	if s.db != nil {
		return "postgres"
	}
	return "memory"
}

func (s *WorkflowStore) persistWorkflow(run *WorkflowRun) {
	if s.db == nil || run == nil {
		return
	}
	if err := s.db.UpsertWorkflow(context.Background(), run); err != nil {
		log.Printf("warn: persist workflow %s failed: %v", run.WorkflowID, err)
	}
}

func (s *WorkflowStore) persistTelemetry(snap TelemetrySnapshot) {
	if s.db == nil {
		return
	}
	if err := s.db.SaveTelemetrySnapshot(context.Background(), snap); err != nil {
		log.Printf("warn: persist telemetry snapshot failed: %v", err)
	}
}

func (s *WorkflowStore) SaveSolved(run *WorkflowRun) {
	s.mu.Lock()
	if _, exists := s.workflows[run.WorkflowID]; !exists {
		s.order = append(s.order, run.WorkflowID)
	}
	s.workflows[run.WorkflowID] = run
	s.mu.Unlock()
	s.persistWorkflow(run)
	s.broadcast(run)
}

func (s *WorkflowStore) ListRecent(limit int) []*WorkflowRun {
	s.mu.RLock()
	defer s.mu.RUnlock()

	if limit <= 0 || limit > len(s.order) {
		limit = len(s.order)
	}
	res := make([]*WorkflowRun, 0, limit)
	for i := len(s.order) - 1; i >= 0 && len(res) < limit; i-- {
		if wf, ok := s.workflows[s.order[i]]; ok {
			res = append(res, wf)
		}
	}
	return res
}

func (s *WorkflowStore) ApproveAndDispatch(workflowID, operator string) (*WorkflowRun, error) {
	s.mu.Lock()
	wf, ok := s.workflows[workflowID]
	if !ok {
		s.mu.Unlock()
		return nil, errors.New("workflow not found")
	}
	if wf.Status == StatusDispatched && wf.ApprovalReceipt != nil {
		// Idempotent replay: return existing deterministic receipt
		s.mu.Unlock()
		return wf, nil
	}
	if wf.Status != StatusSolved {
		s.mu.Unlock()
		return nil, fmt.Errorf("cannot approve workflow in status %s", wf.Status)
	}

	now := time.Now().UTC().Format(time.RFC3339)
	hashBytes := sha256.Sum256([]byte(workflowID + "|" + operator + "|" + now))
	txHash := "0x" + hex.EncodeToString(hashBytes[:16])

	wf.Status = StatusDispatched
	wf.ApprovalReceipt = &ApprovalReceipt{
		ApprovedBy:      operator,
		ApprovedAtUTC:   now,
		TransactionHash: txHash,
		DispatchedAPIs:  buildDispatchedAPIs(wf.Solution),
		ETIRSealID:      fmt.Sprintf("ETIR-GCC-%s", workflowID),
	}
	s.mu.Unlock()

	s.persistWorkflow(wf)
	s.broadcast(wf)
	return wf, nil
}

func buildDispatchedAPIs(solution json.RawMessage) []string {
	apis := []string{
		"Dubai Trade / Mirsal 2 Transit Bond",
		"Maqta Gateway ATLP Manifest",
	}

	var parsed struct {
		CustomsPayloads *struct {
			OmanGreenCorridorETIR *struct {
				Activated bool `json:"activated"`
			} `json:"oman_green_corridor_etir"`
			EtihadCargoEAWB json.RawMessage `json:"etihad_cargo_eawb"`
		} `json:"customs_payloads"`
	}
	if len(solution) > 0 && json.Unmarshal(solution, &parsed) == nil && parsed.CustomsPayloads != nil {
		if parsed.CustomsPayloads.OmanGreenCorridorETIR != nil && parsed.CustomsPayloads.OmanGreenCorridorETIR.Activated {
			apis = append(apis, "Oman Bayan ↔ Dubai Customs Green Corridor e-TIR")
		}
		if len(parsed.CustomsPayloads.EtihadCargoEAWB) > 0 && string(parsed.CustomsPayloads.EtihadCargoEAWB) != "null" {
			apis = append(apis, "Etihad Cargo Spot e-AWB Reservation")
		}
	}
	return apis
}

func (s *WorkflowStore) Subscribe() chan []byte {
	ch := make(chan []byte, 16)
	s.mu.Lock()
	s.subscribers[ch] = struct{}{}
	s.mu.Unlock()
	return ch
}

func (s *WorkflowStore) Unsubscribe(ch chan []byte) {
	s.mu.Lock()
	delete(s.subscribers, ch)
	close(ch)
	s.mu.Unlock()
}

func (s *WorkflowStore) broadcastMessage(msg map[string]any) {
	payload, err := json.Marshal(msg)
	if err != nil {
		return
	}

	s.mu.RLock()
	for ch := range s.subscribers {
		select {
		case ch <- payload:
		default:
		}
	}
	s.mu.RUnlock()
}

func (s *WorkflowStore) broadcast(run *WorkflowRun) {
	s.broadcastMessage(map[string]any{
		"event":       "workflow_update",
		"workflow_id": run.WorkflowID,
		"status":      run.Status,
		"timestamp":   time.Now().UTC().Format(time.RFC3339),
	})
}

func (s *WorkflowStore) broadcastTelemetry(snap TelemetrySnapshot) {
	s.broadcastMessage(map[string]any{
		"event":          "telemetry_update",
		"active_sources": snap.ActiveSources,
		"event_count":    snap.EventCount,
		"disruption":     snap.Disruption,
		"edge_overrides": snap.EdgeOverrides,
		"timestamp":      snap.LastUpdatedUTC,
	})
}

func clampFloat(v, minVal, maxVal float64) float64 {
	return math.Min(maxVal, math.Max(minVal, v))
}

func (s *WorkflowStore) snapshotCopyLocked() TelemetrySnapshot {
	overridesCopy := make(map[string]EdgeTelemetryOverride, len(s.telemetry.EdgeOverrides))
	for k, v := range s.telemetry.EdgeOverrides {
		overridesCopy[k] = v
	}
	sourcesCopy := append([]string(nil), s.telemetry.ActiveSources...)
	return TelemetrySnapshot{
		Disruption:     s.telemetry.Disruption,
		EdgeOverrides:  overridesCopy,
		LastUpdatedUTC: s.telemetry.LastUpdatedUTC,
		ActiveSources:  sourcesCopy,
		EventCount:     s.telemetry.EventCount,
	}
}

func (s *WorkflowStore) recordTelemetrySourceLocked(source string) {
	for _, existing := range s.telemetry.ActiveSources {
		if existing == source {
			s.telemetry.LastUpdatedUTC = time.Now().UTC().Format(time.RFC3339)
			s.telemetry.EventCount++
			return
		}
	}
	s.telemetry.ActiveSources = append(s.telemetry.ActiveSources, source)
	s.telemetry.LastUpdatedUTC = time.Now().UTC().Format(time.RFC3339)
	s.telemetry.EventCount++
}

func (s *WorkflowStore) GetTelemetry() TelemetrySnapshot {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.snapshotCopyLocked()
}

type vizionJourneyEvent struct {
	JourneyType     string `json:"journey_type"`
	EventClassifier string `json:"event_classifier"`
	EventType       string `json:"event_type"`
	TransportMode   string `json:"transport_mode"`
}

type vizionShipmentLocation struct {
	TypeCode string `json:"type_code"`
	Locode   string `json:"locode"`
}

type vizionMilestone struct {
	Timestamp        string                 `json:"timestamp"`
	Description      string                 `json:"description"`
	Location         string                 `json:"location"`
	DelayHours       float64                `json:"delay_hours"`
	JourneyEvent     vizionJourneyEvent     `json:"journey_event"`
	ShipmentLocation vizionShipmentLocation `json:"shipment_location"`
}

type vizionWebhookPayload struct {
	CarrierSCAC string            `json:"carrier_scac"`
	ContainerID string            `json:"container_id"`
	Origin      string            `json:"origin"`
	Destination string            `json:"destination"`
	Milestones  []vizionMilestone `json:"milestones"`
}

type vizionWebhookEnvelope struct {
	ID          string               `json:"id"`
	Status      string               `json:"status"`
	ReferenceID string               `json:"reference_id"`
	Payload     vizionWebhookPayload `json:"payload"`
}

var portToSeaEdge = map[string]struct {
	edgeID    string
	baseHours float64
}{
	"AEJEA": {edgeID: "E_INNSA_AEJEA_SEA", baseHours: 96.0},
	"AEFJR": {edgeID: "E_INNSA_AEFJR_SEA", baseHours: 80.0},
	"OMSOH": {edgeID: "E_INNSA_OMSOH_SEA", baseHours: 78.0},
	"OMSLL": {edgeID: "E_INNSA_OMSLL_SEA", baseHours: 72.0},
}

func (s *WorkflowStore) ApplyVizionWebhook(body []byte) (TelemetrySnapshot, error) {
	var env vizionWebhookEnvelope
	if err := json.Unmarshal(body, &env); err != nil {
		return TelemetrySnapshot{}, fmt.Errorf("invalid vizion webhook json: %w", err)
	}
	if env.Payload.ContainerID == "" && len(env.Payload.Milestones) == 0 {
		return TelemetrySnapshot{}, errors.New("vizion webhook missing payload.container_id or milestones")
	}

	now := time.Now().UTC().Format(time.RFC3339)
	s.mu.Lock()
	for _, m := range env.Payload.Milestones {
		loc := strings.ToUpper(strings.TrimSpace(m.ShipmentLocation.Locode))
		if loc == "" {
			loc = strings.ToUpper(strings.TrimSpace(m.Location))
		}
		if m.DelayHours > 0 {
			if loc == "AEJEA" {
				s.telemetry.Disruption.JebelAliCongestionHours = clampFloat(m.DelayHours, 0, 168)
			} else if mapping, ok := portToSeaEdge[loc]; ok {
				adj := mapping.baseHours + m.DelayHours
				s.telemetry.EdgeOverrides[mapping.edgeID] = EdgeTelemetryOverride{
					EdgeID:         mapping.edgeID,
					BaseHours:      &adj,
					SourceProvider: "vizion_dcsa",
					UpdatedAtUTC:   now,
				}
			}
		}
		if strings.EqualFold(m.ShipmentLocation.TypeCode, "RTP") && strings.EqualFold(m.JourneyEvent.EventClassifier, "ACT") && m.DelayHours >= 12.0 {
			s.telemetry.Disruption.HormuzDelayHours = clampFloat(math.Max(s.telemetry.Disruption.HormuzDelayHours, m.DelayHours), 0, 240)
		}
	}
	s.recordTelemetrySourceLocked("vizion_dcsa")
	snap := s.snapshotCopyLocked()
	s.mu.Unlock()

	s.persistTelemetry(snap)
	s.broadcastTelemetry(snap)
	return snap, nil
}

type lynxTruData struct {
	OperatingMode string  `json:"operatingMode"`
	SetPointTemp  float64 `json:"setPointTemp"`
	ReturnAirTemp float64 `json:"returnAirTemp"`
	SupplyAirTemp float64 `json:"supplyAirTemp"`
	AmbientTemp   float64 `json:"ambientTemp"`
	AlarmStatus   string  `json:"alarmStatus"`
}

type lynxAlarm struct {
	AlarmCode   string `json:"alarmCode"`
	Description string `json:"description"`
	Severity    string `json:"severity"`
	Active      bool   `json:"active"`
}

type lynxWebhookPayload struct {
	EventID   string      `json:"eventId"`
	EventType string      `json:"eventType"`
	Timestamp string      `json:"timestamp"`
	AssetID   string      `json:"assetId"`
	TruData   lynxTruData `json:"truData"`
	Alarms    []lynxAlarm `json:"alarms"`
}

func (s *WorkflowStore) ApplyCarrierLynxWebhook(body []byte) (TelemetrySnapshot, error) {
	var msg lynxWebhookPayload
	if err := json.Unmarshal(body, &msg); err != nil {
		return TelemetrySnapshot{}, fmt.Errorf("invalid carrier lynx webhook json: %w", err)
	}
	if msg.EventType == "" && msg.AssetID == "" {
		return TelemetrySnapshot{}, errors.New("carrier lynx payload missing eventType and assetId")
	}

	hasCriticalAlarm := false
	for _, a := range msg.Alarms {
		if a.Active && (strings.EqualFold(a.Severity, "Critical") || strings.EqualFold(a.Severity, "High") || a.AlarmCode != "") {
			hasCriticalAlarm = true
			break
		}
	}
	tempExcursion := msg.TruData.ReturnAirTemp > 8.0
	faultActive := hasCriticalAlarm || tempExcursion

	s.mu.Lock()
	s.telemetry.Disruption.ReeferFault = faultActive
	if faultActive {
		drift := 0.035
		if msg.TruData.AmbientTemp > msg.TruData.SetPointTemp {
			drift = clampFloat((msg.TruData.AmbientTemp-msg.TruData.SetPointTemp)*0.0025, 0.015, 5.0)
		}
		s.telemetry.Disruption.ReeferAmbientDriftCPerHour = math.Round(drift*10000) / 10000
	} else {
		s.telemetry.Disruption.ReeferAmbientDriftCPerHour = 0.0
	}
	s.recordTelemetrySourceLocked("carrier_lynx")
	snap := s.snapshotCopyLocked()
	s.mu.Unlock()

	s.persistTelemetry(snap)
	s.broadcastTelemetry(snap)
	return snap, nil
}

type p44WebhookPayload struct {
	MasterShipmentID        string   `json:"masterShipmentId"`
	ShipmentID              string   `json:"shipmentId"`
	HormuzDelayHours        *float64 `json:"hormuz_delay_hours"`
	JebelAliCongestionHours *float64 `json:"jebel_ali_congestion_hours"`
	States                  []any    `json:"states"`
	Events                  []any    `json:"events"`
}

func (s *WorkflowStore) ApplyProject44Webhook(body []byte) (TelemetrySnapshot, error) {
	var msg p44WebhookPayload
	if err := json.Unmarshal(body, &msg); err != nil {
		return TelemetrySnapshot{}, fmt.Errorf("invalid project44 webhook json: %w", err)
	}
	if msg.MasterShipmentID == "" && msg.ShipmentID == "" && msg.HormuzDelayHours == nil && msg.JebelAliCongestionHours == nil {
		return TelemetrySnapshot{}, errors.New("project44 payload missing shipment identifier or delay update")
	}

	s.mu.Lock()
	if msg.HormuzDelayHours != nil {
		s.telemetry.Disruption.HormuzDelayHours = clampFloat(*msg.HormuzDelayHours, 0, 240)
	}
	if msg.JebelAliCongestionHours != nil {
		s.telemetry.Disruption.JebelAliCongestionHours = clampFloat(*msg.JebelAliCongestionHours, 0, 168)
	}
	s.recordTelemetrySourceLocked("project44")
	snap := s.snapshotCopyLocked()
	s.mu.Unlock()

	s.persistTelemetry(snap)
	s.broadcastTelemetry(snap)
	return snap, nil
}

type marineTrafficPortStat struct {
	Unlocode                 string  `json:"unlocode"`
	MedianAnchorageTimeHours float64 `json:"median_anchorage_time_hours"`
	MedianPortTimeHours      float64 `json:"median_port_time_hours"`
	VesselCount              int     `json:"vessel_count"`
	CallCount                int     `json:"call_count"`
	BaselineCallCount        int     `json:"baseline_call_count"`
}

type xenetaRefreshPayload struct {
	RedSeaSurchargeUSD *float64           `json:"red_sea_surcharge_usd"`
	EdgeRates          map[string]float64 `json:"edge_rates"`
}

type pollingRefreshRequest struct {
	MarineTraffic []marineTrafficPortStat `json:"marine_traffic"`
	Xeneta        *xenetaRefreshPayload   `json:"xeneta"`
}

func (s *WorkflowStore) ApplyPollingRefresh(body []byte) (TelemetrySnapshot, error) {
	var req pollingRefreshRequest
	if len(strings.TrimSpace(string(body))) > 0 {
		if err := json.Unmarshal(body, &req); err != nil {
			return TelemetrySnapshot{}, fmt.Errorf("invalid telemetry refresh json: %w", err)
		}
	}

	now := time.Now().UTC().Format(time.RFC3339)
	s.mu.Lock()
	if len(req.MarineTraffic) > 0 {
		for _, port := range req.MarineTraffic {
			code := strings.ToUpper(strings.TrimSpace(port.Unlocode))
			totalWait := port.MedianAnchorageTimeHours + port.MedianPortTimeHours
			if code == "AEJEA" {
				// Inverse Congestion Trap (docs/specs/telemetry_apis.md Sec. 1):
				// A >50% drop in AEJEA call count signals Hormuz loop suspension rather than clear transit.
				if port.BaselineCallCount > 0 && float64(port.CallCount) < 0.5*float64(port.BaselineCallCount) {
					s.telemetry.Disruption.HormuzDelayHours = clampFloat(math.Max(s.telemetry.Disruption.HormuzDelayHours, 72.0), 0, 240)
				}
				s.telemetry.Disruption.JebelAliCongestionHours = clampFloat(totalWait, 0, 168)
			} else if mapping, ok := portToSeaEdge[code]; ok {
				adjHours := mapping.baseHours + port.MedianAnchorageTimeHours
				s.telemetry.EdgeOverrides[mapping.edgeID] = EdgeTelemetryOverride{
					EdgeID:         mapping.edgeID,
					BaseHours:      &adjHours,
					SourceProvider: "marinetraffic_vi06",
					UpdatedAtUTC:   now,
				}
			}
		}
		s.recordTelemetrySourceLocked("marinetraffic_vi06")
	}

	if req.Xeneta != nil {
		if req.Xeneta.RedSeaSurchargeUSD != nil {
			s.telemetry.Disruption.RedSeaSurchargeUSD = clampFloat(*req.Xeneta.RedSeaSurchargeUSD, 0, 10000)
		}
		for edgeID, rateUSD := range req.Xeneta.EdgeRates {
			rateCopy := math.Max(0, rateUSD)
			ov := s.telemetry.EdgeOverrides[edgeID]
			ov.EdgeID = edgeID
			ov.BaseCostPerTEUUSD = &rateCopy
			ov.SourceProvider = "xeneta_v3"
			ov.UpdatedAtUTC = now
			s.telemetry.EdgeOverrides[edgeID] = ov
		}
		s.recordTelemetrySourceLocked("xeneta_v3")
	}

	if len(req.MarineTraffic) == 0 && req.Xeneta == nil {
		s.recordTelemetrySourceLocked("polling_heartbeat")
	}
	snap := s.snapshotCopyLocked()
	s.mu.Unlock()

	s.persistTelemetry(snap)
	s.broadcastTelemetry(snap)
	return snap, nil
}
