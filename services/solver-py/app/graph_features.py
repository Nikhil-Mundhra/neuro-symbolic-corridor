"""Shared spatiotemporal graph tensor builder for T-GNN training and ONNX Runtime inference."""

from __future__ import annotations

import math

import numpy as np

from app.models import CorridorEdge, DisruptionState, ShipmentSpec, TransportMode
from app.network import CORRIDOR_NODES

NODE_FEATURE_DIM = 8
EDGE_FEATURE_DIM = 23
DELAY_FEATURE_DIM = 4

_MODE_INDEX: dict[TransportMode, int] = {
    TransportMode.SEA: 0,
    TransportMode.GREEN_CORRIDOR_TRUCK: 1,
    TransportMode.ETIHAD_RAIL_BONDED: 2,
    TransportMode.AIR_CARGO: 3,
    TransportMode.UNBONDED_SPOT_TRUCK: 4,
}

_CANONICAL_NODE_INDEX: dict[str, int] = {node.id: idx for idx, node in enumerate(CORRIDOR_NODES)}
_CANONICAL_STATIC_NODES = np.array(
    [
        [
            node.lon / 100.0,
            node.lat / 60.0,
            node.daily_demurrage_usd / 500.0,
            0.0,  # is_origin (populated per shipment)
            0.0,  # is_dest (populated per shipment)
            1.0 if ("UAE" in node.country or "Oman" in node.country) else 0.0,
            0.0,  # is_temp_sensitive (populated per shipment)
            0.0,  # cepa_compliant_shipment (populated per shipment/disruption)
        ]
        for node in CORRIDOR_NODES
    ],
    dtype=np.float32,
)


def build_graph_tensors(
    edges: list[CorridorEdge],
    disruption: DisruptionState,
    shipment: ShipmentSpec,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build (node_features, edge_index, edge_features, delay_features) for the corridor graph.

    Note: `node_features` and `edge_features` intentionally exclude `hormuz_delay_hours` and
    `jebel_ali_congestion_hours` so those delay pressures enter exclusively through the
    monotonic `delay_features` branch of `TemporalCorridorGATv2`.
    """
    node_to_idx = dict(_CANONICAL_NODE_INDEX)
    extra_rows: list[list[float]] = []
    for edge in edges:
        for nid in (edge.source, edge.target):
            if nid not in node_to_idx:
                node_to_idx[nid] = len(node_to_idx)
                extra_rows.append([0.5, 0.4, 0.4, 0.0, 0.0, 0.0, 0.0, 0.0])

    if extra_rows:
        node_features = np.vstack([_CANONICAL_STATIC_NODES, np.array(extra_rows, dtype=np.float32)])
    else:
        node_features = _CANONICAL_STATIC_NODES.copy()

    if shipment.origin_node in node_to_idx:
        node_features[node_to_idx[shipment.origin_node], 3] = 1.0
    if shipment.destination_node in node_to_idx:
        node_features[node_to_idx[shipment.destination_node], 4] = 1.0

    temp_sens = 1.0 if shipment.is_temp_sensitive else 0.0
    cepa_ok = (
        1.0
        if (not disruption.require_cepa_zero_tariff or shipment.cepa_value_add_pct >= 40.0)
        else 0.0
    )
    node_features[:, 6] = temp_sens
    node_features[:, 7] = cepa_ok

    num_edges = len(edges)
    edge_index = np.zeros((2, num_edges), dtype=np.int64)
    edge_features = np.zeros((num_edges, EDGE_FEATURE_DIM), dtype=np.float32)
    delay_features = np.zeros((num_edges, DELAY_FEATURE_DIM), dtype=np.float32)

    temp_headroom = max(0.5, shipment.max_temp_c - shipment.initial_temp_c)
    max_hours = max(1.0, shipment.max_transit_hours)
    vot_norm = min(5.0, shipment.value_of_time_usd_per_hour / 1000.0)
    cargo_val_norm = math.log1p(shipment.cargo_value_usd) / 20.0
    teu_norm = min(5.0, shipment.teu_count / 100.0)
    red_sea_norm = disruption.red_sea_surcharge_usd / 5000.0
    hormuz_norm = disruption.hormuz_delay_hours / 120.0
    jebel_norm = disruption.jebel_ali_congestion_hours / 72.0
    cepa_below_threshold = (
        disruption.require_cepa_zero_tariff and shipment.cepa_value_add_pct < 40.0
    )

    for idx, edge in enumerate(edges):
        edge_index[0, idx] = node_to_idx[edge.source]
        edge_index[1, idx] = node_to_idx[edge.target]

        edge_features[idx, 0] = 1.0 if edge.passes_hormuz else 0.0
        edge_features[idx, 1] = 1.0 if edge.touches_jebel_ali else 0.0
        edge_features[idx, 2] = 1.0 if edge.touches_oman else 0.0
        edge_features[idx, 3] = 1.0 if edge.has_continuous_customs_seal else 0.0
        edge_features[idx, 4] = 1.0 if edge.is_green_corridor else 0.0
        edge_features[idx, 5] = 1.0 if edge.active_cold_chain else 0.0
        edge_features[idx, 6] = edge.base_hours / 350.0
        edge_features[idx, 7] = edge.base_cost_per_teu_usd / 5000.0
        edge_features[idx, 8] = edge.distance_km / 12000.0
        edge_features[idx, 9] = edge.thermal_drift_c_per_hour * 10.0
        edge_features[idx, 10 + _MODE_INDEX[edge.mode]] = 1.0

        reefer_sea = (
            disruption.reefer_fault
            and shipment.is_temp_sensitive
            and edge.mode == TransportMode.SEA
        )
        edge_features[idx, 15] = 1.0 if reefer_sea else 0.0
        edge_features[idx, 16] = (
            min(
                5.0,
                (disruption.reefer_ambient_drift_c_per_hour * edge.base_hours) / temp_headroom,
            )
            if reefer_sea
            else 0.0
        )
        edge_features[idx, 17] = (
            red_sea_norm if edge.id in ("E_AEJEA_EUFRA_SEA", "E_AEKHL_EUFRA_SEA") else 0.0
        )
        edge_features[idx, 18] = min(5.0, edge.base_hours / max_hours)
        edge_features[idx, 19] = vot_norm
        edge_features[idx, 20] = cargo_val_norm
        edge_features[idx, 21] = teu_norm
        edge_features[idx, 22] = (
            1.0 if (not edge.has_continuous_customs_seal or cepa_below_threshold) else 0.0
        )

        if edge.passes_hormuz:
            delay_features[idx, 0] = hormuz_norm
            delay_features[idx, 2] = min(5.0, disruption.hormuz_delay_hours / max_hours)
            if disruption.reefer_fault and shipment.is_temp_sensitive:
                delay_features[idx, 3] = min(
                    5.0,
                    (disruption.hormuz_delay_hours * disruption.reefer_ambient_drift_c_per_hour)
                    / temp_headroom,
                )
        if edge.touches_jebel_ali:
            delay_features[idx, 1] = jebel_norm

    return node_features, edge_index, edge_features, delay_features
