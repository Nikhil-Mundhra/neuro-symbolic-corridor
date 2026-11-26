package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
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

	// Test 422 infeasibility passthrough without turning into 502
	unsatSolver := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusUnprocessableEntity)
		_, _ = w.Write([]byte(`{"detail":"No feasible route: all candidate routes failed Z3 formal verification (UNSAT)."}`))
	}))
	defer unsatSolver.Close()

	unsatGW := NewGatewayServer(unsatSolver.URL)
	uReq := httptest.NewRequest(http.MethodPost, "/api/v1/solve", bytes.NewBufferString(`{}`))
	uRec := httptest.NewRecorder()
	unsatGW.Routes().ServeHTTP(uRec, uReq)
	if uRec.Code != http.StatusUnprocessableEntity {
		t.Fatalf("expected 422 passthrough, got %d: %s", uRec.Code, uRec.Body.String())
	}
	if !strings.Contains(uRec.Body.String(), "UNSAT") {
		t.Fatalf("expected UNSAT detail in 422 body, got %s", uRec.Body.String())
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

func TestTelemetryWebhooksPollingAndValidateProxy(t *testing.T) {
	mockSolver := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/validate-shipment" {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusUnprocessableEntity)
			_, _ = w.Write([]byte(`{"status":"VALIDATION_HOLD","autonomous_dispatch_blocked":true,"requires_human_review":true}`))
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}))
	defer mockSolver.Close()

	gw := NewGatewayServer(mockSolver.URL)
	handler := gw.Routes()

	// 1. Validate-shipment proxy passthrough
	valReq := httptest.NewRequest(http.MethodPost, "/api/v1/validate-shipment", bytes.NewBufferString(`{}`))
	valRec := httptest.NewRecorder()
	handler.ServeHTTP(valRec, valReq)
	if valRec.Code != http.StatusUnprocessableEntity || !strings.Contains(valRec.Body.String(), "VALIDATION_HOLD") {
		t.Fatalf("unexpected validate-shipment proxy response: %d %s", valRec.Code, valRec.Body.String())
	}

	// 2. Initial telemetry state
	stReq := httptest.NewRequest(http.MethodGet, "/api/v1/telemetry/state", nil)
	stRec := httptest.NewRecorder()
	handler.ServeHTTP(stRec, stReq)
	if stRec.Code != http.StatusOK {
		t.Fatalf("expected 200 on telemetry state, got %d", stRec.Code)
	}

	// 3. Vizion HMAC-signed webhook
	t.Setenv("VIZION_WEBHOOK_SECRET", "vizion-secret")
	vizPayload := []byte(`{"id":"v-1","status":"data_received","payload":{"container_id":"KEIU9000798","carrier_scac":"MAEU","milestones":[{"shipment_location":{"type_code":"RTP","locode":"AEFJR"},"journey_event":{"event_classifier":"ACT","event_type":"ARRI"},"delay_hours":18.5}]}}`)
	badVizReq := httptest.NewRequest(http.MethodPost, "/api/v1/telemetry/webhooks/vizion", bytes.NewReader(vizPayload))
	badVizReq.Header.Set("X-Vizion-Signature", "sha256=deadbeef")
	badVizRec := httptest.NewRecorder()
	handler.ServeHTTP(badVizRec, badVizReq)
	if badVizRec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401 for bad vizion hmac, got %d", badVizRec.Code)
	}

	mac := hmac.New(sha256.New, []byte("vizion-secret"))
	mac.Write(vizPayload)
	sig := "sha256=" + hex.EncodeToString(mac.Sum(nil))
	okVizReq := httptest.NewRequest(http.MethodPost, "/api/v1/telemetry/webhooks/vizion", bytes.NewReader(vizPayload))
	okVizReq.Header.Set("X-Vizion-Signature", sig)
	okVizRec := httptest.NewRecorder()
	handler.ServeHTTP(okVizRec, okVizReq)
	if okVizRec.Code != http.StatusOK {
		t.Fatalf("expected 200 for valid vizion webhook, got %d: %s", okVizRec.Code, okVizRec.Body.String())
	}

	// 4. Carrier Lynx Push webhook
	t.Setenv("CARRIER_LYNX_API_KEY", "lynx-key-123")
	badLynxReq := httptest.NewRequest(http.MethodPost, "/api/v1/telemetry/webhooks/carrier-lynx", bytes.NewBufferString(`{}`))
	badLynxReq.Header.Set("x-lynx-api-key", "wrong")
	badLynxRec := httptest.NewRecorder()
	handler.ServeHTTP(badLynxRec, badLynxReq)
	if badLynxRec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401 for invalid lynx key, got %d", badLynxRec.Code)
	}

	lynxBody := `{"eventId":"lx-1","eventType":"ALARM_TRIGGERED","assetId":"CT-884","truData":{"setPointTemp":5.0,"returnAirTemp":9.8,"ambientTemp":42.0},"alarms":[{"alarmCode":"AL22","severity":"Critical","active":true}]}`
	okLynxReq := httptest.NewRequest(http.MethodPost, "/api/v1/telemetry/webhooks/carrier-lynx", bytes.NewBufferString(lynxBody))
	okLynxReq.Header.Set("x-lynx-api-key", "lynx-key-123")
	okLynxRec := httptest.NewRecorder()
	handler.ServeHTTP(okLynxRec, okLynxReq)
	if okLynxRec.Code != http.StatusOK {
		t.Fatalf("expected 200 for carrier lynx webhook, got %d", okLynxRec.Code)
	}

	// 5. Project44 webhook + MarineTraffic/Xeneta polling refresh
	p44Req := httptest.NewRequest(http.MethodPost, "/api/v1/telemetry/webhooks/project44", bytes.NewBufferString(`{"masterShipmentId":"P44-1","jebel_ali_congestion_hours":30}`))
	p44Rec := httptest.NewRecorder()
	handler.ServeHTTP(p44Rec, p44Req)
	if p44Rec.Code != http.StatusOK {
		t.Fatalf("expected 200 for p44 webhook, got %d", p44Rec.Code)
	}

	refBody := `{"marine_traffic":[{"unlocode":"AEJEA","median_anchorage_time_hours":8.0,"median_port_time_hours":4.0,"call_count":20,"baseline_call_count":100},{"unlocode":"AEFJR","median_anchorage_time_hours":168.0,"median_port_time_hours":12.0}],"xeneta":{"red_sea_surcharge_usd":2450,"edge_rates":{"E_AEAUH_EUFRA_AIR":5100}}}`
	refReq := httptest.NewRequest(http.MethodPost, "/api/v1/telemetry/refresh", bytes.NewBufferString(refBody))
	refRec := httptest.NewRecorder()
	handler.ServeHTTP(refRec, refReq)
	if refRec.Code != http.StatusOK {
		t.Fatalf("expected 200 for telemetry refresh, got %d", refRec.Code)
	}

	var snap TelemetrySnapshot
	if err := json.Unmarshal(refRec.Body.Bytes(), &snap); err != nil {
		t.Fatalf("unmarshal TelemetrySnapshot: %v", err)
	}
	if snap.Disruption.HormuzDelayHours < 72.0 || snap.Disruption.RedSeaSurchargeUSD != 2450.0 || !snap.Disruption.ReeferFault {
		t.Fatalf("unexpected telemetry snapshot state: %+v", snap)
	}
	if _, ok := snap.EdgeOverrides["E_INNSA_AEFJR_SEA"]; !ok {
		t.Fatalf("expected E_INNSA_AEFJR_SEA override from MarineTraffic VI06 refresh")
	}
}

func TestHandleSolveInjectsActiveEdgeOverrides(t *testing.T) {
	var receivedPayloads []map[string]any
	var mu sync.Mutex

	mockSolver := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/health" {
			w.WriteHeader(http.StatusOK)
			return
		}
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		mu.Lock()
		receivedPayloads = append(receivedPayloads, body)
		mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"solve_id":"ov-1","total_solver_ms":10.0,"stage_latencies":[]}`))
	}))
	defer mockSolver.Close()

	gw := NewGatewayServer(mockSolver.URL)
	handler := gw.Routes()

	// Verify /health exposes persistence mode
	hReq := httptest.NewRequest(http.MethodGet, "/health", nil)
	hRec := httptest.NewRecorder()
	handler.ServeHTTP(hRec, hReq)
	if !strings.Contains(hRec.Body.String(), `"persistence":"memory"`) {
		t.Fatalf("expected memory persistence mode in /health, got %s", hRec.Body.String())
	}

	// Seed a MarineTraffic VI06 edge override on AEFJR
	refBody := `{"marine_traffic":[{"unlocode":"AEFJR","median_anchorage_time_hours":120.0,"median_port_time_hours":8.0}]}`
	refReq := httptest.NewRequest(http.MethodPost, "/api/v1/telemetry/refresh", bytes.NewBufferString(refBody))
	refRec := httptest.NewRecorder()
	handler.ServeHTTP(refRec, refReq)
	if refRec.Code != http.StatusOK {
		t.Fatalf("expected 200 on refresh, got %d", refRec.Code)
	}

	// 1. Solve without edge_overrides -> gateway injects active overrides
	solveReq := httptest.NewRequest(http.MethodPost, "/api/v1/solve", bytes.NewBufferString(`{"pareto_alpha":0.55}`))
	solveRec := httptest.NewRecorder()
	handler.ServeHTTP(solveRec, solveReq)
	if solveRec.Code != http.StatusOK {
		t.Fatalf("expected 200 on solve, got %d", solveRec.Code)
	}

	// 2. Solve with explicit edge_overrides -> gateway preserves caller overrides
	explicitReq := httptest.NewRequest(http.MethodPost, "/api/v1/solve", bytes.NewBufferString(`{"pareto_alpha":0.55,"edge_overrides":{}}`))
	explicitRec := httptest.NewRecorder()
	handler.ServeHTTP(explicitRec, explicitReq)
	if explicitRec.Code != http.StatusOK {
		t.Fatalf("expected 200 on explicit solve, got %d", explicitRec.Code)
	}

	mu.Lock()
	defer mu.Unlock()
	if len(receivedPayloads) != 2 {
		t.Fatalf("expected 2 solver calls, got %d", len(receivedPayloads))
	}
	injected, ok := receivedPayloads[0]["edge_overrides"].(map[string]any)
	if !ok || injected["E_INNSA_AEFJR_SEA"] == nil {
		t.Fatalf("expected E_INNSA_AEFJR_SEA injected into solver payload, got %+v", receivedPayloads[0])
	}
	explicit, ok := receivedPayloads[1]["edge_overrides"].(map[string]any)
	if !ok || len(explicit) != 0 {
		t.Fatalf("expected caller explicit empty edge_overrides preserved, got %+v", receivedPayloads[1])
	}
}
