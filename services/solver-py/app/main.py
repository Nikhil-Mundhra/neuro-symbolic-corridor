"""FastAPI entrypoint for the Python Neuro-Symbolic Corridor Solver."""

from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.customs_payloads import build_customs_payloads
from app.gnn_warmstart import compute_gnn_warmstart
from app.milp_solver import NoFeasibleRouteError, solve_corridor
from app.models import (
    CorridorTopology,
    ParseBoLRequest,
    ParseBoLResponse,
    ScenarioPreset,
    SolveRequest,
    SolveResponse,
    StageLatency,
)
from app.network import CORRIDOR_EDGES, get_topology
from app.parser import get_scenarios, parse_bol_text

app = FastAPI(
    title="Neuro-Symbolic Corridor Solver (Python Z3 + HiGHS Core)",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "engine": "z3-smt + scipy-highs-milp"}


@app.get("/topology", response_model=CorridorTopology)
def topology() -> CorridorTopology:
    return get_topology()


@app.get("/scenarios", response_model=list[ScenarioPreset])
def scenarios() -> list[ScenarioPreset]:
    return get_scenarios()


@app.post("/parse-bol", response_model=ParseBoLResponse)
def parse_bol(req: ParseBoLRequest) -> ParseBoLResponse:
    return parse_bol_text(req.raw_text)


@app.post("/solve", response_model=SolveResponse)
def solve(req: SolveRequest) -> SolveResponse:
    t0 = time.perf_counter()
    solve_id = str(uuid.uuid4())[:12]

    # Stage: T-GNN warm-start scoring & pruning
    t_gnn_start = time.perf_counter()
    gnn_metrics = compute_gnn_warmstart(CORRIDOR_EDGES, req.disruption, req.shipment)
    gnn_ms = round((time.perf_counter() - t_gnn_start) * 1000.0, 3)

    # Stage: Z3 SMT Verification + HiGHS MILP Optimization
    t_math_start = time.perf_counter()
    try:
        (
            candidates,
            certificates,
            optimal_route,
            pareto_frontier,
            unit_economics,
            mip_gap,
        ) = solve_corridor(req.shipment, req.disruption, req.pareto_alpha)
    except NoFeasibleRouteError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    math_ms = round((time.perf_counter() - t_math_start) * 1000.0, 3)

    # Stage: Customs & Spot Booking JSON Payload Compilation
    t_cust_start = time.perf_counter()
    opt_cert = next(c for c in certificates if c.route_id == optimal_route.route_id)
    customs_payloads = build_customs_payloads(solve_id, req.shipment, optimal_route, opt_cert)
    cust_ms = round((time.perf_counter() - t_cust_start) * 1000.0, 3)

    total_ms = round((time.perf_counter() - t0) * 1000.0, 3)

    stages = [
        StageLatency(
            stage="T-GNN Warm-Start",
            component="PyG / ONNX Variable Pruner",
            duration_ms=gnn_ms,
            status="DONE",
        ),
        StageLatency(
            stage="Z3 SMT + HiGHS MILP",
            component="Formal Regulatory + MILP Core",
            duration_ms=math_ms,
            status="DONE",
        ),
        StageLatency(
            stage="Customs Bridge",
            component="Dubai Trade / Maqta / Bayan JSON",
            duration_ms=cust_ms,
            status="DONE",
        ),
    ]

    return SolveResponse(
        solve_id=solve_id,
        solver_engine="SciPy-HiGHS MILP + Z3 4.13 SMT",
        optimality_gap_pct=mip_gap,
        total_solver_ms=total_ms,
        optimal_route=optimal_route,
        candidates=candidates,
        z3_certificates=certificates,
        gnn_warmstart=gnn_metrics,
        pareto_frontier=pareto_frontier,
        unit_economics=unit_economics,
        stage_latencies=stages,
        customs_payloads=customs_payloads,
    )
