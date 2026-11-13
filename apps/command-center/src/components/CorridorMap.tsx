import { useMemo, useState } from 'react';
import DeckGL from '@deck.gl/react';
import { ArcLayer, PathLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import type { CorridorEdge, CorridorNode, SolveResponse } from '../types';

interface CorridorMapProps {
  nodes: CorridorNode[];
  edges: CorridorEdge[];
  solution: SolveResponse | null;
  hormuzDelayHours: number;
  jebelAliDelayHours: number;
}

// Simplified regional coastline guide paths so the WebGL map stays legible even offline
const REGIONAL_COASTLINES: { name: string; path: [number, number][] }[] = [
  {
    name: 'Arabian Peninsula & Gulf',
    path: [
      [48.5, 29.8],
      [50.2, 26.3],
      [51.5, 25.3],
      [54.3, 24.4],
      [55.3, 25.3],
      [56.4, 26.2],
      [56.4, 25.0],
      [57.8, 23.6],
      [59.8, 22.4],
      [57.7, 20.2],
      [54.1, 17.0],
      [45.0, 12.8],
      [43.3, 12.6],
      [39.1, 21.5],
      [34.9, 29.5],
    ],
  },
  {
    name: 'Iran / Strait of Hormuz North Shore',
    path: [
      [48.8, 30.0],
      [50.8, 28.9],
      [53.4, 26.7],
      [56.3, 27.1],
      [57.1, 25.7],
      [61.5, 25.2],
      [67.0, 24.8],
    ],
  },
  {
    name: 'India West Coast',
    path: [
      [68.8, 23.8],
      [70.1, 20.9],
      [72.8, 21.2],
      [72.9, 18.9],
      [73.8, 15.4],
      [76.2, 9.9],
    ],
  },
  {
    name: 'Europe North / Mediterranean Corridor',
    path: [
      [-5.3, 36.1],
      [3.1, 43.3],
      [12.3, 45.4],
      [14.0, 40.8],
      [23.7, 37.9],
      [29.0, 41.0],
    ],
  },
  {
    name: 'North Sea / Rhine Gateway',
    path: [
      [-1.5, 50.8],
      [4.4, 51.9],
      [8.5, 53.5],
      [10.0, 54.0],
    ],
  },
];

const INITIAL_VIEW_STATE = {
  longitude: 54.5,
  latitude: 24.7,
  zoom: 4.3,
  pitch: 32,
  bearing: -8,
};

export function CorridorMap({
  nodes,
  edges,
  solution,
  hormuzDelayHours,
  jebelAliDelayHours,
}: CorridorMapProps) {
  const [viewMode, setViewMode] = useState<'gulf' | 'eurasia'>('gulf');

  const viewState = useMemo(
    () =>
      viewMode === 'gulf'
        ? INITIAL_VIEW_STATE
        : {
            longitude: 42.0,
            latitude: 33.5,
            zoom: 2.55,
            pitch: 24,
            bearing: -4,
          },
    [viewMode]
  );

  const nodeById = useMemo(() => {
    const map = new Map<string, CorridorNode>();
    for (const n of nodes) map.set(n.id, n);
    return map;
  }, [nodes]);

  const optimalEdgeSet = useMemo(
    () => new Set(solution?.optimal_route.edge_ids ?? []),
    [solution]
  );

  const optimalNodeSet = useMemo(
    () => new Set(solution?.optimal_route.node_sequence ?? []),
    [solution]
  );

  const baselineEdgeSet = useMemo(() => {
    const baseline = solution?.candidates.find((c) => c.is_baseline);
    return new Set(baseline?.edge_ids ?? []);
  }, [solution]);

  const layers = useMemo(() => {
    const coastlineLayer = new PathLayer({
      id: 'regional-coastlines',
      data: REGIONAL_COASTLINES,
      getPath: (d) => d.path,
      getColor: [96, 125, 155, 110],
      getWidth: 2,
      widthUnits: 'pixels',
    });

    const arcData = edges
      .map((e) => {
        const src = nodeById.get(e.source);
        const dst = nodeById.get(e.target);
        if (!src || !dst) return null;
        const isOptimal = optimalEdgeSet.has(e.id);
        const isBaselineBlocked =
          baselineEdgeSet.has(e.id) &&
          !isOptimal &&
          (hormuzDelayHours > 0 || jebelAliDelayHours > 0);
        return {
          ...e,
          from: [src.lon, src.lat] as [number, number],
          to: [dst.lon, dst.lat] as [number, number],
          isOptimal,
          isBaselineBlocked,
        };
      })
      .filter((x): x is NonNullable<typeof x> => x !== null);

    const networkPathLayer = new PathLayer({
      id: 'corridor-sea-lanes',
      data: arcData.filter((d) => d.waypoints && d.waypoints.length >= 2),
      getPath: (d) => d.waypoints as [number, number][],
      getColor: (d) =>
        d.isOptimal
          ? [16, 185, 129, 235]
          : d.isBaselineBlocked
            ? [239, 68, 68, 190]
            : [100, 116, 139, 95],
      getWidth: (d) => (d.isOptimal ? 5 : d.isBaselineBlocked ? 3 : 1.5),
      widthUnits: 'pixels',
    });

    const arcLayer = new ArcLayer({
      id: 'corridor-multimodal-arcs',
      data: arcData.filter((d) => !d.waypoints || d.waypoints.length < 2),
      getSourcePosition: (d) => d.from,
      getTargetPosition: (d) => d.to,
      getSourceColor: (d) =>
        d.isOptimal
          ? [16, 185, 129, 255]
          : d.mode === 'UNBONDED_SPOT_TRUCK'
            ? [245, 158, 11, 140]
            : [56, 189, 248, 110],
      getTargetColor: (d) =>
        d.isOptimal
          ? [34, 211, 238, 255]
          : d.mode === 'UNBONDED_SPOT_TRUCK'
            ? [239, 68, 68, 140]
            : [99, 102, 241, 110],
      getWidth: (d) => (d.isOptimal ? 5 : 2),
      getHeight: (d) => (d.mode === 'AIR_CARGO' ? 0.45 : 0.08),
    });

    const chokePoints =
      hormuzDelayHours > 0
        ? [
            {
              name: `HORMUZ CHOKE (+${hormuzDelayHours}h)`,
              position: [56.45, 26.35] as [number, number],
              radius: 42000 + hormuzDelayHours * 450,
            },
          ]
        : [];

    const chokeLayer = new ScatterplotLayer({
      id: 'hormuz-choke-ring',
      data: chokePoints,
      getPosition: (d) => d.position,
      getRadius: (d) => d.radius,
      getFillColor: [239, 68, 68, 55],
      getLineColor: [248, 113, 113, 230],
      stroked: true,
      lineWidthMinPixels: 2,
    });

    const nodeLayer = new ScatterplotLayer({
      id: 'corridor-nodes',
      data: nodes,
      pickable: true,
      getPosition: (d) => [d.lon, d.lat],
      getRadius: (d) => (optimalNodeSet.has(d.id) ? 18000 : 11000),
      radiusMinPixels: 6,
      radiusMaxPixels: 14,
      getFillColor: (d) => {
        if (d.id === 'AEJEA' && jebelAliDelayHours > 0 && !optimalNodeSet.has('AEJEA')) {
          return [239, 68, 68, 240];
        }
        if (optimalNodeSet.has(d.id)) {
          return [16, 185, 129, 255];
        }
        return [56, 189, 248, 190];
      },
      getLineColor: [255, 255, 255, 220],
      stroked: true,
      lineWidthMinPixels: 1.5,
    });

    const labelLayer = new TextLayer({
      id: 'corridor-node-labels',
      data: nodes,
      getPosition: (d) => [d.lon, d.lat],
      getText: (d) => `${d.code}`,
      getSize: 12,
      getColor: [226, 232, 240, 240],
      getPixelOffset: [0, -16],
      fontWeight: 'bold',
    });

    return [coastlineLayer, networkPathLayer, arcLayer, chokeLayer, nodeLayer, labelLayer];
  }, [
    nodes,
    edges,
    nodeById,
    optimalEdgeSet,
    optimalNodeSet,
    baselineEdgeSet,
    hormuzDelayHours,
    jebelAliDelayHours,
  ]);

  return (
    <div className="digital-twin-canvas">
      <div className="map-toolbar">
        <div className="map-legend">
          <span className="legend-pill optimal">Optimal Z3+MILP Route</span>
          <span className="legend-pill blocked">Blocked / UNSAT Maritime</span>
          <span className="legend-pill network">Multimodal Network</span>
        </div>
        <div className="map-zoom-controls">
          <button
            type="button"
            className={viewMode === 'gulf' ? 'chip active' : 'chip'}
            onClick={() => setViewMode('gulf')}
          >
            Gulf / Oman Focus
          </button>
          <button
            type="button"
            className={viewMode === 'eurasia' ? 'chip active' : 'chip'}
            onClick={() => setViewMode('eurasia')}
          >
            India → UAE → EU Corridor
          </button>
        </div>
      </div>

      <div className="deckgl-stage" aria-label="Gulf Corridor WebGL Digital Twin Map">
        <DeckGL
          initialViewState={viewState}
          controller={true}
          layers={layers}
          getTooltip={({ object }) => {
            if (!object) return null;
            if ('code' in object) {
              const n = object as CorridorNode;
              return `${n.code} — ${n.name}\n${n.role} (${n.customs_zone})`;
            }
            return null;
          }}
        />
      </div>

      {solution && (
        <div className="route-ribbon">
          <span className="ribbon-label">Active Verified Vector:</span>
          <span className="ribbon-path">
            {solution.optimal_route.node_sequence.join('  →  ')}
          </span>
        </div>
      )}
    </div>
  );
}
