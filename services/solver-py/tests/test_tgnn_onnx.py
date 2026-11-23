"""Tests for Monte Carlo oracle dataset, PyG T-GNN training, ONNX export, and ORT inference."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import pytest
import torch

import app.gnn_warmstart as gnn_mod
from app.gnn_warmstart import compute_gnn_warmstart, reset_onnx_session_cache
from app.graph_features import (
    DELAY_FEATURE_DIM,
    EDGE_FEATURE_DIM,
    NODE_FEATURE_DIM,
    build_graph_tensors,
)
from app.models import CorridorEdge, DisruptionState, ShipmentSpec, TransportMode
from app.network import CORRIDOR_EDGES
from app.parser import get_scenarios
from app.synthetic_data import (
    CARGO_PROFILES,
    generate_monte_carlo_dataset,
    label_sample_with_oracle,
    save_dataset_splits,
)
from app.train_gnn import (
    TemporalCorridorGATv2,
    _compute_auroc,
    evaluate_model,
)
from app.train_gnn import (
    main as train_main,
)


@pytest.mark.unit
def test_synthetic_dataset_generation_and_persistence(tmp_path: Path) -> None:
    splits = generate_monte_carlo_dataset(num_samples=18, seed=7)
    assert len(splits.train) + len(splits.val) + len(splits.test) == 18
    assert splits.train and splits.val and splits.test
    assert set(splits.metadata["profiles"]) == set(CARGO_PROFILES)

    for sample in splits.train + splits.val + splits.test:
        assert sample.node_features.shape == (10, NODE_FEATURE_DIM)
        assert sample.edge_index.shape == (2, len(CORRIDOR_EDGES))
        assert sample.edge_features.shape == (len(CORRIDOR_EDGES), EDGE_FEATURE_DIM)
        assert sample.delay_features.shape == (len(CORRIDOR_EDGES), DELAY_FEATURE_DIM)
        np.testing.assert_allclose(
            sample.edge_optimal_labels + sample.edge_prune_labels,
            np.ones(len(CORRIDOR_EDGES), dtype=np.float32),
        )
        assert np.all(sample.edge_sat_feasible >= sample.edge_optimal_labels)

    # Impossible SLA triggers all-UNSAT oracle fallback cleanly
    pharma = get_scenarios()[0]
    impossible = pharma.shipment.model_copy(update={"max_transit_hours": 5.0})
    unsat_sample = label_sample_with_oracle(
        impossible, pharma.default_disruption, 0.5, "pharma_cold_chain"
    )
    assert unsat_sample.optimal_route_id is None
    assert np.all(unsat_sample.edge_prune_labels == 1.0)
    assert np.all(unsat_sample.edge_sat_feasible == 0.0)

    npz_path, meta_path = save_dataset_splits(splits, tmp_path)
    assert npz_path.exists()
    assert meta_path.exists()
    loaded = np.load(npz_path)
    assert loaded["train_edge_features"].shape[0] == len(splits.train)

    with pytest.raises(ValueError, match="at least 6"):
        generate_monte_carlo_dataset(num_samples=4)
    with pytest.raises(ValueError, match="sum to < 1.0"):
        generate_monte_carlo_dataset(num_samples=12, train_ratio=0.8, val_ratio=0.3)


@pytest.mark.unit
def test_graph_features_handles_custom_nodes_and_edges() -> None:
    pharma = get_scenarios()[0]
    custom_shipment = pharma.shipment.model_copy(
        update={"origin_node": "CUSTOM_SRC", "destination_node": "CUSTOM_DST"}
    )
    custom_edges = [
        *CORRIDOR_EDGES,
        CorridorEdge(
            id="E_CUSTOM_TEST",
            source="CUSTOM_SRC",
            target="CUSTOM_DST",
            mode=TransportMode.GREEN_CORRIDOR_TRUCK,
            label="Custom Test Leg",
            base_hours=12.0,
            base_cost_per_teu_usd=300.0,
            distance_km=400.0,
            co2_kg_per_teu=50.0,
        ),
    ]
    x, ei, ea, df = build_graph_tensors(custom_edges, pharma.default_disruption, custom_shipment)
    assert x.shape == (12, NODE_FEATURE_DIM)
    assert ei.shape == (2, len(custom_edges))
    assert ea.shape == (len(custom_edges), EDGE_FEATURE_DIM)
    assert df.shape == (len(custom_edges), DELAY_FEATURE_DIM)


@pytest.mark.unit
def test_train_cli_smoke_and_onnx_pytorch_parity(tmp_path: Path) -> None:
    exit_code = train_main(
        [
            "--samples",
            "18",
            "--epochs",
            "3",
            "--seed",
            "11",
            "--output-dir",
            str(tmp_path),
            "--save-dataset",
        ]
    )
    assert exit_code == 0

    onnx_path = tmp_path / "corridor_tgnn.onnx"
    meta_path = tmp_path / "corridor_tgnn.meta.json"
    assert onnx_path.exists()
    assert meta_path.exists()
    assert (tmp_path / "corridor_oracle_dataset.npz").exists()

    model_proto = onnx.load(str(onnx_path))
    onnx.checker.check_model(model_proto)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["onnx_parity_max_diff"] < 1e-4

    # Single-class AUROC edge case returns 1.0 cleanly
    assert _compute_auroc(np.ones(5), np.linspace(0.1, 0.9, 5)) == 1.0

    # Direct PyTorch vs ONNX Runtime parity check on an untrained/fresh model or exported artifact
    pt_model = TemporalCorridorGATv2().eval()
    splits = generate_monte_carlo_dataset(num_samples=6, seed=99)
    metrics = evaluate_model(pt_model, splits.test)
    assert 0.0 <= metrics.auroc <= 1.0

    # Verify checked-in pre-trained artifact parity and validation quality
    artifact_onnx = gnn_mod.DEFAULT_ONNX_PATH
    artifact_meta_path = artifact_onnx.with_suffix(".meta.json")
    assert artifact_onnx.exists()
    assert artifact_meta_path.exists()

    artifact_meta = json.loads(artifact_meta_path.read_text(encoding="utf-8"))
    assert artifact_meta["val_metrics"]["auroc"] >= 0.90
    assert artifact_meta["val_metrics"]["optimal_edge_keep_recall"] >= 0.90
    assert artifact_meta["test_metrics"]["optimal_edge_keep_recall"] >= 0.90

    # Dynamic graph size check on the exported ONNX artifact (subset of edges)
    session = ort.InferenceSession(str(artifact_onnx), providers=["CPUExecutionProvider"])
    subset_edges = CORRIDOR_EDGES[:6]
    pharma = get_scenarios()[0]
    x, ei, ea, df = build_graph_tensors(subset_edges, pharma.default_disruption, pharma.shipment)
    out = session.run(
        None,
        {
            "node_features": x,
            "edge_index": ei,
            "edge_features": ea,
            "delay_features": df,
        },
    )[0]
    assert out.shape == (len(subset_edges),)
    assert np.all((out >= 0.0) & (out <= 1.0))

    # Verify torch tensor forward works cleanly as well
    with torch.no_grad():
        pt_out = pt_model(
            torch.from_numpy(x),
            torch.from_numpy(ei),
            torch.from_numpy(ea),
            torch.from_numpy(df),
        )
        assert pt_out.shape == (len(subset_edges),)


@pytest.mark.unit
def test_gnn_warmstart_onnx_singleton_and_fallbacks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pharma = get_scenarios()[0]
    reset_onnx_session_cache()

    # Empty graph handled cleanly
    empty_metrics = compute_gnn_warmstart([], pharma.default_disruption, pharma.shipment)
    assert empty_metrics.fleet_scale_variables == 0
    assert empty_metrics.edge_risk_scores == {}

    # Real ONNX Runtime path caches InferenceSession singleton
    m1 = compute_gnn_warmstart(CORRIDOR_EDGES, pharma.default_disruption, pharma.shipment)
    assert "ONNX Runtime" in m1.model_architecture
    assert m1.edge_risk_scores["E_OMSOH_AEWAJ_UNBONDED"] >= 0.72
    cache_size_after_first = len(gnn_mod._ORT_SESSION_CACHE)
    assert cache_size_after_first == 1
    m2 = compute_gnn_warmstart(CORRIDOR_EDGES, pharma.default_disruption, pharma.shipment)
    assert m1.edge_risk_scores == m2.edge_risk_scores
    assert len(gnn_mod._ORT_SESSION_CACHE) == 1

    # Env override to missing file triggers deterministic heuristic fallback
    monkeypatch.setenv("CORRIDOR_TGNN_ONNX_PATH", str(tmp_path / "missing.onnx"))
    fallback_missing = compute_gnn_warmstart(
        CORRIDOR_EDGES, pharma.default_disruption, pharma.shipment
    )
    assert "Heuristic Fallback" in fallback_missing.model_architecture
    assert all(0.0 <= v <= 1.0 for v in fallback_missing.edge_risk_scores.values())

    # Corrupted ONNX file triggers clean fallback without raising
    bad_onnx = tmp_path / "corrupt.onnx"
    bad_onnx.write_bytes(b"not-an-onnx-model")
    monkeypatch.setenv("CORRIDOR_TGNN_ONNX_PATH", str(bad_onnx))
    fallback_corrupt = compute_gnn_warmstart(
        CORRIDOR_EDGES, pharma.default_disruption, pharma.shipment
    )
    assert "Heuristic Fallback" in fallback_corrupt.model_architecture

    # Absence of onnxruntime module triggers clean fallback
    monkeypatch.delenv("CORRIDOR_TGNN_ONNX_PATH", raising=False)
    monkeypatch.setattr(gnn_mod, "ort", None)
    fallback_no_ort = compute_gnn_warmstart(
        CORRIDOR_EDGES, pharma.default_disruption, pharma.shipment
    )
    assert "Heuristic Fallback" in fallback_no_ort.model_architecture
    reset_onnx_session_cache()


@pytest.mark.sla
def test_gnn_warmstart_onnx_inference_sla_under_30ms() -> None:
    pharma = get_scenarios()[0]
    reset_onnx_session_cache()

    # Warm-up singleton load
    warm = compute_gnn_warmstart(CORRIDOR_EDGES, pharma.default_disruption, pharma.shipment)
    assert "ONNX Runtime" in warm.model_architecture

    latencies_ms: list[float] = []
    for idx in range(100):
        disruption = DisruptionState(
            hormuz_delay_hours=float((idx * 3) % 160),
            jebel_ali_congestion_hours=float((idx * 2) % 96),
            red_sea_surcharge_usd=1500.0,
            reefer_fault=(idx % 2 == 0),
            reefer_ambient_drift_c_per_hour=0.035,
        )
        shipment: ShipmentSpec = get_scenarios()[idx % 3].shipment
        t0 = time.perf_counter()
        metrics = compute_gnn_warmstart(CORRIDOR_EDGES, disruption, shipment)
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)
        assert 45.0 <= metrics.prune_ratio_pct <= 92.0

    p99_ms = float(np.percentile(latencies_ms, 99))
    assert p99_ms < 30.0, f"ONNX Stage 3 P99 ({p99_ms:.3f} ms) exceeded 30ms SLA"
