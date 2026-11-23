# ParetoLane

**The Autonomous Cargo Rerouting & Customs Engine** — *Autonomous, Formally Verified Neuro-Symbolic Multi-Modal Rerouting & Customs Compliance for the UAE–Oman–India–Europe Corridor.*

Built for the **Nov 17 BTI Startup Expo**, **Dec 11 NYUADEIP Priority Deadline**, and the **2027 startAD / Hub71** roadmap.

## Executive Summary

### The Problem
Every year, billions of dollars in trade moving between **India, the UAE, Oman, and Europe** are delayed by maritime choke points in the Strait of Hormuz and Red Sea, port berth congestion, and cold-chain failures. When a ship is delayed or a refrigerated container malfunctions, freight forwarders lose **\$150–\$300 per container per day** in port demurrage fees—or risk losing **100% of high-value pharmaceutical cargo** to spoilage. Existing logistics software only *shows* that a shipment is late; it cannot automatically re-route cargo across sea, land, and air while guaranteeing customs compliance.

### Our Solution
**ParetoLane** (powered by our **Neuro-Symbolic Corridor Solver**) is an autonomous decision and customs-execution engine for GCC freight forwarders, ports, and air cargo carriers:
- **Instant Multi-Modal Rerouting:** When a disruption hits (e.g., a 72-hour delay at the Strait of Hormuz), our engine shifts cargo in real time—for example, offloading at **Fujairah** or **Oman (Sohar/Salalah)** onto **Oman–UAE Sealed-Truck "Green Corridor"** lanes or **Etihad Rail**, and connecting to **Etihad Cargo** at Zayed International Airport.
- **Zero Customs Mistakes:** Unlike generic AI chatbots that can invent tariff rules, every route is mathematically checked against **GCC Unified Customs Law**, **UAE–India CEPA (0% duty) rules of origin**, and **2°C–8°C pharmaceutical cold-chain limits** before it is ever shown to a dispatcher.
- **1-Click Execution:** Dispatchers see the exact dollar and dirham savings side-by-side and approve the reroute in one click, automatically generating ready-to-submit customs and booking payloads for **Dubai Trade**, **Maqta Gateway**, **Oman Bayan**, and **Etihad Cargo**.

### Business Model
We pair a base platform license with an **Autonomous Clearinghouse take-rate (10–15%)** on every dirham of port demurrage, detention, and cold-chain spoilage our engine mathematically prevents.

## Why Neuro-Symbolic?
Standard logistics dashboards only report delays after containers miss berths. Pure LLM wrappers hallucinate Harmonized System (HS) tariff codes and UAE–India CEPA rules of origin. Traditional MILP solvers choke when graph nodes scale across thousands of containers.

Our 3-layer architecture solves all three:
1. **Neural Perception & T-GNN Warm-Start (`services/solver-py`)**: Parses unstructured Bills of Lading into strict Pydantic schemas and uses Temporal Graph Neural Network edge scoring to prune dominated binary routing variables before branch-and-bound.
2. **Symbolic Solver Core (`Z3 SMT + HiGHS MILP`)**: Formally **proves** compliance with GCC Unified Customs Law, Oman–UAE Sealed-Truck **"Green Corridor"** transit bonds, UAE–India CEPA rules of origin, and GDP pharmaceutical cold-chain SLAs (`2°C–8°C`), then solves the exact Pareto-optimal multi-modal reroute (Sea → Fujairah/Sohar → Bonded Rail/Truck → Khalifa Port / Etihad Cargo Air Bridge) in **< 400ms**.
3. **Durable Execution Bridge (`services/gateway-go`) & WebGL Digital Twin (`apps/command-center`)**: Go high-concurrency workflow engine streaming live solutions via SSE to a 60 FPS Deck.gl WebGL command center with 1-click dispatcher approval and auto-generated **Dubai Trade**, **Maqta Gateway**, **Oman Bayan Green Corridor**, and **Etihad Cargo** JSON payloads.

### Abstract System Flow

```text
┌────────────────┐ ┌────────────┐ ┌──────────────────┐ ┌─────────────────┐ ┌────────────┐ ┌────────────────┐
│ Command Center ├►│ Go Gateway ├►│ Neural BoL+T-GNN ├►│ Z3 SMT Verifier ├►│ HiGHS MILP ├►│ Customs Bridge │
└────────────────┘ └────────────┘ └──────────────────┘ └─────────────────┘ └────────────┘ └────────────────┘
```

See [System Architecture & Mathematical Formulation](docs/ARCHITECTURE.md) for the full `<400ms` sequence diagram and multimodal Gulf Corridor topology.

## Quickstart

### 1. Setup All Services
```bash
make setup
```

### 2. Run Full Verification Suite
```bash
make test
```

### 3. Run Locally (Three-Service Stack)
```bash
make dev
```
- **Command Center UI**: `http://localhost:5173`
- **Go Gateway API**: `http://localhost:8080/health`
- **Python Neuro-Symbolic Solver**: `http://localhost:8001/health`

Or launch via Docker Compose:
```bash
docker compose up --build
```

## Documentation
- [System Architecture & Mathematical Formulation](docs/ARCHITECTURE.md)
- [Testing & CI/CD Guardrails](docs/TESTING_AND_CICD.md)
- [Phased Product Roadmap (Nov 2026 – Q4 2027)](docs/ROADMAP.md)
- [SWE Standards & Contributing](CONTRIBUTING.md)
- [Agent & Verification Rules](AGENTS.md)
