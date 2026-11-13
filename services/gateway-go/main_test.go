package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
)

func TestSolveAndApproveWorkflowLifecycle(t *testing.T) {
	mockSolver := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/health":
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`{"status":"ok"}`))
		case "/solve":
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{
				"solve_id": "abc123",
				"total_solver_ms": 18.4,
				"stage_latencies": [
					{"stage": "T-GNN Warm-Start", "component": "PyG", "duration_ms": 2.1, "status": "DONE"},
					{"stage": "Z3 SMT + HiGHS MILP", "component": "Z3+HiGHS", "duration_ms": 15.2, "status": "DONE"}
				]
			}`))
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer mockSolver.Close()

	gw := NewGatewayServer(mockSolver.URL)
	handler := gw.Routes()

	// 1. Trigger /api/v1/solve
	req := httptest.NewRequest(http.MethodPost, "/api/v1/solve", bytes.NewBufferString(`{"test":true}`))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}

	var run WorkflowRun
	if err := json.Unmarshal(rec.Body.Bytes(), &run); err != nil {
		t.Fatalf("unmarshal workflow: %v", err)
	}
	if run.Status != StatusSolved {
		t.Fatalf("expected SOLVED, got %s", run.Status)
	}
	if len(run.StageLatencies) != 4 {
		t.Fatalf("expected 4 telemetry stages, got %d", len(run.StageLatencies))
	}

	// 2. Approve & Dispatch 1-click reroute
	approveReq := httptest.NewRequest(
		http.MethodPost,
		"/api/v1/execute/"+run.WorkflowID+"/approve",
		bytes.NewBufferString(`{"operator":"NYUAD Dispatcher"}`),
	)
	approveRec := httptest.NewRecorder()
	handler.ServeHTTP(approveRec, approveReq)

	if approveRec.Code != http.StatusOK {
		t.Fatalf("expected 200 on approve, got %d", approveRec.Code)
	}

	var dispatched WorkflowRun
	if err := json.Unmarshal(approveRec.Body.Bytes(), &dispatched); err != nil {
		t.Fatalf("unmarshal dispatched: %v", err)
	}
	if dispatched.Status != StatusDispatched {
		t.Fatalf("expected DISPATCHED_BONDED_CORRIDOR, got %s", dispatched.Status)
	}
	if dispatched.ApprovalReceipt == nil || dispatched.ApprovalReceipt.TransactionHash == "" {
		t.Fatalf("expected populated approval receipt")
	}

	// 3. Idempotent second approval returns same tx hash
	approveReq2 := httptest.NewRequest(http.MethodPost, "/api/v1/execute/"+run.WorkflowID+"/approve", nil)
	approveRec2 := httptest.NewRecorder()
	handler.ServeHTTP(approveRec2, approveReq2)

	var replay WorkflowRun
	_ = json.Unmarshal(approveRec2.Body.Bytes(), &replay)
	if replay.ApprovalReceipt.TransactionHash != dispatched.ApprovalReceipt.TransactionHash {
		t.Fatalf("expected idempotent tx hash")
	}
}

func TestConcurrentWorkflowIngestion(t *testing.T) {
	mockSolver := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"solve_id":"par","total_solver_ms":5.0,"stage_latencies":[]}`))
	}))
	defer mockSolver.Close()

	gw := NewGatewayServer(mockSolver.URL)
	handler := gw.Routes()

	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			req := httptest.NewRequest(http.MethodPost, "/api/v1/solve", bytes.NewBufferString(`{}`))
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)
			if rec.Code != http.StatusOK {
				t.Errorf("unexpected status %d", rec.Code)
			}
		}()
	}
	wg.Wait()

	recent := gw.store.ListRecent(50)
	if len(recent) != 20 {
		t.Fatalf("expected 20 stored workflows, got %d", len(recent))
	}
}
