# Contributing & SWE Standards

This repository implements a tri-lingual, high-reliability Neuro-Symbolic Supply Chain Optimization platform targeting UAE–Oman–India–Europe multi-modal trade corridors.

## 1. Engineering Principles
- **Determinism & Formal Safety**: All customs, tariff (UAE-India CEPA), and pharmaceutical GDP cold-chain constraints must be encoded as verifiable SMT assertions in Z3 before entering the MILP feasible set.
- **Explicit Schemas at Service Boundaries**: Every JSON payload crossing between `apps/command-center`, `services/gateway-go`, and `services/solver-py` must strictly conform to typed structs (Go), Pydantic v2 models (Python), and TypeScript interfaces (Frontend).
- **Sub-400ms Execution Budget**: Avoid synchronous blocking I/O in hot paths, pre-compute static corridor topology graphs, and measure stage latencies on every `/solve` call.

## 2. Language-Specific Standards

### Python (`services/solver-py`)
- **Runtime**: Python 3.12 managed via `uv` (`.venv`).
- **Validation**: Pydantic v2 `BaseModel` with explicit field bounds and type annotations on all public functions.
- **Optimization**: `scipy.optimize.milp` (HiGHS backend) and `z3-solver`. Always assert `res.success` and record optimality gap (`mip_gap`).
- **Testing**: `pytest` covering baseline optimality, Hormuz/Jebel Ali disruption rerouting, Z3 `UNSAT` rejection of unbonded/thermal-breaching routes, and latency budgets.

### Go (`services/gateway-go`)
- **Runtime**: Go 1.26 standard library `net/http` (`ServeMux` method routing) + concurrency-safe `sync.RWMutex` durable workflow store.
- **State Machine**: Workflows transition strictly through `PENDING -> SOLVED -> APPROVED -> DISPATCHED_BONDED_CORRIDOR` (or `FAILED`).
- **Testing**: `go vet ./...` and `go test -race -v ./...`.

### Frontend (`apps/command-center`)
- **Stack**: React 19, TypeScript (`strict: true`), Vite, Deck.gl + MapLibre GL.
- **Web Standards**: Semantic HTML (`<table>`, `<dialog>`, `<input type="range">`), CSS `color-scheme: light dark`, container-query responsive tables (`@container`), and zero `any` escape hatches.

## 3. Local Development Commands
```bash
make setup   # Install Python, Go, and Node dependencies
make test    # Run pytest, go test -race, and frontend tsc/vite build
make dev     # Launch solver-py (:8001), gateway-go (:8080), and command-center (:5173)
```
