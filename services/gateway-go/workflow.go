package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
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

// WorkflowStore provides thread-safe durable state management and SSE fan-out.
type WorkflowStore struct {
	mu          sync.RWMutex
	workflows   map[string]*WorkflowRun
	order       []string
	subscribers map[chan []byte]struct{}
}

func NewWorkflowStore() *WorkflowStore {
	return &WorkflowStore{
		workflows:   make(map[string]*WorkflowRun),
		order:       make([]string, 0, 64),
		subscribers: make(map[chan []byte]struct{}),
	}
}

func (s *WorkflowStore) SaveSolved(run *WorkflowRun) {
	s.mu.Lock()
	if _, exists := s.workflows[run.WorkflowID]; !exists {
		s.order = append(s.order, run.WorkflowID)
	}
	s.workflows[run.WorkflowID] = run
	s.mu.Unlock()
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

func (s *WorkflowStore) broadcast(run *WorkflowRun) {
	payload, err := json.Marshal(map[string]any{
		"event":       "workflow_update",
		"workflow_id": run.WorkflowID,
		"status":      run.Status,
		"timestamp":   time.Now().UTC().Format(time.RFC3339),
	})
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
