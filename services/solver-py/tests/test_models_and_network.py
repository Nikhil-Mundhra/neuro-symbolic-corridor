"""Unit tests for Pydantic models and Gulf Corridor network topology."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import (
    DisruptionState,
    ParseBoLRequest,
    ShipmentSpec,
    TransportMode,
)
from app.network import (
    CANDIDATE_ROUTES,
    CORRIDOR_EDGES,
    CORRIDOR_NODES,
    get_edge_map,
    get_node_map,
    get_topology,
)


def test_corridor_topology_integrity() -> None:
    topo = get_topology()
    assert len(topo.nodes) == len(CORRIDOR_NODES) == 10
    assert len(topo.edges) == len(CORRIDOR_EDGES) == 15

    node_map = get_node_map()
    edge_map = get_edge_map()
    assert len(node_map) == 10
    assert len(edge_map) == 15

    for edge in topo.edges:
        assert edge.source in node_map
        assert edge.target in node_map
        assert edge.base_hours > 0
        assert edge.distance_km > 0


def test_candidate_routes_are_connected_innsa_to_eufra() -> None:
    edge_map = get_edge_map()
    for route in CANDIDATE_ROUTES:
        edge_ids: list[str] = route["edge_ids"]  # type: ignore[assignment]
        assert len(edge_ids) >= 2
        edges = [edge_map[eid] for eid in edge_ids]
        assert edges[0].source == "INNSA"
        assert edges[-1].target == "EUFRA"
        for idx in range(len(edges) - 1):
            assert edges[idx].target == edges[idx + 1].source


def test_model_validation_bounds() -> None:
    with pytest.raises(ValidationError):
        DisruptionState(hormuz_delay_hours=-5.0)

    with pytest.raises(ValidationError):
        ShipmentSpec(
            bol_number="B1",
            shipper="S",
            consignee="C",
            cargo_description="Cargo",
            hs_code="12",
            teu_count=0,
        )

    with pytest.raises(ValidationError):
        ParseBoLRequest(raw_text="short")

    assert TransportMode.GREEN_CORRIDOR_TRUCK.value == "GREEN_CORRIDOR_TRUCK"
