package main

import (
	"encoding/json"
	"strings"
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
