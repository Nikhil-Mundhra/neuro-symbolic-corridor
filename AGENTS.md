# AGENTS.md — Neuro-Symbolic Corridor Solver Engineering Rules

## Core Architecture Invariants
1. **Zero Regulatory Hallucination Invariant**: Unstructured document parsers or LLMs may only extract typed fields into strict Pydantic/JSON schemas. No route may be marked feasible or dispatched without passing formal verification in `services/solver-py/app/z3_compiler.py` (`z3.sat`).
2. **Latency SLA (<400ms P99 End-to-End)**:
   - Stage 1 (Go Gateway & Stream Ingest): `< 10 ms`
   - Stage 2 (Guided BoL Schema Extraction): `< 25 ms`
   - Stage 3 (T-GNN Warm-Start Variable Pruning): `< 30 ms`
   - Stage 4 (Z3 SMT Formal Check + HiGHS MILP Optimization): `< 200 ms`
   - Stage 5 (Customs Payload Generation & SSE Push): `< 50 ms`
3. **Decoupled Service Boundaries**:
   - `services/gateway-go` owns high-concurrency ingestion, durable workflow state transitions, and SSE streaming.
   - `services/solver-py` owns neural/guided extraction, T-GNN warm-start pruning, Z3 SMT regulatory verification, HiGHS MILP solving, and customs payload generation.
   - `apps/command-center` owns visualization (Deck.gl WebGL + tactical schematic radar) and dispatcher human-in-the-loop approval.

## Browser Support & Modern Web Policy
- **Browser Support:** Baseline Newly Available features (`light-dark()`, `accent-color`, `<dialog closedby>`, `scrollbar-color`) are used with progressive enhancement fallbacks (`prefers-color-scheme`, `@supports not (accent-color: ...)`, bounding-rect pointer light-dismiss) so Safari, Firefox, and Chromium behave consistently.
- Never replace native `<dialog>` semantics with custom `role="dialog"` overlays.

## Verification Gates
Before any commit or PR:
- Python solver tests: `cd services/solver-py && .venv/bin/pytest -v`
- Go gateway race-checked tests & vet: `cd services/gateway-go && go vet ./... && go test -race -v ./...`
- Frontend strict typecheck & bundle: `cd apps/command-center && npm run build`

## CLI Tooling & Diagramming
- **mermaid-ascii** (`https://github.com/AlexanderGrooff/mermaid-ascii`): A CLI tool that renders Mermaid markdown (`graph`/`flowchart`, `sequenceDiagram`, `erDiagram`) into plaintext ASCII/Unicode diagrams.
- **Agent Value**: Enables LLMs to visually inspect, self-correct, and share structural layouts directly in text-based context blocks or terminal logs without relying on external image renderers.
- **Usage**: Pipeline Mermaid text directly into stdin (`cat diagram.mermaid | mermaid-ascii` or `printf 'graph LR\nA --> B\n' | mermaid-ascii`) or pass a file (`mermaid-ascii -f diagram.mermaid`, optional flags `-a` for pure ASCII, `-x`/`-y` for node spacing, `-p` for box padding, `--max-width <cols>`).
