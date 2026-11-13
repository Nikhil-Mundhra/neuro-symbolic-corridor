.PHONY: setup lint test test-py test-py-property test-contracts test-sla test-go test-ui build-ui test-e2e ci dev clean

setup:
	cd services/solver-py && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"
	cd services/gateway-go && go mod tidy
	cd apps/command-center && npm install

# Stage 1: Static Analysis, Formatting & Type-Safety Guardrails
lint:
	cd services/solver-py && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd services/gateway-go && test -z "$$(gofmt -l .)" && go vet ./...
	cd apps/command-center && npx tsc --noEmit

# Stage 2: Service-Level Unit, Property, Coverage & Bundle Guardrails
test: test-py test-go test-ui build-ui

test-py:
	cd services/solver-py && .venv/bin/pytest -v --cov=app --cov-report=term-missing --cov-fail-under=95

test-py-property:
	cd services/solver-py && .venv/bin/pytest -v -m property

test-contracts:
	cd services/solver-py && .venv/bin/pytest -v -m contract

test-sla:
	cd services/solver-py && .venv/bin/pytest -v -m sla

test-go:
	cd services/gateway-go && go vet ./... && go test -race -v ./...

test-ui:
	cd apps/command-center && npm test

build-ui:
	cd apps/command-center && npm run build

# Stage 3: Live Cross-Service E2E Contract & <400ms P99 SLA Benchmark Gate
test-e2e:
	@echo "Running Live Cross-Service E2E Contract & <400ms P99 SLA Gate..."
	@(cd services/solver-py && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 18001 >/dev/null 2>&1) & \
	SOLVER_PID=$$!; \
	trap "kill $$SOLVER_PID 2>/dev/null || true" EXIT INT TERM; \
	for i in $$(seq 1 30); do \
		if curl -sf http://127.0.0.1:18001/health >/dev/null; then break; fi; \
		sleep 0.2; \
	done; \
	cd services/gateway-go && LIVE_SOLVER_URL=http://127.0.0.1:18001 go test -count=1 -race -v -run TestLiveSolverEndToEndContractAndSLAGate ./...

# Full Local & CI Verification Pipeline
ci: lint test test-e2e

dev:
	@echo "Starting Neuro-Symbolic Corridor stack..."
	@(trap 'kill 0' SIGINT SIGTERM; \
		(cd services/solver-py && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001) & \
		(cd services/gateway-go && SOLVER_URL=http://127.0.0.1:8001 PORT=8080 go run .) & \
		(cd apps/command-center && npm run dev -- --port 5173) & \
		wait)

clean:
	rm -rf apps/command-center/dist services/solver-py/.pytest_cache services/solver-py/.coverage services/solver-py/__pycache__ services/gateway-go/coverage.out
