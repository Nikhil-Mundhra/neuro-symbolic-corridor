.PHONY: setup test test-py test-go test-ui build-ui dev clean

setup:
	cd services/solver-py && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"
	cd services/gateway-go && go mod tidy
	cd apps/command-center && npm install

test: test-py test-go build-ui

test-py:
	cd services/solver-py && .venv/bin/pytest -v

test-go:
	cd services/gateway-go && go vet ./... && go test -race -v ./...

build-ui:
	cd apps/command-center && npm run build

dev:
	@echo "Starting Neuro-Symbolic Corridor stack..."
	@(trap 'kill 0' SIGINT SIGTERM; \
		(cd services/solver-py && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001) & \
		(cd services/gateway-go && SOLVER_URL=http://127.0.0.1:8001 PORT=8080 go run .) & \
		(cd apps/command-center && npm run dev -- --port 5173) & \
		wait)

clean:
	rm -rf apps/command-center/dist services/solver-py/.pytest_cache services/solver-py/__pycache__
