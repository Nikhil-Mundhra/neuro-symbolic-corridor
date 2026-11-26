package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// PersistenceStore defines durable checkpointing for workflows and live telemetry.
type PersistenceStore interface {
	InitSchema(ctx context.Context) error
	LoadRecentWorkflows(ctx context.Context, limit int) ([]*WorkflowRun, error)
	UpsertWorkflow(ctx context.Context, run *WorkflowRun) error
	LoadTelemetrySnapshot(ctx context.Context) (*TelemetrySnapshot, error)
	SaveTelemetrySnapshot(ctx context.Context, snap TelemetrySnapshot) error
	Close()
}

// PostgresStore persists WorkflowRun and TelemetrySnapshot state in PostgreSQL JSONB tables.
type PostgresStore struct {
	pool *pgxpool.Pool
}

// NewPostgresStore connects to PostgreSQL using pgxpool with bounded startup timeout.
func NewPostgresStore(ctx context.Context, databaseURL string) (*PostgresStore, error) {
	cfg, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		return nil, fmt.Errorf("parse database url: %w", err)
	}
	cfg.MaxConns = 10
	cfg.MinConns = 1
	cfg.MaxConnIdleTime = 5 * time.Minute

	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("create pgx pool: %w", err)
	}

	pingCtx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	if err := pool.Ping(pingCtx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("ping postgres: %w", err)
	}
	return &PostgresStore{pool: pool}, nil
}

func (p *PostgresStore) InitSchema(ctx context.Context) error {
	queryCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()

	const ddl = `
CREATE TABLE IF NOT EXISTS workflow_runs (
	workflow_id TEXT PRIMARY KEY,
	status TEXT NOT NULL,
	created_at_utc TIMESTAMPTZ NOT NULL,
	payload JSONB NOT NULL,
	updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_created_at
	ON workflow_runs (created_at_utc DESC);

CREATE TABLE IF NOT EXISTS telemetry_snapshots (
	id SMALLINT PRIMARY KEY CHECK (id = 1),
	payload JSONB NOT NULL,
	updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
`
	_, err := p.pool.Exec(queryCtx, ddl)
	if err != nil {
		return fmt.Errorf("init postgres schema: %w", err)
	}
	return nil
}

func (p *PostgresStore) LoadRecentWorkflows(ctx context.Context, limit int) ([]*WorkflowRun, error) {
	if limit <= 0 {
		limit = 100
	}
	queryCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()

	rows, err := p.pool.Query(
		queryCtx,
		`SELECT payload FROM workflow_runs ORDER BY created_at_utc ASC LIMIT $1`,
		limit,
	)
	if err != nil {
		return nil, fmt.Errorf("load recent workflows: %w", err)
	}
	defer rows.Close()

	var runs []*WorkflowRun
	for rows.Next() {
		var raw []byte
		if err := rows.Scan(&raw); err != nil {
			return nil, fmt.Errorf("scan workflow payload: %w", err)
		}
		var run WorkflowRun
		if err := json.Unmarshal(raw, &run); err != nil {
			return nil, fmt.Errorf("unmarshal workflow payload: %w", err)
		}
		runs = append(runs, &run)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate workflow rows: %w", err)
	}
	return runs, nil
}

func (p *PostgresStore) UpsertWorkflow(ctx context.Context, run *WorkflowRun) error {
	payload, err := json.Marshal(run)
	if err != nil {
		return fmt.Errorf("marshal workflow: %w", err)
	}
	createdAt, err := time.Parse(time.RFC3339, run.CreatedAtUTC)
	if err != nil {
		createdAt = time.Now().UTC()
	}

	queryCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()

	_, err = p.pool.Exec(
		queryCtx,
		`INSERT INTO workflow_runs (workflow_id, status, created_at_utc, payload, updated_at)
		 VALUES ($1, $2, $3, $4::jsonb, NOW())
		 ON CONFLICT (workflow_id) DO UPDATE
		 SET status = EXCLUDED.status,
		     payload = EXCLUDED.payload,
		     updated_at = NOW()`,
		run.WorkflowID,
		string(run.Status),
		createdAt,
		payload,
	)
	if err != nil {
		return fmt.Errorf("upsert workflow %s: %w", run.WorkflowID, err)
	}
	return nil
}

func (p *PostgresStore) LoadTelemetrySnapshot(ctx context.Context) (*TelemetrySnapshot, error) {
	queryCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()

	var raw []byte
	err := p.pool.QueryRow(queryCtx, `SELECT payload FROM telemetry_snapshots WHERE id = 1`).Scan(&raw)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, fmt.Errorf("load telemetry snapshot: %w", err)
	}
	var snap TelemetrySnapshot
	if err := json.Unmarshal(raw, &snap); err != nil {
		return nil, fmt.Errorf("unmarshal telemetry snapshot: %w", err)
	}
	if snap.EdgeOverrides == nil {
		snap.EdgeOverrides = make(map[string]EdgeTelemetryOverride)
	}
	if snap.ActiveSources == nil {
		snap.ActiveSources = []string{}
	}
	return &snap, nil
}

func (p *PostgresStore) SaveTelemetrySnapshot(ctx context.Context, snap TelemetrySnapshot) error {
	payload, err := json.Marshal(snap)
	if err != nil {
		return fmt.Errorf("marshal telemetry snapshot: %w", err)
	}

	queryCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()

	_, err = p.pool.Exec(
		queryCtx,
		`INSERT INTO telemetry_snapshots (id, payload, updated_at)
		 VALUES (1, $1::jsonb, NOW())
		 ON CONFLICT (id) DO UPDATE
		 SET payload = EXCLUDED.payload,
		     updated_at = NOW()`,
		payload,
	)
	if err != nil {
		return fmt.Errorf("save telemetry snapshot: %w", err)
	}
	return nil
}

func (p *PostgresStore) Close() {
	if p != nil && p.pool != nil {
		p.pool.Close()
	}
}
