"""Monte Carlo disruption & Z3+MILP oracle dataset generator for T-GNN training."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.graph_features import build_graph_tensors
from app.milp_solver import NoFeasibleRouteError, solve_corridor
from app.models import DisruptionState, ShipmentSpec
from app.network import CANDIDATE_ROUTES, CORRIDOR_EDGES

CARGO_PROFILES: tuple[str, ...] = (
    "pharma_cold_chain",
    "ev_automotive_jit",
    "industrial_bulk",
)


@dataclass(frozen=True)
class CorridorOracleSample:
    """Single labeled corridor graph snapshot produced by the Z3 + HiGHS MILP oracle."""

    profile: str
    shipment: ShipmentSpec
    disruption: DisruptionState
    pareto_alpha: float
    optimal_route_id: str | None
    optimal_edge_ids: tuple[str, ...]
    route_sat_status: dict[str, str]
    node_features: np.ndarray
    edge_index: np.ndarray
    edge_features: np.ndarray
    delay_features: np.ndarray
    edge_sat_feasible: np.ndarray
    edge_optimal_labels: np.ndarray
    edge_prune_labels: np.ndarray


@dataclass(frozen=True)
class DatasetSplits:
    """Train, validation, and test splits of Monte Carlo oracle graph samples."""

    train: list[CorridorOracleSample]
    val: list[CorridorOracleSample]
    test: list[CorridorOracleSample]
    metadata: dict[str, Any]


def _sample_shipment(rng: np.random.Generator, profile: str, idx: int) -> ShipmentSpec:
    if profile == "pharma_cold_chain":
        hs_code = str(rng.choice(["3002.15.00", "3004.31.00"]))
        initial_temp = float(rng.uniform(2.0, 4.5))
        max_temp = float(rng.uniform(7.5, 8.5))
        teu_count = int(rng.integers(1, 13))
        cargo_value = float(rng.uniform(650_000.0, 4_500_000.0))
        max_transit = float(rng.uniform(115.0, 260.0))
        demurrage = float(rng.uniform(220.0, 450.0))
        spoilage = float(rng.uniform(80.0, 100.0))
        vot = float(rng.uniform(240.0, 650.0))
        is_temp_sensitive = True
        desc = "Monoclonal Antibody Biologics (2C-8C GDP)"
    elif profile == "ev_automotive_jit":
        hs_code = str(rng.choice(["8708.40.00", "8708.99.00"]))
        initial_temp = float(rng.uniform(18.0, 28.0))
        max_temp = float(rng.uniform(42.0, 50.0))
        teu_count = int(rng.integers(4, 25))
        cargo_value = float(rng.uniform(350_000.0, 2_000_000.0))
        max_transit = float(rng.uniform(140.0, 520.0))
        demurrage = float(rng.uniform(180.0, 340.0))
        spoilage = float(rng.uniform(0.0, 15.0))
        vot = float(rng.uniform(110.0, 340.0))
        is_temp_sensitive = False
        desc = "Precision EV Reduction Gearboxes (JIT Assembly)"
    else:
        hs_code = str(rng.choice(["3902.10.00", "8481.80.00"]))
        initial_temp = float(rng.uniform(20.0, 30.0))
        max_temp = float(rng.uniform(48.0, 60.0))
        teu_count = int(rng.integers(10, 61))
        cargo_value = float(rng.uniform(150_000.0, 950_000.0))
        max_transit = float(rng.uniform(360.0, 650.0))
        demurrage = float(rng.uniform(120.0, 260.0))
        spoilage = 0.0
        vot = float(rng.uniform(25.0, 120.0))
        is_temp_sensitive = False
        desc = "High-Density Polypropylene Resins (Containerized Bulk)"

    # Mix CEPA-compliant (>=40%) and boundary/non-compliant (<40%) shipments
    cepa_pct = (
        float(rng.uniform(40.5, 68.0)) if rng.random() < 0.85 else float(rng.uniform(20.0, 39.5))
    )

    return ShipmentSpec(
        bol_number=f"BOL-MC-{idx:05d}",
        shipper="Synthetic India Origin Exporter Pvt Ltd",
        consignee="Synthetic EU Consignee Logistics GmbH",
        cargo_description=desc,
        hs_code=hs_code,
        origin_node="INNSA",
        destination_node="EUFRA",
        teu_count=teu_count,
        cargo_value_usd=round(cargo_value, 2),
        cepa_value_add_pct=round(cepa_pct, 2),
        is_temp_sensitive=is_temp_sensitive,
        initial_temp_c=round(initial_temp, 2),
        max_temp_c=round(max_temp, 2),
        max_transit_hours=round(max_transit, 2),
        demurrage_usd_per_teu_day=round(demurrage, 2),
        spoilage_risk_pct_on_breach=round(spoilage, 2),
        value_of_time_usd_per_hour=round(vot, 2),
    )


def _sample_disruption(rng: np.random.Generator) -> DisruptionState:
    regime = rng.random()
    if regime < 0.18:
        # Nominal / low-disruption regime
        hormuz = 0.0
        jebel = 0.0
        red_sea = float(rng.uniform(0.0, 350.0))
        reefer_fault = False
        drift = 0.0
    elif regime < 0.55:
        # Moderate disruption
        hormuz = float(rng.uniform(12.0, 72.0))
        jebel = float(rng.uniform(6.0, 42.0))
        red_sea = float(rng.uniform(400.0, 2600.0))
        reefer_fault = bool(rng.random() < 0.45)
        drift = float(rng.uniform(0.015, 0.045)) if reefer_fault else 0.0
    else:
        # Severe disruption
        hormuz = float(rng.uniform(60.0, 180.0))
        jebel = float(rng.uniform(24.0, 110.0))
        red_sea = float(rng.uniform(1400.0, 6000.0))
        reefer_fault = bool(rng.random() < 0.78)
        drift = float(rng.uniform(0.025, 0.09)) if reefer_fault else 0.0

    return DisruptionState(
        hormuz_delay_hours=round(hormuz, 2),
        jebel_ali_congestion_hours=round(jebel, 2),
        red_sea_surcharge_usd=round(red_sea, 2),
        reefer_fault=reefer_fault,
        reefer_ambient_drift_c_per_hour=round(drift, 4),
        require_cepa_zero_tariff=bool(rng.random() < 0.85),
    )


def sample_scenario(
    rng: np.random.Generator,
    profile: str,
    idx: int,
) -> tuple[ShipmentSpec, DisruptionState, float]:
    """Sample a single realistic (ShipmentSpec, DisruptionState, pareto_alpha) scenario."""
    shipment = _sample_shipment(rng, profile, idx)
    disruption = _sample_disruption(rng)
    pareto_alpha = round(float(rng.uniform(0.1, 0.95)), 3)
    return shipment, disruption, pareto_alpha


def label_sample_with_oracle(
    shipment: ShipmentSpec,
    disruption: DisruptionState,
    pareto_alpha: float,
    profile: str,
) -> CorridorOracleSample:
    """Invoke the Z3 SMT + HiGHS MILP oracle to produce ground-truth edge labels."""
    num_edges = len(CORRIDOR_EDGES)
    edge_id_to_idx = {edge.id: idx for idx, edge in enumerate(CORRIDOR_EDGES)}

    edge_sat_feasible = np.zeros(num_edges, dtype=np.float32)
    edge_optimal_labels = np.zeros(num_edges, dtype=np.float32)

    try:
        candidates, _, optimal_route, _, _, _ = solve_corridor(shipment, disruption, pareto_alpha)
        optimal_route_id: str | None = optimal_route.route_id
        optimal_edge_ids = tuple(optimal_route.edge_ids)
        route_sat_status = {cand.route_id: cand.z3_status for cand in candidates}

        for cand in candidates:
            if cand.z3_status == "SAT":
                for eid in cand.edge_ids:
                    edge_sat_feasible[edge_id_to_idx[eid]] = 1.0

        for eid in optimal_edge_ids:
            edge_optimal_labels[edge_id_to_idx[eid]] = 1.0
    except NoFeasibleRouteError:
        optimal_route_id = None
        optimal_edge_ids = ()
        route_sat_status = {str(r["route_id"]): "UNSAT" for r in CANDIDATE_ROUTES}

    edge_prune_labels = (1.0 - edge_optimal_labels).astype(np.float32)
    node_features, edge_index, edge_features, delay_features = build_graph_tensors(
        CORRIDOR_EDGES, disruption, shipment
    )

    return CorridorOracleSample(
        profile=profile,
        shipment=shipment,
        disruption=disruption,
        pareto_alpha=pareto_alpha,
        optimal_route_id=optimal_route_id,
        optimal_edge_ids=optimal_edge_ids,
        route_sat_status=route_sat_status,
        node_features=node_features,
        edge_index=edge_index,
        edge_features=edge_features,
        delay_features=delay_features,
        edge_sat_feasible=edge_sat_feasible,
        edge_optimal_labels=edge_optimal_labels,
        edge_prune_labels=edge_prune_labels,
    )


def generate_monte_carlo_dataset(
    num_samples: int = 900,
    seed: int = 42,
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
) -> DatasetSplits:
    """Generate stratified Monte Carlo samples labeled by the Z3 + HiGHS MILP oracle."""
    if num_samples < 6:
        raise ValueError("num_samples must be at least 6 to construct non-empty splits.")
    if train_ratio <= 0.0 or val_ratio <= 0.0 or train_ratio + val_ratio >= 1.0:
        raise ValueError("train_ratio and val_ratio must be positive and sum to < 1.0.")

    rng = np.random.default_rng(seed)
    samples: list[CorridorOracleSample] = []
    for idx in range(num_samples):
        profile = CARGO_PROFILES[idx % len(CARGO_PROFILES)]
        shipment, disruption, alpha = sample_scenario(rng, profile, idx)
        samples.append(label_sample_with_oracle(shipment, disruption, alpha, profile))

    perm = rng.permutation(num_samples)
    train_end = max(1, int(round(num_samples * train_ratio)))
    val_end = min(num_samples - 1, train_end + max(1, int(round(num_samples * val_ratio))))

    train = [samples[int(i)] for i in perm[:train_end]]
    val = [samples[int(i)] for i in perm[train_end:val_end]]
    test = [samples[int(i)] for i in perm[val_end:]]

    feasible_count = sum(1 for s in samples if s.optimal_route_id is not None)
    metadata: dict[str, Any] = {
        "num_samples": num_samples,
        "seed": seed,
        "train_count": len(train),
        "val_count": len(val),
        "test_count": len(test),
        "feasible_samples": feasible_count,
        "all_unsat_samples": num_samples - feasible_count,
        "profiles": list(CARGO_PROFILES),
        "num_nodes": int(samples[0].node_features.shape[0]),
        "num_edges": int(samples[0].edge_features.shape[0]),
    }
    return DatasetSplits(train=train, val=val, test=test, metadata=metadata)


def _stack_split(samples: list[CorridorOracleSample]) -> dict[str, np.ndarray]:
    return {
        "node_features": np.stack([s.node_features for s in samples], axis=0),
        "edge_index": samples[0].edge_index,
        "edge_features": np.stack([s.edge_features for s in samples], axis=0),
        "delay_features": np.stack([s.delay_features for s in samples], axis=0),
        "edge_sat_feasible": np.stack([s.edge_sat_feasible for s in samples], axis=0),
        "edge_optimal_labels": np.stack([s.edge_optimal_labels for s in samples], axis=0),
        "edge_prune_labels": np.stack([s.edge_prune_labels for s in samples], axis=0),
    }


def save_dataset_splits(splits: DatasetSplits, output_dir: Path) -> tuple[Path, Path]:
    """Persist dataset split tensors as compressed NPZ plus JSON metadata."""
    output_dir.mkdir(parents=True, exist_ok=True)
    npz_path = output_dir / "corridor_oracle_dataset.npz"
    meta_path = output_dir / "corridor_oracle_dataset.meta.json"

    arrays: dict[str, np.ndarray] = {}
    for split_name, split_samples in (
        ("train", splits.train),
        ("val", splits.val),
        ("test", splits.test),
    ):
        for key, arr in _stack_split(split_samples).items():
            arrays[f"{split_name}_{key}"] = arr

    np.savez_compressed(npz_path, **arrays)
    meta_path.write_text(json.dumps(splits.metadata, indent=2), encoding="utf-8")
    return npz_path, meta_path
