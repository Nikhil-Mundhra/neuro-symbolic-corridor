package main

import (
	"context"
	"encoding/json"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestWorkflowStoreListRecentAndErrorCases(t *testing.T) {
	store := NewWorkflowStore()

	// Empty list
	if got := store.ListRecent(10); len(got) != 0 {
		t.Fatalf("expected 0 workflows, got %d", len(got))
	}

	// Missing workflow approval
	if _, err := store.ApproveAndDispatch("wf-missing", "op"); err == nil {
		t.Fatalf("expected error for missing workflow")
	}

	// Non-SOLVED workflow cannot be approved
	store.SaveSolved(&WorkflowRun{
		WorkflowID: "wf-pending",
		Status:     StatusPending,
		Solution:   json.RawMessage(`{}`),
	})
	if _, err := store.ApproveAndDispatch("wf-pending", "op"); err == nil {
		t.Fatalf("expected error approving PENDING workflow")
	}

	// Save 3 workflows and test ListRecent limit slicing
	store.SaveSolved(&WorkflowRun{WorkflowID: "wf-1", Status: StatusSolved, Solution: json.RawMessage(`{}`)})
	store.SaveSolved(&WorkflowRun{WorkflowID: "wf-2", Status: StatusSolved, Solution: json.RawMessage(`{}`)})
	store.SaveSolved(&WorkflowRun{WorkflowID: "wf-3", Status: StatusSolved, Solution: json.RawMessage(`{}`)})

	all := store.ListRecent(0)
	if len(all) != 4 {
		t.Fatalf("expected 4 workflows for limit=0, got %d", len(all))
	}
	recent2 := store.ListRecent(2)
	if len(recent2) != 2 || recent2[0].WorkflowID != "wf-3" || recent2[1].WorkflowID != "wf-2" {
		t.Fatalf("unexpected recent2 ordering: %+v", recent2)
	}
}

func TestWorkflowStoreSubscribeUnsubscribeAndBroadcast(t *testing.T) {
	store := NewWorkflowStore()
	ch := store.Subscribe()

	store.SaveSolved(&WorkflowRun{
		WorkflowID: "wf-sse-1",
		Status:     StatusSolved,
		Solution:   json.RawMessage(`{}`),
	})

	select {
	case msg := <-ch:
		if !strings.Contains(string(msg), "wf-sse-1") {
			t.Fatalf("expected workflow id in SSE payload, got %s", string(msg))
		}
	case <-time.After(time.Second):
		t.Fatalf("timed out waiting for SSE broadcast")
	}

	store.Unsubscribe(ch)
	if _, open := <-ch; open {
		t.Fatalf("expected channel to be closed after Unsubscribe")
	}
}

func TestBuildDispatchedAPIsMatchesCustomsPayloads(t *testing.T) {
	seaOnly := json.RawMessage(`{
		"customs_payloads": {
			"oman_green_corridor_etir": {"activated": false},
			"etihad_cargo_eawb": null
		}
	}`)
	seaAPIs := buildDispatchedAPIs(seaOnly)
	if len(seaAPIs) != 2 {
		t.Fatalf("expected 2 APIs for sea-only route, got %v", seaAPIs)
	}

	airGreen := json.RawMessage(`{
		"customs_payloads": {
			"oman_green_corridor_etir": {"activated": true},
			"etihad_cargo_eawb": {"origin_airport": "AUH"}
		}
	}`)
	airAPIs := buildDispatchedAPIs(airGreen)
	if len(airAPIs) != 4 {
		t.Fatalf("expected 4 APIs for green+air route, got %v", airAPIs)
	}
}

func TestTelemetryInverseCongestionTrapAndSSEBroadcast(t *testing.T) {
	store := NewWorkflowStore()
	ch := store.Subscribe()
	defer store.Unsubscribe(ch)

	// Reset Hormuz delay to 0 via P44, then trigger MarineTraffic AEJEA call drop >50%
	_, err := store.ApplyProject44Webhook([]byte(`{"masterShipmentId":"P44-99","hormuz_delay_hours":0,"jebel_ali_congestion_hours":8}`))
	if err != nil {
		t.Fatalf("ApplyProject44Webhook failed: %v", err)
	}
	<-ch // drain P44 event

	snap, err := store.ApplyPollingRefresh([]byte(`{"marine_traffic":[{"unlocode":"AEJEA","median_anchorage_time_hours":4.0,"median_port_time_hours":5.0,"call_count":15,"baseline_call_count":100}]}`))
	if err != nil {
		t.Fatalf("ApplyPollingRefresh failed: %v", err)
	}
	if snap.Disruption.HormuzDelayHours < 72.0 {
		t.Fatalf("Inverse Congestion Trap failed to escalate HormuzDelayHours: %v", snap.Disruption.HormuzDelayHours)
	}

	select {
	case msg := <-ch:
		if !strings.Contains(string(msg), `"event":"telemetry_update"`) {
			t.Fatalf("expected telemetry_update SSE event, got %s", string(msg))
		}
	case <-time.After(time.Second):
		t.Fatalf("timed out waiting for telemetry_update SSE broadcast")
	}
}

type mockPersistenceStore struct {
	mu        sync.Mutex
	workflows []*WorkflowRun
	upserts   int
	telemetry *TelemetrySnapshot
	telSaves  int
}

func (m *mockPersistenceStore) InitSchema(ctx context.Context) error { return nil }

func (m *mockPersistenceStore) LoadRecentWorkflows(ctx context.Context, limit int) ([]*WorkflowRun, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return append([]*WorkflowRun(nil), m.workflows...), nil
}

func (m *mockPersistenceStore) UpsertWorkflow(ctx context.Context, run *WorkflowRun) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.upserts++
	m.workflows = append(m.workflows, run)
	return nil
}

func (m *mockPersistenceStore) LoadTelemetrySnapshot(ctx context.Context) (*TelemetrySnapshot, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.telemetry, nil
}

func (m *mockPersistenceStore) SaveTelemetrySnapshot(ctx context.Context, snap TelemetrySnapshot) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.telSaves++
	cp := snap
	m.telemetry = &cp
	return nil
}

func (m *mockPersistenceStore) Close() {}

func TestWorkflowStorePersistenceHydrateAndWriteThrough(t *testing.T) {
	seedSnap := TelemetrySnapshot{
		Disruption: DisruptionState{
			HormuzDelayHours:        96.0,
			JebelAliCongestionHours: 32.0,
			RedSeaSurchargeUSD:      2100.0,
			ReeferFault:             true,
		},
		EdgeOverrides:  map[string]EdgeTelemetryOverride{},
		LastUpdatedUTC: "2026-11-24T00:00:00Z",
		ActiveSources:  []string{"marinetraffic_vi06"},
		EventCount:     3,
	}
	mockDB := &mockPersistenceStore{
		workflows: []*WorkflowRun{
			{
				WorkflowID:   "wf-hydrated",
				Status:       StatusSolved,
				CreatedAtUTC: "2026-11-24T00:00:00Z",
			},
		},
		telemetry: &seedSnap,
	}

	store := NewWorkflowStoreWithDB(mockDB)
	if store.PersistenceMode() != "postgres" {
		t.Fatalf("expected persistence mode postgres, got %s", store.PersistenceMode())
	}
	recent := store.ListRecent(10)
	if len(recent) != 1 || recent[0].WorkflowID != "wf-hydrated" {
		t.Fatalf("expected hydrated workflow wf-hydrated, got %+v", recent)
	}
	if store.GetTelemetry().EventCount != 3 || store.GetTelemetry().Disruption.HormuzDelayHours != 96.0 {
		t.Fatalf("expected hydrated telemetry snapshot, got %+v", store.GetTelemetry())
	}

	store.SaveSolved(&WorkflowRun{
		WorkflowID:   "wf-new",
		Status:       StatusSolved,
		CreatedAtUTC: "2026-11-24T00:05:00Z",
	})
	if _, err := store.ApproveAndDispatch("wf-new", "Lead Dispatcher"); err != nil {
		t.Fatalf("approve failed: %v", err)
	}
	if _, err := store.ApplyPollingRefresh([]byte(`{"xeneta":{"red_sea_surcharge_usd":2600}}`)); err != nil {
		t.Fatalf("refresh failed: %v", err)
	}

	mockDB.mu.Lock()
	defer mockDB.mu.Unlock()
	if mockDB.upserts != 2 {
		t.Fatalf("expected 2 UpsertWorkflow calls (solve + approve), got %d", mockDB.upserts)
	}
	if mockDB.telSaves != 1 {
		t.Fatalf("expected 1 SaveTelemetrySnapshot call, got %d", mockDB.telSaves)
	}
}
