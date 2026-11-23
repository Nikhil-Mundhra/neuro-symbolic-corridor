"""PyTorch Geometric Temporal-GATv2 training, evaluation, and ONNX export pipeline."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import onnx
import onnxruntime as ort
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.data import Batch, Data
from torch_geometric.nn import GATv2Conv

from app.graph_features import DELAY_FEATURE_DIM, EDGE_FEATURE_DIM, NODE_FEATURE_DIM
from app.synthetic_data import (
    CorridorOracleSample,
    DatasetSplits,
    generate_monte_carlo_dataset,
    save_dataset_splits,
)

DEFAULT_ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "artifacts"
PRUNE_THRESHOLD = 0.72


class MonotonicLinear(nn.Module):
    """Linear projection with strictly positive weights via softplus for delay monotonicity."""

    def __init__(self, in_features: int, out_features: int) -> None:
        super().__init__()
        self.weight = nn.Parameter(torch.full((out_features, in_features), -0.8))
        self.bias = nn.Parameter(torch.zeros(out_features))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.linear(x, F.softplus(self.weight), self.bias)


class TemporalCorridorGATv2(nn.Module):
    """2-Layer PyG GATv2 architecture with monotonic spatiotemporal delay residual head."""

    def __init__(
        self,
        node_in_dim: int = NODE_FEATURE_DIM,
        edge_in_dim: int = EDGE_FEATURE_DIM,
        delay_in_dim: int = DELAY_FEATURE_DIM,
        hidden_dim: int = 32,
        edge_dim: int = 16,
        heads: int = 4,
    ) -> None:
        super().__init__()
        self.node_encoder = nn.Sequential(
            nn.Linear(node_in_dim, hidden_dim),
            nn.ReLU(),
        )
        self.edge_encoder = nn.Sequential(
            nn.Linear(edge_in_dim, edge_dim),
            nn.ReLU(),
        )
        self.gat1 = GATv2Conv(
            hidden_dim,
            hidden_dim // heads,
            heads=heads,
            edge_dim=edge_dim,
            add_self_loops=False,
        )
        self.norm1 = nn.LayerNorm(hidden_dim)
        self.gat2 = GATv2Conv(
            hidden_dim,
            hidden_dim // heads,
            heads=heads,
            edge_dim=edge_dim,
            add_self_loops=False,
        )
        self.norm2 = nn.LayerNorm(hidden_dim)

        self.edge_head = nn.Sequential(
            nn.Linear(hidden_dim * 2 + edge_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )
        self.delay_head = nn.Sequential(
            MonotonicLinear(delay_in_dim, 8),
            nn.ReLU(),
            MonotonicLinear(8, 1),
        )

    def forward(
        self,
        node_features: torch.Tensor,
        edge_index: torch.Tensor,
        edge_features: torch.Tensor,
        delay_features: torch.Tensor,
    ) -> torch.Tensor:
        h = self.node_encoder(node_features)
        e_emb = self.edge_encoder(edge_features)

        h = F.relu(self.norm1(h + self.gat1(h, edge_index, e_emb)))
        h = F.relu(self.norm2(h + self.gat2(h, edge_index, e_emb)))

        src = edge_index[0]
        dst = edge_index[1]
        edge_repr = torch.cat([h[src], h[dst], e_emb], dim=-1)
        base_logit = self.edge_head(edge_repr).squeeze(-1)
        delay_logit = self.delay_head(delay_features).squeeze(-1)
        return torch.sigmoid(base_logit + delay_logit)


@dataclass(frozen=True)
class EvalMetrics:
    """Validation / test evaluation summary for T-GNN edge pruning."""

    bce_loss: float
    edge_accuracy: float
    f1_score: float
    auroc: float
    optimal_edge_keep_recall: float
    prunable_edge_recall: float
    unsat_edge_recall: float


@dataclass(frozen=True)
class TrainingResult:
    """Artifacts and metrics returned by `train_and_export`."""

    onnx_path: Path
    metadata_path: Path
    val_metrics: EvalMetrics
    test_metrics: EvalMetrics
    onnx_parity_max_diff: float
    onnx_avg_inference_ms: float
    epochs: int
    dataset_metadata: dict[str, Any]


def _samples_to_pyg_data(samples: list[CorridorOracleSample]) -> list[Data]:
    data_list: list[Data] = []
    for sample in samples:
        data_list.append(
            Data(
                x=torch.from_numpy(sample.node_features),
                edge_index=torch.from_numpy(sample.edge_index),
                edge_attr=torch.from_numpy(sample.edge_features),
                delay_attr=torch.from_numpy(sample.delay_features),
                y=torch.from_numpy(sample.edge_prune_labels),
                sat_feasible=torch.from_numpy(sample.edge_sat_feasible),
            )
        )
    return data_list


def _compute_auroc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    pos_mask = y_true >= 0.5
    neg_mask = ~pos_mask
    n_pos = int(np.sum(pos_mask))
    n_neg = int(np.sum(neg_mask))
    if n_pos == 0 or n_neg == 0:
        return 1.0
    order = np.argsort(y_score, kind="mergesort")
    ranks = np.empty_like(y_score, dtype=np.float64)
    ranks[order] = np.arange(1, len(y_score) + 1, dtype=np.float64)
    sum_pos_ranks = float(np.sum(ranks[pos_mask]))
    return float((sum_pos_ranks - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


@torch.no_grad()
def evaluate_model(
    model: TemporalCorridorGATv2,
    samples: list[CorridorOracleSample],
    prune_threshold: float = PRUNE_THRESHOLD,
) -> EvalMetrics:
    """Evaluate T-GNN predictions against Z3+MILP oracle labels."""
    model.eval()
    batch = Batch.from_data_list(_samples_to_pyg_data(samples))
    preds = model(batch.x, batch.edge_index, batch.edge_attr, batch.delay_attr)
    targets = batch.y
    bce = float(F.binary_cross_entropy(preds, targets).item())

    y_pred = preds.cpu().numpy()
    y_true = targets.cpu().numpy()
    sat_feasible = batch.sat_feasible.cpu().numpy()

    pred_bin = y_pred >= 0.5
    true_bin = y_true >= 0.5
    accuracy = float(np.mean(pred_bin == true_bin))

    tp = int(np.sum(pred_bin & true_bin))
    fp = int(np.sum(pred_bin & (~true_bin)))
    fn = int(np.sum((~pred_bin) & true_bin))
    f1 = (2.0 * tp) / max(1, 2 * tp + fp + fn)

    auroc = _compute_auroc(y_true, y_pred)

    opt_mask = ~true_bin
    opt_keep_recall = (
        float(np.mean(y_pred[opt_mask] < prune_threshold)) if np.any(opt_mask) else 1.0
    )
    prune_recall = float(np.mean(y_pred[true_bin] >= prune_threshold)) if np.any(true_bin) else 1.0
    unsat_mask = sat_feasible < 0.5
    unsat_recall = float(np.mean(y_pred[unsat_mask] >= 0.5)) if np.any(unsat_mask) else 1.0

    return EvalMetrics(
        bce_loss=round(bce, 5),
        edge_accuracy=round(accuracy, 4),
        f1_score=round(float(f1), 4),
        auroc=round(auroc, 4),
        optimal_edge_keep_recall=round(opt_keep_recall, 4),
        prunable_edge_recall=round(prune_recall, 4),
        unsat_edge_recall=round(unsat_recall, 4),
    )


def export_model_to_onnx(
    model: TemporalCorridorGATv2,
    sample: CorridorOracleSample,
    onnx_path: Path,
) -> tuple[float, float]:
    """Export trained `TemporalCorridorGATv2` to self-contained ONNX and verify ORT parity."""
    model.eval()
    onnx_path.parent.mkdir(parents=True, exist_ok=True)

    x = torch.from_numpy(sample.node_features)
    edge_index = torch.from_numpy(sample.edge_index)
    edge_attr = torch.from_numpy(sample.edge_features)
    delay_attr = torch.from_numpy(sample.delay_features)

    num_nodes = torch.export.Dim("num_nodes", min=2, max=2048)
    num_edges = torch.export.Dim("num_edges", min=1, max=16384)

    torch.onnx.export(
        model,
        (x, edge_index, edge_attr, delay_attr),
        str(onnx_path),
        input_names=["node_features", "edge_index", "edge_features", "delay_features"],
        output_names=["edge_risk_scores"],
        dynamic_shapes={
            "node_features": {0: num_nodes},
            "edge_index": {1: num_edges},
            "edge_features": {0: num_edges},
            "delay_features": {0: num_edges},
        },
        dynamo=True,
        external_data=False,
    )

    onnx_model = onnx.load(str(onnx_path))
    onnx.checker.check_model(onnx_model)

    sess_opts = ort.SessionOptions()
    sess_opts.intra_op_num_threads = 1
    sess_opts.inter_op_num_threads = 1
    session = ort.InferenceSession(
        str(onnx_path), sess_options=sess_opts, providers=["CPUExecutionProvider"]
    )
    feed = {
        "node_features": sample.node_features,
        "edge_index": sample.edge_index,
        "edge_features": sample.edge_features,
        "delay_features": sample.delay_features,
    }
    with torch.no_grad():
        pt_out = model(x, edge_index, edge_attr, delay_attr).cpu().numpy()
    ort_out = session.run(None, feed)[0]
    max_diff = float(np.max(np.abs(pt_out - ort_out)))

    t0 = time.perf_counter()
    for _ in range(100):
        session.run(None, feed)
    avg_ms = ((time.perf_counter() - t0) * 1000.0) / 100.0
    return max_diff, avg_ms


def train_and_export(
    splits: DatasetSplits | None = None,
    num_samples: int = 900,
    epochs: int = 45,
    batch_size: int = 64,
    lr: float = 3e-3,
    seed: int = 42,
    output_dir: Path = DEFAULT_ARTIFACTS_DIR,
    save_dataset: bool = False,
) -> TrainingResult:
    """Train TemporalCorridorGATv2 on Monte Carlo oracle data and export ONNX artifact."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)

    if splits is None:
        splits = generate_monte_carlo_dataset(num_samples=num_samples, seed=seed)
    if save_dataset:
        save_dataset_splits(splits, output_dir)

    train_data = _samples_to_pyg_data(splits.train)
    model = TemporalCorridorGATv2()
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-3)

    label_smooth_eps = 0.03
    for _ in range(epochs):
        model.train()
        perm = rng.permutation(len(train_data))
        for start in range(0, len(train_data), batch_size):
            idx_slice = perm[start : start + batch_size]
            batch = Batch.from_data_list([train_data[int(i)] for i in idx_slice])
            optimizer.zero_grad()
            preds = model(batch.x, batch.edge_index, batch.edge_attr, batch.delay_attr)

            # Label smoothing prevents sigmoid saturation while higher weight on optimal edges
            # (y == 0) protects safe pruning recall so optimal edges are not falsely pruned.
            smooth_targets = batch.y * (1.0 - 2.0 * label_smooth_eps) + label_smooth_eps
            weights = torch.where(batch.y < 0.5, 2.2, 1.0)
            loss = F.binary_cross_entropy(preds, smooth_targets, weight=weights)
            loss.backward()
            optimizer.step()

    val_metrics = evaluate_model(model, splits.val)
    test_metrics = evaluate_model(model, splits.test)

    onnx_path = output_dir / "corridor_tgnn.onnx"
    metadata_path = output_dir / "corridor_tgnn.meta.json"
    max_diff, avg_ms = export_model_to_onnx(model, splits.val[0], onnx_path)

    metadata = {
        "model_architecture": "Temporal-GATv2 (2-Layer PyG ONNX)",
        "feature_dims": {
            "node": NODE_FEATURE_DIM,
            "edge": EDGE_FEATURE_DIM,
            "delay": DELAY_FEATURE_DIM,
        },
        "prune_threshold": PRUNE_THRESHOLD,
        "epochs": epochs,
        "seed": seed,
        "dataset": splits.metadata,
        "val_metrics": asdict(val_metrics),
        "test_metrics": asdict(test_metrics),
        "onnx_parity_max_diff": round(max_diff, 8),
        "onnx_avg_inference_ms": round(avg_ms, 4),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return TrainingResult(
        onnx_path=onnx_path,
        metadata_path=metadata_path,
        val_metrics=val_metrics,
        test_metrics=test_metrics,
        onnx_parity_max_diff=max_diff,
        onnx_avg_inference_ms=avg_ms,
        epochs=epochs,
        dataset_metadata=splits.metadata,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for training and exporting the Temporal-GATv2 ONNX model."""
    parser = argparse.ArgumentParser(description="Train T-GNN on Z3+MILP oracle & export ONNX.")
    parser.add_argument("--samples", type=int, default=900)
    parser.add_argument("--epochs", type=int, default=45)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ARTIFACTS_DIR)
    parser.add_argument("--save-dataset", action="store_true")
    args = parser.parse_args(argv)

    result = train_and_export(
        num_samples=args.samples,
        epochs=args.epochs,
        seed=args.seed,
        output_dir=args.output_dir,
        save_dataset=args.save_dataset,
    )
    print(
        json.dumps(
            {
                "onnx_path": str(result.onnx_path),
                "metadata_path": str(result.metadata_path),
                "val_metrics": asdict(result.val_metrics),
                "test_metrics": asdict(result.test_metrics),
                "onnx_parity_max_diff": result.onnx_parity_max_diff,
                "onnx_avg_inference_ms": result.onnx_avg_inference_ms,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
