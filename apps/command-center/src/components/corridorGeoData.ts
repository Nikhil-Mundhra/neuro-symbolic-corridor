import landCountriesRaw from './corridorLandData.json';

export const MAP_WIDTH = 960;
export const MAP_HEIGHT = 430;
export const TILE_SIZE = 256;

export type TileProviderId = 'esri-dark' | 'esri-light' | 'esri-satellite' | 'osm' | 'vector';
export type ViewPresetId = 'gulf' | 'arabian' | 'eurasia';
export type MapRenderMode = 'geo' | 'schematic';

export interface TileProviderConfig {
  id: TileProviderId;
  label: string;
  urlTemplate: string | null;
  attribution: string;
  isDark: boolean;
}

/**
 * Vendor-agnostic XYZ tile provider registry (zero proprietary SDK lock-in).
 * Uses watermark-free public ArcGIS/Esri & OpenStreetMap endpoints plus a
 * self-contained Natural Earth vector fallback ('vector').
 */
export const TILE_PROVIDERS: Record<TileProviderId, TileProviderConfig> = {
  'esri-dark': {
    id: 'esri-dark',
    label: 'Esri Dark Gray',
    urlTemplate:
      'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Tiles © Esri, HERE, Garmin, OpenStreetMap',
    isDark: true,
  },
  'esri-light': {
    id: 'esri-light',
    label: 'Esri Light Gray',
    urlTemplate:
      'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Tiles © Esri, HERE, Garmin, OpenStreetMap',
    isDark: false,
  },
  'esri-satellite': {
    id: 'esri-satellite',
    label: 'Esri Satellite',
    urlTemplate:
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Tiles © Esri, Earthstar Geographics',
    isDark: true,
  },
  osm: {
    id: 'osm',
    label: 'OpenStreetMap',
    urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '© OpenStreetMap contributors',
    isDark: false,
  },
  vector: {
    id: 'vector',
    label: 'Offline Vector',
    urlTemplate: null,
    attribution: 'Natural Earth 50m/110m Vector Geography',
    isDark: true,
  },
};

export interface CameraPreset {
  id: ViewPresetId;
  label: string;
  centerLon: number;
  centerLat: number;
  zoom: number;
}

export const VIEW_PRESETS: Record<ViewPresetId, CameraPreset> = {
  gulf: {
    id: 'gulf',
    label: 'Gulf / Oman Focus',
    centerLon: 55.65,
    centerLat: 25.35,
    zoom: 7.3,
  },
  arabian: {
    id: 'arabian',
    label: 'Arabian Sea & Hormuz',
    centerLon: 62.0,
    centerLat: 21.8,
    zoom: 4.85,
  },
  eurasia: {
    id: 'eurasia',
    label: 'India → UAE → EU Corridor',
    centerLon: 42.5,
    centerLat: 33.5,
    zoom: 3.45,
  },
};

export interface CountryPolygon {
  name: string;
  rings: [number, number][][];
  gulf: boolean;
}

export const CORRIDOR_COUNTRIES = landCountriesRaw as unknown as CountryPolygon[];

export interface GeoLabel {
  text: string;
  lon: number;
  lat: number;
  kind: 'sea' | 'country';
  minZoom?: number;
}

export const GEO_LABELS: GeoLabel[] = [
  { text: 'PERSIAN GULF', lon: 52.3, lat: 26.5, kind: 'sea' },
  { text: 'GULF OF OMAN', lon: 58.3, lat: 24.75, kind: 'sea' },
  { text: 'ARABIAN SEA', lon: 63.0, lat: 16.5, kind: 'sea' },
  { text: 'RED SEA', lon: 38.6, lat: 20.5, kind: 'sea' },
  { text: 'MEDITERRANEAN SEA', lon: 18.0, lat: 35.4, kind: 'sea' },
  { text: 'U A E', lon: 54.0, lat: 23.6, kind: 'country', minZoom: 4.5 },
  { text: 'OMAN', lon: 57.1, lat: 22.1, kind: 'country', minZoom: 4.5 },
  { text: 'IRAN', lon: 54.2, lat: 28.4, kind: 'country' },
  { text: 'SAUDI ARABIA', lon: 46.0, lat: 24.0, kind: 'country' },
  { text: 'INDIA', lon: 76.5, lat: 21.0, kind: 'country' },
];

export interface CalloutOffset {
  dx: number;
  dy: number;
  anchor: 'start' | 'middle' | 'end';
  shortName: string;
}

/**
 * Deterministic radial label layout for the clustered UAE/Oman corridor hubs so
 * port codes and status tags never collide at Gulf or Eurasian zoom levels.
 */
export const NODE_CALLOUT_LAYOUT: Record<
  ViewPresetId,
  Record<string, CalloutOffset>
> = {
  gulf: {
    AEFJR: { dx: 76, dy: -46, anchor: 'start', shortName: 'Fujairah' },
    OMSOH: { dx: 96, dy: 18, anchor: 'start', shortName: 'Sohar FZ' },
    AEWAJ: { dx: -6, dy: 72, anchor: 'middle', shortName: 'Al Wajajah Gate' },
    AEJEA: { dx: -26, dy: -66, anchor: 'end', shortName: 'Jebel Ali' },
    AEDWC: { dx: -14, dy: 72, anchor: 'end', shortName: 'Al Maktoum (DWC)' },
    AEKHL: { dx: -92, dy: -36, anchor: 'end', shortName: 'Khalifa KIZAD' },
    AEAUH: { dx: -92, dy: 24, anchor: 'end', shortName: 'Zayed Air (AUH)' },
    INNSA: { dx: -14, dy: -16, anchor: 'end', shortName: 'Nhava Sheva' },
    OMSLL: { dx: -14, dy: -16, anchor: 'end', shortName: 'Salalah' },
    EUFRA: { dx: 14, dy: 18, anchor: 'start', shortName: 'EU Hub' },
  },
  arabian: {
    INNSA: { dx: -16, dy: -18, anchor: 'end', shortName: 'JNPT Mumbai' },
    OMSLL: { dx: -18, dy: 24, anchor: 'end', shortName: 'Salalah' },
    OMSOH: { dx: 72, dy: 28, anchor: 'start', shortName: 'Sohar' },
    AEFJR: { dx: 68, dy: -32, anchor: 'start', shortName: 'Fujairah' },
    AEWAJ: { dx: 66, dy: 58, anchor: 'start', shortName: 'Al Wajajah' },
    AEJEA: { dx: -52, dy: -44, anchor: 'end', shortName: 'Jebel Ali' },
    AEKHL: { dx: -76, dy: -6, anchor: 'end', shortName: 'Khalifa' },
    AEAUH: { dx: -72, dy: 38, anchor: 'end', shortName: 'Zayed Air' },
    AEDWC: { dx: -44, dy: 64, anchor: 'end', shortName: 'DWC' },
    EUFRA: { dx: 16, dy: 16, anchor: 'start', shortName: 'EU Hub' },
  },
  eurasia: {
    INNSA: { dx: 14, dy: 24, anchor: 'start', shortName: 'JNPT Mumbai' },
    OMSLL: { dx: -18, dy: 26, anchor: 'end', shortName: 'Salalah' },
    OMSOH: { dx: 82, dy: 26, anchor: 'start', shortName: 'Sohar' },
    AEFJR: { dx: 84, dy: -28, anchor: 'start', shortName: 'Fujairah' },
    AEWAJ: { dx: 80, dy: 58, anchor: 'start', shortName: 'Al Wajajah' },
    AEJEA: { dx: -70, dy: -36, anchor: 'end', shortName: 'Jebel Ali' },
    AEKHL: { dx: -82, dy: 2, anchor: 'end', shortName: 'Khalifa' },
    AEAUH: { dx: -76, dy: 38, anchor: 'end', shortName: 'Zayed Air' },
    AEDWC: { dx: -48, dy: 66, anchor: 'end', shortName: 'DWC' },
    EUFRA: { dx: 16, dy: 12, anchor: 'start', shortName: 'Frankfurt / Rotterdam' },
  },
};

export interface CameraState {
  centerLon: number;
  centerLat: number;
  zoom: number;
  panX: number;
  panY: number;
}

export function lonLatToWorldNorm(lon: number, lat: number): [number, number] {
  const clampedLat = Math.max(-85.0511, Math.min(85.0511, lat));
  const x = (lon + 180) / 360;
  const sinLat = Math.sin((clampedLat * Math.PI) / 180);
  const y = 0.5 - Math.log((1 + sinLat) / (1 - sinLat)) / (4 * Math.PI);
  return [x, y];
}

export function projectLonLat(
  lon: number,
  lat: number,
  camera: CameraState,
  width = MAP_WIDTH,
  height = MAP_HEIGHT
): [number, number] {
  const scale = TILE_SIZE * Math.pow(2, camera.zoom);
  const [cx, cy] = lonLatToWorldNorm(camera.centerLon, camera.centerLat);
  const [wx, wy] = lonLatToWorldNorm(lon, lat);
  return [
    width / 2 + (wx - cx) * scale + camera.panX,
    height / 2 + (wy - cy) * scale + camera.panY,
  ];
}

export interface TileDescriptor {
  key: string;
  url: string;
  left: number;
  top: number;
  size: number;
}

export function getVisibleTiles(
  camera: CameraState,
  urlTemplate: string | null,
  width = MAP_WIDTH,
  height = MAP_HEIGHT
): TileDescriptor[] {
  if (!urlTemplate) return [];

  const zInt = Math.max(2, Math.min(11, Math.floor(camera.zoom)));
  const n = Math.pow(2, zInt);
  const worldScale = TILE_SIZE * Math.pow(2, camera.zoom);
  const tilePx = worldScale / n;
  const [cx, cy] = lonLatToWorldNorm(camera.centerLon, camera.centerLat);

  // Origin of world (0, 0) in viewport pixels
  const originX = width / 2 - cx * worldScale + camera.panX;
  const originY = height / 2 - cy * worldScale + camera.panY;

  const minTx = Math.max(0, Math.floor(-originX / tilePx));
  const maxTx = Math.min(n - 1, Math.floor((width - originX) / tilePx));
  const minTy = Math.max(0, Math.floor(-originY / tilePx));
  const maxTy = Math.min(n - 1, Math.floor((height - originY) / tilePx));

  const tiles: TileDescriptor[] = [];
  for (let ty = minTy; ty <= maxTy; ty++) {
    for (let tx = minTx; tx <= maxTx; tx++) {
      const url = urlTemplate
        .replace('{z}', String(zInt))
        .replace('{x}', String(tx))
        .replace('{y}', String(ty));
      tiles.push({
        key: `${zInt}/${tx}/${ty}`,
        url,
        left: originX + tx * tilePx,
        top: originY + ty * tilePx,
        size: tilePx,
      });
    }
  }
  return tiles;
}

export function buildWaypointSvgPath(
  points: [number, number][],
  camera: CameraState
): string {
  if (points.length === 0) return '';
  return points
    .map(([lon, lat], idx) => {
      const [x, y] = projectLonLat(lon, lat, camera);
      return `${idx === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
}

export function buildCurvedArcPath(
  from: [number, number],
  to: [number, number],
  camera: CameraState,
  liftFactor = 0.22
): { d: string; midpoint: [number, number] } {
  const [x1, y1] = projectLonLat(from[0], from[1], camera);
  const [x2, y2] = projectLonLat(to[0], to[1], camera);
  const dist = Math.hypot(x2 - x1, y2 - y1);
  const lift = Math.min(95, dist * liftFactor);
  const cx = (x1 + x2) / 2;
  const cy = (y1 + y2) / 2 - lift;
  const midX = 0.25 * x1 + 0.5 * cx + 0.25 * x2;
  const midY = 0.25 * y1 + 0.5 * cy + 0.25 * y2;
  return {
    d: `M${x1.toFixed(1)},${y1.toFixed(1)} Q${cx.toFixed(1)},${cy.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`,
    midpoint: [midX, midY],
  };
}
