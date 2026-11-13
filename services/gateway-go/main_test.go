package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestSolveAndApproveWorkflowLifecycle(t *testing.T) {
	mockSolver := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/health":
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`{"status":"ok"}`))
		case "/topology":
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"nodes":[],"edges":[]}`))
		case "/scenarios":
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`[]`))
		case "/parse-bol":
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"extraction_confidence":0.95}`))
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

	// Health check
	hReq := httptest.NewRequest(http.MethodGet, "/health", nil)
	hRec := httptest.NewRecorder()
	handler.ServeHTTP(hRec, hReq)
	if hRec.Code != http.StatusOK || !strings.Contains(hRec.Body.String(), `"solver_status":"ok"`) {
		t.Fatalf("unexpected health response: %d %s", hRec.Code, hRec.Body.String())
	}

	// CORS preflight
	optReq := httptest.NewRequest(http.MethodOptions, "/api/v1/solve", nil)
	optRec := httptest.NewRecorder()
	handler.ServeHTTP(optRec, optReq)
	if optRec.Code != http.StatusNoContent {
		t.Fatalf("expected 204 on OPTIONS, got %d", optRec.Code)
	}

	// Proxy GET & POST routes
	for _, tc := range []struct {
		method string
		path   string
		body   string
	}{
		{http.MethodGet, "/api/v1/corridor/topology", ""},
		{http.MethodGet, "/api/v1/scenarios", ""},
		{http.MethodPost, "/api/v1/parse-bol", `{"raw_text":"sample"}`},
	} {
		pReq := httptest.NewRequest(tc.method, tc.path, bytes.NewBufferString(tc.body))
		pRec := httptest.NewRecorder()
		handler.ServeHTTP(pRec, pReq)
		if pRec.Code != http.StatusOK {
			t.Fatalf("proxy %s %s failed: %d", tc.method, tc.path, pRec.Code)
		}
	}

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

	// List workflows
	listReq := httptest.NewRequest(http.MethodGet, "/api/v1/workflows", nil)
	listRec := httptest.NewRecorder()
	handler.ServeHTTP(listRec, listReq)
	if listRec.Code != http.StatusOK || !strings.Contains(listRec.Body.String(), run.WorkflowID) {
		t.Fatalf("expected workflow in list: %s", listRec.Body.String())
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

	// 4. Unknown workflow returns 404
	notFoundReq := httptest.NewRequest(http.MethodPost, "/api/v1/execute/wf-does-not-exist/approve", nil)
	notFoundRec := httptest.NewRecorder()
	handler.ServeHTTP(notFoundRec, notFoundReq)
	if notFoundRec.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", notFoundRec.Code)
	}
}

func TestCallSolverRetryAndErrorPaths(t *testing.T) {
	var attempts atomic.Int32
	flakySolver := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := attempts.Add(1)
		if n == 1 {
			w.WriteHeader(http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"solve_id":"retried","total_solver_ms":3.2,"stage_latencies":[]}`))
	}))
	defer flakySolver.Close()

	gw := NewGatewayServer(flakySolver.URL)
	respBytes, retries, err := gw.callSolverWithRetry(context.Background(), []byte(`{}`))
	if err != nil {
		t.Fatalf("expected retry to succeed, got err: %v", err)
	}
	if retries != 1 || !strings.Contains(string(respBytes), "retried") {
		t.Fatalf("expected 1 retry and retried payload, got retries=%d body=%s", retries, string(respBytes))
	}

	// Test round3 and newWorkflowID helpers
	if got := round3(12.34567); got != 12.346 {
		t.Fatalf("expected 12.346, got %v", got)
	}
	if id := newWorkflowID(); !strings.HasPrefix(id, "wf-") || len(id) < 8 {
		t.Fatalf("unexpected workflow id: %s", id)
	}

	// Test unreachable solver health
	downGW := NewGatewayServer("http://127.0.0.1:1")
	hReq := httptest.NewRequest(http.MethodGet, "/health", nil)
	hRec := httptest.NewRecorder()
	downGW.Routes().ServeHTTP(hRec, hReq)
	if !strings.Contains(hRec.Body.String(), `"solver_status":"unreachable"`) {
		t.Fatalf("expected unreachable solver_status, got %s", hRec.Body.String())
	}
}

func TestSSEEndpointStreamsEvents(t *testing.T) {
	gw := NewGatewayServer("http://127.0.0.1:1")
	ts := httptest.NewServer(gw.Routes())
	defer ts.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, ts.URL+"/api/v1/events", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("SSE connect failed: %v", err)
	}
	defer resp.Body.Close()

	reader := bufio.NewReader(resp.Body)
	line, err := reader.ReadString('\n')
	if err != nil || !strings.Contains(line, "event: connected") {
		t.Fatalf("expected connected SSE event, got %q (err=%v)", line, err)
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
