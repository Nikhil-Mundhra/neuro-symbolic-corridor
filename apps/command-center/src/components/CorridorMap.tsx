import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  buildCurvedArcPath,
  buildWaypointSvgPath,
  CameraState,
  CORRIDOR_COUNTRIES,
  GEO_LABELS,
  getVisibleTiles,
  MAP_HEIGHT,
  MAP_WIDTH,
  MapRenderMode,
  NODE_CALLOUT_LAYOUT,
  projectLonLat,
  TILE_PROVIDERS,
  TileProviderId,
  VIEW_PRESETS,
  ViewPresetId,
} from './corridorGeoData';
import type { CorridorEdge, CorridorNode, SolveResponse, TransportMode } from '../types';

interface CorridorMapProps {
  nodes: CorridorNode[];
  edges: CorridorEdge[];
  solution: SolveResponse | null;
  hormuzDelayHours: number;
  jebelAliDelayHours: number;
}

const MODE_SHORT_LABEL: Record<TransportMode, string> = {
  SEA: 'SEA',
  GREEN_CORRIDOR_TRUCK: 'GREEN TRUCK',
  ETIHAD_RAIL_BONDED: 'RAIL',
  AIR_CARGO: 'AIR',
  UNBONDED_SPOT_TRUCK: 'UNBONDED',
};

function getInitialProvider(): TileProviderId {
  if (typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: light)').matches) {
    return 'esri-light';
  }
  return 'esri-dark';
}

export function CorridorMap({
  nodes,
  edges,
  solution,
  hormuzDelayHours,
  jebelAliDelayHours,
}: CorridorMapProps) {
  const [presetId, setPresetId] = useState<ViewPresetId>('gulf');
  const [tileProvider, setTileProvider] = useState<TileProviderId>(getInitialProvider);
  const [renderMode, setRenderMode] = useState<MapRenderMode>('geo');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [failedTiles, setFailedTiles] = useState<Record<string, boolean>>({});
  const [camera, setCamera] = useState<CameraState>({
    centerLon: VIEW_PRESETS.gulf.centerLon,
    centerLat: VIEW_PRESETS.gulf.centerLat,
    zoom: VIEW_PRESETS.gulf.zoom,
    panX: 0,
    panY: 0,
  });

  const stageRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ startX: number; startY: number; panX: number; panY: number } | null>(
    null
  );
  const [isDragging, setIsDragging] = useState(false);

  const selectPreset = useCallback((id: ViewPresetId) => {
    const preset = VIEW_PRESETS[id];
    setPresetId(id);
    setCamera({
      centerLon: preset.centerLon,
      centerLat: preset.centerLat,
      zoom: preset.zoom,
      panX: 0,
      panY: 0,
    });
  }, []);

  // Automatically clear tile failure cache when switching provider
  useEffect(() => {
    setFailedTiles({});
  }, [tileProvider]);

  const adjustZoom = useCallback((factor: number) => {
    setCamera((prev) => {
      const nextZoom = Math.max(2.2, Math.min(9.5, prev.zoom + Math.log2(factor)));
      return { ...prev, zoom: nextZoom };
    });
  }, []);

  const handleWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    if (renderMode !== 'geo') return;
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.18 : 1 / 1.18;
    adjustZoom(factor);
  };

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (renderMode !== 'geo' || (e.button !== 0 && e.pointerType === 'mouse')) return;
    if ((e.target as HTMLElement).closest('button, select, [data-node-id]')) return;
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      panX: camera.panX,
      panY: camera.panY,
    };
    setIsDragging(true);
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragRef.current || !stageRef.current) return;
    const rect = stageRef.current.getBoundingClientRect();
    const scaleX = MAP_WIDTH / Math.max(1, rect.width);
    const scaleY = MAP_HEIGHT / Math.max(1, rect.height);
    const dx = (e.clientX - dragRef.current.startX) * scaleX;
    const dy = (e.clientY - dragRef.current.startY) * scaleY;
    setCamera((prev) => ({
      ...prev,
      panX: dragRef.current ? dragRef.current.panX + dx : prev.panX,
      panY: dragRef.current ? dragRef.current.panY + dy : prev.panY,
    }));
  };

  const handlePointerUp = () => {
    dragRef.current = null;
    setIsDragging(false);
  };

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

  const providerConfig = TILE_PROVIDERS[tileProvider];

  const visibleTiles = useMemo(
    () => getVisibleTiles(camera, providerConfig.urlTemplate, MAP_WIDTH, MAP_HEIGHT),
    [camera, providerConfig.urlTemplate]
  );

  const countryPaths = useMemo(
    () =>
      CORRIDOR_COUNTRIES.map((country) => ({
        name: country.name,
        gulf: country.gulf,
        d: country.rings
          .map((ring) => {
            if (ring.length < 3) return '';
            const pts = ring.map(([lon, lat], i) => {
              const [x, y] = projectLonLat(lon, lat, camera);
              return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
            });
            return `${pts.join(' ')} Z`;
          })
          .join(' '),
      })),
    [camera]
  );

  const projectedEdges = useMemo(() => {
    return edges
      .map((edge) => {
        const src = nodeById.get(edge.source);
        const dst = nodeById.get(edge.target);
        if (!src || !dst) return null;

        const isOptimal = optimalEdgeSet.has(edge.id);
        const isBaselineBlocked =
          baselineEdgeSet.has(edge.id) &&
          !isOptimal &&
          (hormuzDelayHours > 0 || jebelAliDelayHours > 0);
        const routeState: 'optimal' | 'blocked' | 'network' = isOptimal
          ? 'optimal'
          : isBaselineBlocked
            ? 'blocked'
            : 'network';

        let d = '';
        let mid: [number, number] = [0, 0];
        if (edge.waypoints && edge.waypoints.length >= 2) {
          const pts = edge.waypoints as [number, number][];
          d = buildWaypointSvgPath(pts, camera);
          const midPt = pts[Math.floor(pts.length / 2)];
          mid = projectLonLat(midPt[0], midPt[1], camera);
        } else {
          const lift =
            edge.mode === 'AIR_CARGO' ? 0.28 : edge.mode === 'UNBONDED_SPOT_TRUCK' ? -0.14 : 0.14;
          const curved = buildCurvedArcPath([src.lon, src.lat], [dst.lon, dst.lat], camera, lift);
          d = curved.d;
          mid = curved.midpoint;
        }

        return {
          edge,
          routeState,
          d,
          mid,
          modeLabel: MODE_SHORT_LABEL[edge.mode],
        };
      })
      .filter((item): item is NonNullable<typeof item> => item !== null)
      // Paint network first, blocked second, optimal on top
      .sort((a, b) => {
        const rank = { network: 0, blocked: 1, optimal: 2 };
        return rank[a.routeState] - rank[b.routeState];
      });
  }, [edges, nodeById, optimalEdgeSet, baselineEdgeSet, hormuzDelayHours, jebelAliDelayHours, camera]);

  const projectedNodes = useMemo(() => {
    const layoutMap = NODE_CALLOUT_LAYOUT[presetId];
    return nodes.map((node) => {
      const [x, y] = projectLonLat(node.lon, node.lat, camera);
      const inView = x >= -24 && x <= MAP_WIDTH + 24 && y >= -24 && y <= MAP_HEIGHT + 24;
      const isOptimal = optimalNodeSet.has(node.id);
      const isCongested =
        node.id === 'AEJEA' && jebelAliDelayHours > 0 && !optimalNodeSet.has('AEJEA');
      const offset = layoutMap[node.id] ?? {
        dx: 14,
        dy: -14,
        anchor: 'start' as const,
        shortName: node.code,
      };

      // In continental view, keep callouts focused on origin/destination/optimal/key hubs to avoid clutter
      const showCallout =
        inView &&
        (presetId === 'gulf' ||
          isOptimal ||
          isCongested ||
          node.id === 'INNSA' ||
          node.id === 'EUFRA' ||
          node.id === 'OMSLL' ||
          selectedNodeId === node.id);

      return {
        node,
        x,
        y,
        inView,
        isOptimal,
        isCongested,
        offset,
        showCallout,
      };
    });
  }, [nodes, camera, presetId, optimalNodeSet, jebelAliDelayHours, selectedNodeId]);

  const hormuzPoint = useMemo(
    () => projectLonLat(56.45, 26.35, camera),
    [camera]
  );

  const selectedNode = selectedNodeId ? nodeById.get(selectedNodeId) ?? null : null;

  return (
    <section className="corridor-map-card" aria-label="Corridor Spatial Digital Twin">
      <div className="map-header-bar">
        <div className="map-legend" role="list" aria-label="Route legend">
          <span role="listitem" className="legend-item optimal">
            <span className="legend-swatch optimal" /> Optimal Z3+MILP Route
          </span>
          <span role="listitem" className="legend-item blocked">
            <span className="legend-swatch blocked" /> Blocked / UNSAT Maritime
          </span>
          <span role="listitem" className="legend-item network">
            <span className="legend-swatch network" /> Multimodal Network
          </span>
        </div>

        <div className="map-controls-bar">
          <div className="segmented-group" role="group" aria-label="Map region focus">
            {(Object.keys(VIEW_PRESETS) as ViewPresetId[]).map((id) => (
              <button
                key={id}
                type="button"
                className={renderMode === 'geo' && presetId === id ? 'seg-btn active' : 'seg-btn'}
                onClick={() => {
                  setRenderMode('geo');
                  selectPreset(id);
                }}
              >
                {VIEW_PRESETS[id].label}
              </button>
            ))}
          </div>

          <div className="segmented-group" role="group" aria-label="Map representation">
            <button
              type="button"
              className={renderMode === 'geo' ? 'seg-btn active' : 'seg-btn'}
              onClick={() => setRenderMode('geo')}
            >
              Geographic Map
            </button>
            <button
              type="button"
              className={renderMode === 'schematic' ? 'seg-btn active' : 'seg-btn'}
              onClick={() => setRenderMode('schematic')}
            >
              Schematic Graph
            </button>
          </div>

          {renderMode === 'geo' && (
            <label className="basemap-select-wrap">
              <span className="sr-only">Tile Basemap Provider</span>
              <select
                aria-label="Tile Basemap Provider"
                className="basemap-select"
                value={tileProvider}
                onChange={(e) => setTileProvider(e.target.value as TileProviderId)}
              >
                {(Object.keys(TILE_PROVIDERS) as TileProviderId[]).map((id) => (
                  <option key={id} value={id}>
                    {TILE_PROVIDERS[id].label}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      </div>

      {renderMode === 'geo' ? (
        <div
          ref={stageRef}
          data-testid="corridor-map-stage"
          className={`geo-stage ${providerConfig.isDark ? 'is-dark-basemap' : 'is-light-basemap'} ${
            isDragging ? 'is-dragging' : ''
          }`}
          onWheel={handleWheel}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
        >
          <div className="zoom-toolbar" role="toolbar" aria-label="Map zoom controls">
            <button
              type="button"
              className="zoom-btn"
              onClick={() => adjustZoom(1.35)}
              aria-label="Zoom in"
              title="Zoom in"
            >
              +
            </button>
            <button
              type="button"
              className="zoom-btn"
              onClick={() => adjustZoom(1 / 1.35)}
              aria-label="Zoom out"
              title="Zoom out"
            >
              −
            </button>
            <button
              type="button"
              className="zoom-btn zoom-fit"
              onClick={() => selectPreset(presetId)}
              aria-label="Reset map view"
              title="Reset view"
            >
              Fit
            </button>
          </div>

          <svg
            data-testid="corridor-svg-map"
            className="corridor-svg"
            viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`}
            role="img"
            aria-label="Interactive UAE-Oman-India-Europe Multimodal Corridor Map"
          >
            <defs>
              <marker
                id="arrow-optimal"
                viewBox="0 0 10 10"
                refX="7"
                refY="5"
                markerWidth="5"
                markerHeight="5"
                orient="auto-start-reverse"
              >
                <path d="M 0 1 L 10 5 L 0 9 z" fill="#10b981" />
              </marker>
            </defs>

            {/* Layer 1: Sea backdrop */}
            <rect width={MAP_WIDTH} height={MAP_HEIGHT} className="geo-sea-bg" />

            {/* Layer 2: Natural Earth 50m/110m Land Mass (self-contained real geography) */}
            <g className="geo-land-layer" aria-hidden="true">
              {countryPaths.map((c) => (
                <path key={`fill-${c.name}`} d={c.d} className="geo-land-fill" />
              ))}
            </g>

            {/* Layer 3: Vendor-agnostic XYZ raster tiles (CARTO / Esri / OSM), gracefully hidden if offline */}
            {providerConfig.urlTemplate && (
              <g className="geo-tile-layer" aria-hidden="true">
                {visibleTiles.map(
                  (tile) =>
                    !failedTiles[tile.key] && (
                      <image
                        key={`${tileProvider}-${tile.key}`}
                        href={tile.url}
                        x={tile.left}
                        y={tile.top}
                        width={tile.size + 0.6}
                        height={tile.size + 0.6}
                        preserveAspectRatio="none"
                        onError={() =>
                          setFailedTiles((prev) => ({ ...prev, [tile.key]: true }))
                        }
                      />
                    )
                )}
              </g>
            )}

            {/* Layer 4: Crisp Vector Country Borders & Maritime Water Labels */}
            <g className="geo-borders-layer" aria-hidden="true">
              {countryPaths.map((c) => (
                <path key={`stroke-${c.name}`} d={c.d} className="geo-country-stroke" />
              ))}
              {GEO_LABELS.map((lbl) => {
                if (lbl.minZoom && camera.zoom < lbl.minZoom) return null;
                const [lx, ly] = projectLonLat(lbl.lon, lbl.lat, camera);
                if (lx < 15 || lx > MAP_WIDTH - 15 || ly < 15 || ly > MAP_HEIGHT - 15) return null;
                return (
                  <text
                    key={lbl.text}
                    x={lx}
                    y={ly}
                    className={lbl.kind === 'sea' ? 'geo-sea-label' : 'geo-country-label'}
                  >
                    {lbl.text}
                  </text>
                );
              })}
            </g>

            {/* Layer 5: Semantic Multimodal Corridor Edges */}
            <g className="corridor-edges-layer">
              {projectedEdges.map(({ edge, routeState, d, mid, modeLabel }) => (
                <g key={edge.id} data-edge-id={edge.id} data-route-state={routeState}>
                  <path
                    d={d}
                    className={`corridor-edge corridor-edge--${routeState} corridor-edge--mode-${edge.mode}`}
                    markerEnd={routeState === 'optimal' ? 'url(#arrow-optimal)' : undefined}
                  />
                  {routeState === 'optimal' &&
                    mid[0] > 40 &&
                    mid[0] < MAP_WIDTH - 40 &&
                    mid[1] > 28 &&
                    mid[1] < MAP_HEIGHT - 28 && (
                      <g transform={`translate(${mid[0]}, ${mid[1]})`} className="edge-mode-pill">
                        <rect x={-30} y={-9} width={60} height={18} rx={4} />
                        <text textAnchor="middle" dominantBaseline="central">
                          {modeLabel}
                        </text>
                      </g>
                    )}
                </g>
              ))}
            </g>

            {/* Layer 6: Strait of Hormuz Choke Geofence */}
            {hormuzDelayHours > 0 && (
              <g
                className="hormuz-choke-group"
                transform={`translate(${hormuzPoint[0]}, ${hormuzPoint[1]})`}
                data-choke="hormuz"
              >
                <circle r={Math.min(54, 24 + hormuzDelayHours * 0.22)} className="hormuz-choke-ring" />
                <circle r={5} className="hormuz-choke-core" />
                <g transform="translate(12, -22)">
                  <rect x={0} y={-10} width={132} height={20} rx={4} className="choke-badge-bg" />
                  <text x={8} y={0} dominantBaseline="central" className="choke-badge-text">
                    HORMUZ CHOKE +{hormuzDelayHours}h
                  </text>
                </g>
              </g>
            )}

            {/* Layer 7: Corridor Hubs + Anti-Collision Leader-Line Callouts */}
            <g className="corridor-nodes-layer">
              {projectedNodes.map(({ node, x, y, inView, isOptimal, isCongested, offset, showCallout }) => {
                if (!inView) return null;
                const lx = Math.max(76, Math.min(MAP_WIDTH - 76, x + offset.dx));
                const ly = Math.max(24, Math.min(MAP_HEIGHT - 24, y + offset.dy));
                const boxWidth = 122;
                const boxX =
                  offset.anchor === 'end'
                    ? lx - boxWidth
                    : offset.anchor === 'middle'
                      ? lx - boxWidth / 2
                      : lx;

                return (
                  <g
                    key={node.id}
                    data-node-id={node.id}
                    data-node-optimal={isOptimal ? 'true' : 'false'}
                    className={`corridor-node ${isOptimal ? 'is-optimal' : ''} ${
                      isCongested ? 'is-congested' : ''
                    } ${selectedNodeId === node.id ? 'is-selected' : ''}`}
                    onClick={() =>
                      setSelectedNodeId((prev) => (prev === node.id ? null : node.id))
                    }
                    role="button"
                    tabIndex={0}
                    aria-label={`${node.code} ${node.name}`}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        setSelectedNodeId((prev) => (prev === node.id ? null : node.id));
                      }
                    }}
                  >
                    <title>{`${node.code} — ${node.name} (${node.role})`}</title>
                    {showCallout && (
                      <line x1={x} y1={y} x2={lx} y2={ly} className="node-leader-line" />
                    )}
                    <circle cx={x} cy={y} r={isOptimal ? 6.5 : 4.5} className="node-dot" />
                    {isOptimal && <circle cx={x} cy={y} r={11} className="node-halo" />}

                    {showCallout && (
                      <g transform={`translate(${boxX}, ${ly - 15})`} className="node-callout">
                        <rect width={boxWidth} height={30} rx={5} className="node-callout-bg" />
                        <text x={8} y={11} className="node-callout-code">
                          {node.code}
                          {isCongested ? ' · DELAY' : isOptimal ? ' · ACTIVE' : ''}
                        </text>
                        <text x={8} y={23} className="node-callout-name">
                          {offset.shortName}
                        </text>
                      </g>
                    )}
                  </g>
                );
              })}
            </g>
          </svg>

          {selectedNode && (
            <div className="node-inspector-hud" role="status">
              <div className="node-inspector-head">
                <strong>
                  {selectedNode.code} · {selectedNode.name}
                </strong>
                <button
                  type="button"
                  className="node-inspector-close"
                  onClick={() => setSelectedNodeId(null)}
                  aria-label="Close hub details"
                >
                  ×
                </button>
              </div>
              <div className="node-inspector-meta">
                <span>{selectedNode.role}</span>
                <span className="mono">Zone: {selectedNode.customs_zone}</span>
                <span className="mono">
                  {selectedNode.lat.toFixed(2)}°N, {selectedNode.lon.toFixed(2)}°E
                </span>
              </div>
            </div>
          )}

          <div className="map-footer-bar">
            {solution ? (
              <div className="active-vector-summary">
                <span className="vector-tag">Active Verified Route</span>
                <span className="mono vector-seq">
                  {solution.optimal_route.node_sequence.join(' → ')}
                </span>
              </div>
            ) : (
              <span className="map-hint">Click any hub for customs zone coordinates</span>
            )}
            <span className="map-attribution">{providerConfig.attribution}</span>
          </div>
        </div>
      ) : (
        <div
          className="schematic-stage"
          data-testid="corridor-schematic-view"
          aria-label="LLM-Inspectable Corridor Topology Schematic"
        >
          <div className="schematic-grid">
            <div className="schematic-col">
              <div className="schematic-col-title">Origin Gateway</div>
              <div className="schematic-node optimal">
                <strong>INNSA</strong>
                <span>Nhava Sheva (JNPT)</span>
              </div>
            </div>

            <div className="schematic-arrow">→</div>

            <div className="schematic-col">
              <div className="schematic-col-title">Hormuz Bypass vs Direct</div>
              {(['AEFJR', 'OMSOH', 'OMSLL', 'AEJEA'] as const).map((id) => {
                const n = nodeById.get(id);
                const isOpt = optimalNodeSet.has(id);
                const isBlocked = id === 'AEJEA' && !isOpt && hormuzDelayHours > 0;
                return (
                  <div
                    key={id}
                    className={`schematic-node ${isOpt ? 'optimal' : isBlocked ? 'blocked' : ''}`}
                  >
                    <strong>{id}</strong>
                    <span>{n?.name ?? id}</span>
                  </div>
                );
              })}
            </div>

            <div className="schematic-arrow">→</div>

            <div className="schematic-col">
              <div className="schematic-col-title">Bonded Land / Air Transfer</div>
              {(['AEWAJ', 'AEKHL', 'AEAUH'] as const).map((id) => {
                const n = nodeById.get(id);
                const isOpt = optimalNodeSet.has(id);
                return (
                  <div key={id} className={`schematic-node ${isOpt ? 'optimal' : ''}`}>
                    <strong>{id}</strong>
                    <span>{n?.name ?? id}</span>
                  </div>
                );
              })}
            </div>

            <div className="schematic-arrow">→</div>

            <div className="schematic-col">
              <div className="schematic-col-title">EU Consignee Hub</div>
              <div className="schematic-node optimal">
                <strong>EUFRA</strong>
                <span>Frankfurt / Rotterdam</span>
              </div>
            </div>
          </div>

          {solution && (
            <pre className="schematic-ascii mono" aria-label="Structured corridor vector summary">
              {[
                `ACTIVE VECTOR : ${solution.optimal_route.node_sequence.join(' -> ')} (${solution.optimal_route.z3_status})`,
                `MODES         : ${solution.optimal_route.modes.join(' -> ')}`,
                `HORMUZ DELAY  : +${hormuzDelayHours}h | JEBEL ALI CONGESTION: +${jebelAliDelayHours}h`,
                `CANDIDATES    : ${solution.candidates
                  .map((c) => `${c.route_id}[${c.z3_status}:${c.total_hours}h/$${c.total_economic_cost_usd}]`)
                  .join(' | ')}`,
              ].join('\n')}
            </pre>
          )}
        </div>
      )}
    </section>
  );
}
