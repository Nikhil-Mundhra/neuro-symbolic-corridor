package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"sort"
	"strings"
	"testing"
	"time"
)

// TestLiveSolverEndToEndContractAndSLAGate executes L3/L4 cross-service integration tests
// against a live Python Neuro-Symbolic Solver instance when LIVE_SOLVER_URL is set.
// When LIVE_SOLVER_URL is unset, it skips cleanly so fast L1 unit tests remain hermetic.
func TestLiveSolverEndToEndContractAndSLAGate(t *testing.T) {
	liveSolverURL := os.Getenv("LIVE_SOLVER_URL")
	if liveSolverURL == "" {
		t.Skip("Skipping live cross-service E2E gate (set LIVE_SOLVER_URL=http://127.0.0.1:8001 to run)")
	}

	gw := NewGatewayServer(liveSolverURL)
	ts := httptest.NewServer(gw.Routes())
	defer ts.Close()

	client := &http.Client{Timeout: 5 * time.Second}

	// 1. Verify /health reports both gateway-go and solver-py healthy
	healthResp, err := client.Get(ts.URL + "/health")
	if err != nil {
		t.Fatalf("GET /health failed: %v", err)
	}
	defer healthResp.Body.Close()
	if healthResp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200 on /health, got %d", healthResp.StatusCode)
	}
	var healthData map[string]any
	if err := json.NewDecoder(healthResp.Body).Decode(&healthData); err != nil {
		t.Fatalf("decode /health: %v", err)
	}
	if healthData["solver_status"] != "ok" {
		t.Fatalf("expected live solver_status=ok, got %v", healthData["solver_status"])
	}

	// 2. Verify /api/v1/corridor/topology proxy returns 10 nodes & 15 edges
	topoResp, err := client.Get(ts.URL + "/api/v1/corridor/topology")
	if err != nil {
		t.Fatalf("GET /api/v1/corridor/topology failed: %v", err)
	}
	defer topoResp.Body.Close()
	var topo struct {
		Nodes []map[string]any `json:"nodes"`
		Edges []map[string]any `json:"edges"`
	}
	if err := json.NewDecoder(topoResp.Body).Decode(&topo); err != nil {
		t.Fatalf("decode topology: %v", err)
	}
	if len(topo.Nodes) != 10 || len(topo.Edges) != 15 {
		t.Fatalf("expected 10 nodes and 15 edges, got %d nodes and %d edges", len(topo.Nodes), len(topo.Edges))
	}

	// 3. Connect live SSE stream before triggering solve & approval
	sseCtx, sseCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer sseCancel()
	sseReq, _ := http.NewRequestWithContext(sseCtx, http.MethodGet, ts.URL+"/api/v1/events", nil)
	sseResp, err := client.Do(sseReq)
	if err != nil {
		t.Fatalf("SSE connect failed: %v", err)
	}
	defer sseResp.Body.Close()
	sseReader := bufio.NewReader(sseResp.Body)
	connLine, err := sseReader.ReadString('\n')
	if err != nil || !strings.Contains(connLine, "event: connected") {
		t.Fatalf("expected connected SSE event, got %q (err=%v)", connLine, err)
	}

	// 4. Fetch scenarios and run /api/v1/parse-bol
	scenResp, err := client.Get(ts.URL + "/api/v1/scenarios")
	if err != nil {
		t.Fatalf("GET /api/v1/scenarios failed: %v", err)
	}
	defer scenResp.Body.Close()
	var scenarios []struct {
		ID                string          `json:"id"`
		RawBoLText        string          `json:"raw_bol_text"`
		Shipment          json.RawMessage `json:"shipment"`
		DefaultDisruption json.RawMessage `json:"default_disruption"`
	}
	if err := json.NewDecoder(scenResp.Body).Decode(&scenarios); err != nil || len(scenarios) == 0 {
		t.Fatalf("failed to decode scenarios: %v", err)
	}

	parseBody := fmt.Sprintf(`{"raw_text":%q}`, scenarios[0].RawBoLText)
	parseResp, err := client.Post(ts.URL+"/api/v1/parse-bol", "application/json", strings.NewReader(parseBody))
	if err != nil {
		t.Fatalf("POST /api/v1/parse-bol failed: %v", err)
	}
	defer parseResp.Body.Close()
	if parseResp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200 on /api/v1/parse-bol, got %d", parseResp.StatusCode)
	}

	// 5. Execute 20 End-to-End Solve requests across scenarios to enforce <400ms P99 E2E SLA
	e2eLatencies := make([]float64, 0, 20)
	var lastWorkflow WorkflowRun

	for i := 0; i < 20; i++ {
		sc := scenarios[i%len(scenarios)]
		solvePayload := fmt.Sprintf(
			`{"shipment":%s,"disruption":%s,"pareto_alpha":0.55}`,
			string(sc.Shipment),
			string(sc.DefaultDisruption),
		)
		t0 := time.Now()
		sResp, err := client.Post(ts.URL+"/api/v1/solve", "application/json", bytes.NewBufferString(solvePayload))
		if err != nil {
			t.Fatalf("POST /api/v1/solve iteration %d failed: %v", i, err)
		}
		rawBytes, _ := io.ReadAll(sResp.Body)
		_ = sResp.Body.Close()
		wallMs := float64(time.Since(t0).Microseconds()) / 1000.0

		if sResp.StatusCode != http.StatusOK {
			t.Fatalf("iteration %d expected 200, got %d: %s", i, sResp.StatusCode, string(rawBytes))
		}
		if err := json.Unmarshal(rawBytes, &lastWorkflow); err != nil {
			t.Fatalf("unmarshal WorkflowRun: %v", err)
		}
		if lastWorkflow.Status != StatusSolved {
			t.Fatalf("expected status SOLVED, got %s", lastWorkflow.Status)
		}
		// Must have 5 telemetry stages: Go Ingest + 3 Python Solver stages + Durable Stream Push
		if len(lastWorkflow.StageLatencies) != 5 {
			t.Fatalf("expected 5 stage_latencies in E2E run, got %d", len(lastWorkflow.StageLatencies))
		}
		// Stage 1 (Go Gateway Ingest) must be < 10ms
		if lastWorkflow.StageLatencies[0].DurationMs >= 10.0 {
			t.Fatalf("Stage 1 Go Gateway Ingest exceeded 10ms SLA: %.3fms", lastWorkflow.StageLatencies[0].DurationMs)
		}

		// Verify Zero Regulatory Hallucination on returned solution
		var sol struct {
			OptimalRoute struct {
				Z3Status string `json:"z3_status"`
			} `json:"optimal_route"`
		}
		if err := json.Unmarshal(lastWorkflow.Solution, &sol); err != nil {
			t.Fatalf("unmarshal nested solution: %v", err)
		}
		if sol.OptimalRoute.Z3Status != "SAT" {
			t.Fatalf("Zero Regulatory Hallucination violation: optimal route Z3 status is %s", sol.OptimalRoute.Z3Status)
		}

		e2eLatencies = append(e2eLatencies, wallMs)
	}

	sort.Float64s(e2eLatencies)
	p99Index := int(float64(len(e2eLatencies))*0.99) - 1
	if p99Index < 0 {
		p99Index = 0
	}
	p99Ms := e2eLatencies[p99Index]
	t.Logf("Live Cross-Service E2E Latency (20 runs): P50=%.2fms, P99=%.2fms (SLA < 400ms)", e2eLatencies[len(e2eLatencies)/2], p99Ms)
	if p99Ms >= 400.0 {
		t.Fatalf("End-to-End P99 latency %.2fms breached 400ms SLA", p99Ms)
	}

	// 6. Approve & Dispatch last workflow and verify deterministic receipt
	appResp, err := client.Post(
		ts.URL+"/api/v1/execute/"+lastWorkflow.WorkflowID+"/approve",
		"application/json",
		strings.NewReader(`{"operator":"E2E Contract Gate"}`),
	)
	if err != nil {
		t.Fatalf("approve failed: %v", err)
	}
	defer appResp.Body.Close()
	if appResp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200 on approve, got %d", appResp.StatusCode)
	}
	var approvedWf WorkflowRun
	if err := json.NewDecoder(appResp.Body).Decode(&approvedWf); err != nil {
		t.Fatalf("decode approvedWf: %v", err)
	}
	if approvedWf.Status != StatusDispatched || approvedWf.ApprovalReceipt == nil {
		t.Fatalf("expected DISPATCHED_BONDED_CORRIDOR with receipt, got %+v", approvedWf)
	}
}
