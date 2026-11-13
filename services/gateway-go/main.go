package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"
)

type GatewayServer struct {
	solverURL  string
	httpClient *http.Client
	store      *WorkflowStore
}

func NewGatewayServer(solverURL string) *GatewayServer {
	return &GatewayServer{
		solverURL: strings.TrimRight(solverURL, "/"),
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
		store: NewWorkflowStore(),
	}
}

func newWorkflowID() string {
	b := make([]byte, 6)
	if _, err := rand.Read(b); err != nil {
		return fmt.Sprintf("wf-%d", time.Now().UnixNano())
	}
	return "wf-" + hex.EncodeToString(b)
}

func withCORS(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func (g *GatewayServer) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", g.handleHealth)
	mux.HandleFunc("GET /api/v1/corridor/topology", g.proxyGET("/topology"))
	mux.HandleFunc("GET /api/v1/scenarios", g.proxyGET("/scenarios"))
	mux.HandleFunc("POST /api/v1/parse-bol", g.proxyPOST("/parse-bol"))
	mux.HandleFunc("POST /api/v1/solve", g.handleSolve)
	mux.HandleFunc("GET /api/v1/workflows", g.handleListWorkflows)
	mux.HandleFunc("POST /api/v1/execute/{id}/approve", g.handleApprove)
	mux.HandleFunc("GET /api/v1/events", g.handleSSE)
	return withCORS(mux)
}

func (g *GatewayServer) handleHealth(w http.ResponseWriter, r *http.Request) {
	solverStatus := "unreachable"
	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, g.solverURL+"/health", nil)
	if err == nil {
		resp, err := g.httpClient.Do(req)
		if err == nil {
			_ = resp.Body.Close()
			if resp.StatusCode == http.StatusOK {
				solverStatus = "ok"
			}
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"status":        "ok",
		"service":       "gateway-go",
		"solver_status": solverStatus,
		"timestamp_utc": time.Now().UTC().Format(time.RFC3339),
	})
}

func (g *GatewayServer) proxyGET(path string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, g.solverURL+path, nil)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}
		resp, err := g.httpClient.Do(req)
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]string{"error": err.Error()})
			return
		}
		defer resp.Body.Close()

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(resp.StatusCode)
		_, _ = io.Copy(w, resp.Body)
	}
}

func (g *GatewayServer) proxyPOST(path string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		req, err := http.NewRequestWithContext(r.Context(), http.MethodPost, g.solverURL+path, bytes.NewReader(body))
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}
		req.Header.Set("Content-Type", "application/json")
		resp, err := g.httpClient.Do(req)
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]string{"error": err.Error()})
			return
		}
		defer resp.Body.Close()

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(resp.StatusCode)
		_, _ = io.Copy(w, resp.Body)
	}
}

func (g *GatewayServer) callSolverWithRetry(ctx context.Context, body []byte) ([]byte, int, error) {
	var lastErr error
	for attempt := 0; attempt < 2; attempt++ {
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, g.solverURL+"/solve", bytes.NewReader(body))
		if err != nil {
			return nil, attempt, err
		}
		req.Header.Set("Content-Type", "application/json")
		resp, err := g.httpClient.Do(req)
		if err != nil {
			lastErr = err
			continue
		}
		respBytes, readErr := io.ReadAll(resp.Body)
		_ = resp.Body.Close()
		if readErr != nil {
			lastErr = readErr
			continue
		}
		if resp.StatusCode >= 500 {
			lastErr = fmt.Errorf("solver returned status %d", resp.StatusCode)
			continue
		}
		if resp.StatusCode >= 400 {
			return nil, attempt, fmt.Errorf("solver rejected request (%d): %s", resp.StatusCode, string(respBytes))
		}
		return respBytes, attempt, nil
	}
	return nil, 1, lastErr
}

func (g *GatewayServer) handleSolve(w http.ResponseWriter, r *http.Request) {
	tStart := time.Now()
	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return
	}

	wfID := newWorkflowID()
	tIngestDone := time.Now()
	ingestMs := float64(tIngestDone.Sub(tStart).Microseconds()) / 1000.0

	respBytes, retries, err := g.callSolverWithRetry(r.Context(), body)
	if err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": err.Error()})
		return
	}

	var parsed struct {
		TotalSolverMs  float64          `json:"total_solver_ms"`
		StageLatencies []StageTelemetry `json:"stage_latencies"`
	}
	if err := json.Unmarshal(respBytes, &parsed); err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": "invalid solver json"})
		return
	}

	totalPipelineMs := float64(time.Since(tStart).Microseconds()) / 1000.0
	bridgeMs := totalPipelineMs - ingestMs - parsed.TotalSolverMs
	if bridgeMs < 0.2 {
		bridgeMs = 0.2
	}

	stages := make([]StageTelemetry, 0, len(parsed.StageLatencies)+2)
	stages = append(stages, StageTelemetry{
		Stage:      "Go Gateway Ingest",
		Component:  "Go 1.26 + Durable Workflow Init",
		DurationMs: round3(ingestMs),
		Status:     "DONE",
	})
	stages = append(stages, parsed.StageLatencies...)
	stages = append(stages, StageTelemetry{
		Stage:      "Durable Stream Push",
		Component:  "SSE Broker + State Checkpoint",
		DurationMs: round3(bridgeMs),
		Status:     "DONE",
	})

	run := &WorkflowRun{
		WorkflowID:      wfID,
		Status:          StatusSolved,
		CreatedAtUTC:    time.Now().UTC().Format(time.RFC3339),
		TotalPipelineMs: round3(totalPipelineMs),
		RetryCount:      retries,
		StageLatencies:  stages,
		Solution:        json.RawMessage(respBytes),
	}
	g.store.SaveSolved(run)

	writeJSON(w, http.StatusOK, run)
}

func (g *GatewayServer) handleListWorkflows(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"workflows": g.store.ListRecent(20),
	})
}

func (g *GatewayServer) handleApprove(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if id == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "missing workflow id"})
		return
	}
	var reqBody struct {
		Operator string `json:"operator"`
	}
	_ = json.NewDecoder(io.LimitReader(r.Body, 4096)).Decode(&reqBody)
	if reqBody.Operator == "" {
		reqBody.Operator = "UAE-GCC Corridor Dispatcher"
	}

	wf, err := g.store.ApproveAndDispatch(id, reqBody.Operator)
	if err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, wf)
}

func (g *GatewayServer) handleSSE(w http.ResponseWriter, r *http.Request) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")

	ch := g.store.Subscribe()
	defer g.store.Unsubscribe(ch)

	_, _ = fmt.Fprintf(w, "event: connected\ndata: {\"status\":\"listening\"}\n\n")
	flusher.Flush()

	ticker := time.NewTicker(15 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-r.Context().Done():
			return
		case msg := <-ch:
			_, _ = fmt.Fprintf(w, "event: workflow_update\ndata: %s\n\n", msg)
			flusher.Flush()
		case <-ticker.C:
			_, _ = fmt.Fprintf(w, "event: heartbeat\ndata: {\"ts\":%d}\n\n", time.Now().Unix())
			flusher.Flush()
		}
	}
}

func round3(v float64) float64 {
	return float64(int(v*1000+0.5)) / 1000.0
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	solverURL := os.Getenv("SOLVER_URL")
	if solverURL == "" {
		solverURL = "http://127.0.0.1:8001"
	}

	srv := NewGatewayServer(solverURL)
	log.Printf("gateway-go listening on :%s (solver: %s)", port, solverURL)
	if err := http.ListenAndServe(":"+port, srv.Routes()); err != nil {
		log.Fatal(err)
	}
}
