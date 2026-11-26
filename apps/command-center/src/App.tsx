import { type KeyboardEvent, useCallback, useEffect, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  Compass,
  Cpu,
  FileJson,
  FileText,
  Layers,
  Play,
  Radio,
  RefreshCw,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Terminal,
  Thermometer,
} from 'lucide-react';
import { CorridorMap } from './components/CorridorMap';
import { CorridorHomepage, type HomepageViewMode } from './components/CorridorHomepage';
import { CorridorBrandMark } from './components/CorridorBrandMark';
import { FALLBACK_SCENARIOS, FALLBACK_TOPOLOGY } from './data/fallbackData';
import type {
  CorridorTopology,
  DisruptionState,
  ScenarioPreset,
  ShipmentRequest,
  ShipmentSpec,
  TelemetrySnapshot,
  ValidationHold,
  WorkflowRun,
} from './types';

function formatUSD(v: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(v);
}

function formatAED(v: number): string {
  return `AED ${new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(v)}`;
}

type WorkspaceTabId = 'dispatch' | 'scenarios' | 'routes' | 'proofs' | 'diagnostics';

const WORKSPACE_TABS: readonly {
  id: WorkspaceTabId;
  label: string;
  hint: string;
}[] = [
  { id: 'dispatch', label: 'Dispatch & Map', hint: 'Map & shock levers' },
  { id: 'scenarios', label: 'Corridor Scenarios', hint: 'Cargo & SLA presets' },
  { id: 'routes', label: 'Route Matrix', hint: 'MILP cost table' },
  { id: 'proofs', label: 'Z3 Formal Proofs', hint: 'SMT audit checks' },
  { id: 'diagnostics', label: 'BoL & Diagnostics', hint: 'Schema & latency' },
];

function getScenarioDomainLabel(preset: ScenarioPreset): string {
  if (preset.shipment.is_temp_sensitive) return 'GDP Cold-Chain';
  if (preset.id.includes('ev') || preset.shipment.hs_code.startsWith('8708')) return 'Automotive JIT';
  return 'Industrial Bulk';
}

function buildCanonicalSamplePayload(mode: 'valid' | 'incomplete'): Record<string, unknown> {
  const base: Record<string, unknown> = {
    internal_request_id: mode === 'valid' ? 'REQ-PL-2026-0001' : 'REQ-PL-2026-HOLD',
    transport_mode: 'MULTIMODAL_SEA_AIR',
    transport_document_ref: 'MAEU-INNSA-992841',
    document_status: 'ISSU',
    customs_regime: 'SEA_AIR_TRANSSHIPMENT',
    issue_date: '2026-11-24',
    incoterms_code: 'CIF',
    mofaic_attested_invoice: true,
    mofaic_attestation_ref: 'MOFAIC-2026-88412',
    parties: [
      {
        role: 'SHP',
        legal_name: 'BioGenix Therapeutics Pvt Ltd',
        address_line: 'Plot 42 MIDC Taloja, Navi Mumbai',
        country_code: 'IN',
      },
      {
        role: 'CNE',
        legal_name: 'RheinPharma Distribution GmbH',
        address_line: 'Cargo City South Bldg 532, Frankfurt',
        country_code: 'DE',
        uae_trn: mode === 'valid' ? '100456789012345' : null,
        uae_trn_fta_verified: mode === 'valid',
        dubai_customs_code: mode === 'valid' ? 'AE-1234567' : null,
        eori_number: 'DE8839201948271',
      },
    ],
    legs: [
      {
        leg_sequence: 1,
        mode: 'OCEAN',
        origin_locode: 'INNSA',
        destination_locode: 'AEFJR',
        carrier_code: 'MAEU',
        voyage_or_flight_number: '418W',
        scheduled_departure_utc: '2026-11-24T06:00:00Z',
        scheduled_arrival_utc: '2026-11-27T14:00:00Z',
      },
      {
        leg_sequence: 2,
        mode: 'AIR',
        origin_locode: 'AEAUH',
        destination_locode: 'EUFRA',
        carrier_code: 'EY',
        voyage_or_flight_number: 'EY901',
        scheduled_departure_utc: '2026-11-27T21:00:00Z',
        scheduled_arrival_utc: '2026-11-28T04:30:00Z',
      },
    ],
    consignment_items: [
      {
        item_id: 'ITEM-01',
        goods_description: 'Monoclonal Antibodies Biologics (2-8C Active Reefer)',
        hs_code_gcc12: mode === 'valid' ? '300215000010' : null,
        hs_code_wco6: '300215',
        quantity: '400',
        package_type: 'CTN',
        gross_weight_kg: '12400.00',
        net_weight_kg: '11200.00',
        customs_value_amount: '1850000.00',
        customs_value_currency: 'USD',
        origin: {
          country_of_origin: 'IN',
          certificate_of_origin_no: mode === 'valid' ? 'IN-UAE-CEPA-2026-9910' : null,
          preferential_cepa_claimed: true,
          cepa_agreement_code: 'IN-UAE-CEPA',
          cepa_value_add_pct: mode === 'valid' ? '48.5' : null,
        },
        is_reefer: true,
        reefer_spec: {
          min_temp_c: '2.0',
          max_temp_c: '8.0',
          setpoint_temp_c: '4.0',
        },
        is_dangerous_goods: false,
        regulatory_permits: ['EU-GDP-2013-C343', 'UAE-MOHAP-BIOLOGICS'],
      },
    ],
    utilized_equipments: [
      {
        equipment_reference: 'MSKU9070323',
        iso_size_type_code: '45R1',
        seal_numbers: ['ETIR-GCC-884210'],
      },
    ],
  };
  return { shipment: base };
}

export default function App() {
  const [topology, setTopology] = useState<CorridorTopology>(FALLBACK_TOPOLOGY);
  const [scenarios, setScenarios] = useState<ScenarioPreset[]>(FALLBACK_SCENARIOS);
  const [activeScenarioId, setActiveScenarioId] = useState<string>(FALLBACK_SCENARIOS[0].id);
  const [shipment, setShipment] = useState<ShipmentSpec>(FALLBACK_SCENARIOS[0].shipment);
  const [disruption, setDisruption] = useState<DisruptionState>(
    FALLBACK_SCENARIOS[0].default_disruption
  );
  const [paretoAlpha, setParetoAlpha] = useState<number>(0.55);
  const [rawBolText, setRawBolText] = useState<string>(FALLBACK_SCENARIOS[0].raw_bol_text);

  const [workflow, setWorkflow] = useState<WorkflowRun | null>(null);
  const [solving, setSolving] = useState<boolean>(false);
  const [approving, setApproving] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [sseConnected, setSseConnected] = useState<boolean>(false);
  const [telemetry, setTelemetry] = useState<TelemetrySnapshot | null>(null);
  const [autoSyncTelemetry, setAutoSyncTelemetry] = useState<boolean>(false);
  const [validatingGate, setValidatingGate] = useState<boolean>(false);
  const [gateResult, setGateResult] = useState<
    | { kind: 'verified'; shipment: ShipmentRequest }
    | { kind: 'hold'; hold: ValidationHold }
    | { kind: 'error'; message: string }
    | null
  >(null);
  const [modalTab, setModalTab] = useState<'customs' | 'z3'>('customs');
  const [activeTab, setActiveTab] = useState<WorkspaceTabId>('dispatch');
  const tabRefs = useRef<Partial<Record<WorkspaceTabId, HTMLButtonElement | null>>>({});
  const shipmentRef = useRef<ShipmentSpec>(shipment);
  const paretoAlphaRef = useRef<number>(paretoAlpha);
  const autoSyncTelemetryRef = useRef<boolean>(autoSyncTelemetry);

  useEffect(() => {
    shipmentRef.current = shipment;
  }, [shipment]);

  useEffect(() => {
    paretoAlphaRef.current = paretoAlpha;
  }, [paretoAlpha]);

  useEffect(() => {
    autoSyncTelemetryRef.current = autoSyncTelemetry;
  }, [autoSyncTelemetry]);
  const [viewMode, setViewMode] = useState<HomepageViewMode>(() =>
    typeof window !== 'undefined' && window.location.pathname.startsWith('/twin')
      ? 'console'
      : 'full'
  );

  const handleToggleViewMode = useCallback((mode: HomepageViewMode) => {
    setViewMode(mode);
    if (typeof window !== 'undefined') {
      const targetPath = mode === 'console' ? '/twin' : '/';
      if (window.location.pathname !== targetPath) {
        window.history?.pushState?.({}, '', targetPath);
      }
      window.scrollTo?.(0, 0);
    }
  }, []);

  useEffect(() => {
    const onPopState = () => {
      setViewMode(window.location.pathname.startsWith('/twin') ? 'console' : 'full');
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const hormuzSliderRef = useRef<HTMLInputElement | null>(null);
  const jebelSliderRef = useRef<HTMLInputElement | null>(null);
  const alphaSliderRef = useRef<HTMLInputElement | null>(null);

  const syncSliderProgress = useCallback(
    (el: HTMLInputElement | null, value: number, min: number, max: number) => {
      if (!el || CSS.supports('accent-color', '#000')) return;
      const pct = ((value - min) / (max - min)) * 100;
      el.style.setProperty('--progress', `${pct}%`);
    },
    []
  );

  useEffect(() => {
    syncSliderProgress(hormuzSliderRef.current, disruption.hormuz_delay_hours, 0, 120);
    syncSliderProgress(jebelSliderRef.current, disruption.jebel_ali_congestion_hours, 0, 72);
    syncSliderProgress(alphaSliderRef.current, paretoAlpha, 0, 1);
  }, [
    disruption.hormuz_delay_hours,
    disruption.jebel_ali_congestion_hours,
    paretoAlpha,
    syncSliderProgress,
  ]);

  const runSolve = useCallback(
    async (spec: ShipmentSpec, dis: DisruptionState, alpha: number) => {
      setSolving(true);
      setErrorMsg(null);
      try {
        const res = await fetch('/api/v1/solve', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            shipment: spec,
            disruption: dis,
            pareto_alpha: alpha,
          }),
        });
        if (!res.ok) {
          let detail = `Gateway returned ${res.status}`;
          try {
            const errJson = (await res.json()) as { detail?: string; error?: string };
            if (errJson.detail) detail = errJson.detail;
            else if (errJson.error) detail = errJson.error;
          } catch {
            // Keep HTTP status fallback when response body is not JSON
          }
          throw new Error(detail);
        }
        const data = (await res.json()) as WorkflowRun;
        setWorkflow(data);
      } catch (err) {
        setErrorMsg(err instanceof Error ? err.message : 'Failed to reach gateway-go');
      } finally {
        setSolving(false);
      }
    },
    []
  );

  // Load topology, scenarios & live telemetry snapshot from gateway-go on boot
  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      try {
        const [topoRes, scenRes, telRes] = await Promise.all([
          fetch('/api/v1/corridor/topology'),
          fetch('/api/v1/scenarios'),
          fetch('/api/v1/telemetry/state').catch(() => null),
        ]);
        if (telRes && telRes.ok) {
          const telData = (await telRes.json()) as TelemetrySnapshot;
          if (!cancelled && telData && telData.disruption) {
            setTelemetry(telData);
          }
        }
        if (topoRes.ok) {
          const topoData = (await topoRes.json()) as Partial<CorridorTopology>;
          if (!cancelled && Array.isArray(topoData.nodes) && Array.isArray(topoData.edges)) {
            setTopology({ nodes: topoData.nodes, edges: topoData.edges });
          }
        }
        if (scenRes.ok) {
          const scenData = (await scenRes.json()) as ScenarioPreset[];
          if (!cancelled && scenData.length > 0) {
            setScenarios(scenData);
            setActiveScenarioId(scenData[0].id);
            setShipment(scenData[0].shipment);
            setDisruption(scenData[0].default_disruption);
            setRawBolText(scenData[0].raw_bol_text);
            void runSolve(scenData[0].shipment, scenData[0].default_disruption, 0.55);
            return;
          }
        }
      } catch {
        // Ignore bootstrap error; runSolve below will surface gateway connectivity status
      }
      if (!cancelled) {
        void runSolve(FALLBACK_SCENARIOS[0].shipment, FALLBACK_SCENARIOS[0].default_disruption, 0.55);
      }
    }
    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [runSolve]);

  // Subscribe to SSE live workflow updates from Go gateway
  useEffect(() => {
    const es = new EventSource('/api/v1/events');
    es.addEventListener('connected', () => setSseConnected(true));
    es.addEventListener('workflow_update', (evt) => {
      setSseConnected(true);
      try {
        const data = JSON.parse((evt as MessageEvent<string>).data) as {
          workflow_id?: string;
          status?: WorkflowRun['status'];
        };
        if (data.workflow_id && data.status) {
          setWorkflow((prev) =>
            prev && prev.workflow_id === data.workflow_id && prev.status !== data.status
              ? { ...prev, status: data.status! }
              : prev
          );
        }
      } catch {
        // Ignore malformed SSE payload
      }
    });
    es.addEventListener('telemetry_update', (evt) => {
      setSseConnected(true);
      try {
        const data = JSON.parse((evt as MessageEvent<string>).data) as {
          active_sources?: string[];
          event_count?: number;
          disruption?: DisruptionState;
          edge_overrides?: TelemetrySnapshot['edge_overrides'];
          timestamp?: string;
        };
        setTelemetry((prev) => {
          const nextDisruption = data.disruption ?? prev?.disruption ?? FALLBACK_SCENARIOS[0].default_disruption;
          return {
            disruption: nextDisruption,
            edge_overrides: data.edge_overrides ?? prev?.edge_overrides ?? {},
            last_updated_utc: data.timestamp ?? new Date().toISOString(),
            active_sources: data.active_sources ?? prev?.active_sources ?? [],
            event_count: data.event_count ?? prev?.event_count ?? 0,
          };
        });
        if (autoSyncTelemetryRef.current && data.disruption) {
          setDisruption(data.disruption);
          void runSolve(shipmentRef.current, data.disruption, paretoAlphaRef.current);
        }
      } catch {
        // Ignore malformed telemetry SSE payload
      }
    });
    es.onerror = () => setSseConnected(false);
    return () => {
      es.close();
    };
  }, [runSolve]);

  // Configure native <dialog> returnValue reset and light-dismiss fallback for browsers lacking closedBy
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    const onClose = () => {
      dialog.returnValue = '';
    };
    dialog.addEventListener('close', onClose);

    if (!('closedBy' in HTMLDialogElement.prototype)) {
      let pressedOutside = false;
      const outside = (e: PointerEvent) => {
        const r = dialog.getBoundingClientRect();
        return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
      };
      const onPointerDown = (e: PointerEvent) => {
        pressedOutside = outside(e);
      };
      const onPointerUp = (e: PointerEvent) => {
        if (pressedOutside && outside(e)) dialog.close();
      };
      dialog.addEventListener('pointerdown', onPointerDown);
      dialog.addEventListener('pointerup', onPointerUp);
      return () => {
        dialog.removeEventListener('close', onClose);
        dialog.removeEventListener('pointerdown', onPointerDown);
        dialog.removeEventListener('pointerup', onPointerUp);
      };
    }

    return () => {
      dialog.removeEventListener('close', onClose);
    };
  }, []);

  const handleSelectScenario = (preset: ScenarioPreset) => {
    setActiveScenarioId(preset.id);
    setShipment(preset.shipment);
    setDisruption(preset.default_disruption);
    setRawBolText(preset.raw_bol_text);
    void runSolve(preset.shipment, preset.default_disruption, paretoAlpha);
  };

  const handleParseAndSolve = async () => {
    setSolving(true);
    setErrorMsg(null);
    try {
      const res = await fetch('/api/v1/parse-bol', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_text: rawBolText }),
      });
      if (!res.ok) throw new Error(`BoL parse failed (${res.status})`);
      const parsed = (await res.json()) as { shipment: ShipmentSpec };
      setShipment(parsed.shipment);
      await runSolve(parsed.shipment, disruption, paretoAlpha);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'BoL parsing failed');
      setSolving(false);
    }
  };

  const handleApproveDispatch = async () => {
    if (!workflow) return;
    setApproving(true);
    try {
      const res = await fetch(`/api/v1/execute/${workflow.workflow_id}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ operator: 'KIZAD / JAFZA Lead Dispatcher' }),
      });
      if (!res.ok) throw new Error(`Approval failed (${res.status})`);
      const updated = (await res.json()) as WorkflowRun;
      setWorkflow(updated);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Approval error');
    } finally {
      setApproving(false);
    }
  };

  const handleSyncLiveTelemetry = () => {
    if (!telemetry) return;
    setDisruption(telemetry.disruption);
    void runSolve(shipment, telemetry.disruption, paretoAlpha);
  };

  const handleValidateShipment = async (mode: 'valid' | 'incomplete') => {
    setValidatingGate(true);
    setGateResult(null);
    try {
      const res = await fetch('/api/v1/validate-shipment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildCanonicalSamplePayload(mode)),
      });
      const body = (await res.json()) as ShipmentRequest | ValidationHold | { error?: string };
      if (res.status === 200) {
        setGateResult({ kind: 'verified', shipment: body as ShipmentRequest });
      } else if (res.status === 422) {
        setGateResult({ kind: 'hold', hold: body as ValidationHold });
      } else {
        setGateResult({
          kind: 'error',
          message:
            (body as { error?: string }).error ?? `Compliance gate returned HTTP ${res.status}`,
        });
      }
    } catch (err) {
      setGateResult({
        kind: 'error',
        message: err instanceof Error ? err.message : 'Failed to reach compliance gate',
      });
    } finally {
      setValidatingGate(false);
    }
  };

  const openInspectorDialog = (tab: 'customs' | 'z3') => {
    setModalTab(tab);
    dialogRef.current?.showModal();
  };

  const solution = workflow?.solution ?? null;
  const usesAccentFallback = typeof CSS !== 'undefined' && !CSS.supports('accent-color', '#000');
  const activeScenario = scenarios.find((s) => s.id === activeScenarioId) ?? scenarios[0];
  const satCertCount =
    solution?.z3_certificates.filter((cert) => cert.status === 'SAT').length ?? 0;
  const totalCertCount = solution?.z3_certificates.length ?? 0;
  const panelRefs = useRef<Partial<Record<WorkspaceTabId, HTMLDivElement | null>>>({});

  useEffect(() => {
    const cleanups: (() => void)[] = [];
    for (const tab of WORKSPACE_TABS) {
      const el = panelRefs.current[tab.id];
      if (!el) continue;
      const onMatch = () => setActiveTab(tab.id);
      el.addEventListener('beforematch', onMatch);
      cleanups.push(() => el.removeEventListener('beforematch', onMatch));
    }
    return () => {
      for (const cleanup of cleanups) cleanup();
    };
  }, []);

  const handleTabKeyDown = (e: KeyboardEvent<HTMLButtonElement>, currentIndex: number) => {
    let nextIndex: number | null = null;
    if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
      nextIndex = (currentIndex + 1) % WORKSPACE_TABS.length;
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
      nextIndex = (currentIndex - 1 + WORKSPACE_TABS.length) % WORKSPACE_TABS.length;
    } else if (e.key === 'Home') {
      nextIndex = 0;
    } else if (e.key === 'End') {
      nextIndex = WORKSPACE_TABS.length - 1;
    }
    if (nextIndex === null) return;
    e.preventDefault();
    const target = WORKSPACE_TABS[nextIndex].id;
    setActiveTab(target);
    tabRefs.current[target]?.focus();
  };

  const renderTabIcon = (id: WorkspaceTabId) => {
    if (id === 'dispatch') return <Compass size={15} />;
    if (id === 'scenarios') return <Layers size={15} />;
    if (id === 'routes') return <Scale size={15} />;
    if (id === 'proofs') return <ShieldCheck size={15} />;
    return <Terminal size={15} />;
  };

  const getTabMeta = (id: WorkspaceTabId): string => {
    if (id === 'dispatch') return solution ? `Z3 ${solution.optimal_route.z3_status}` : 'Standby';
    if (id === 'scenarios') return `${scenarios.length} presets`;
    if (id === 'routes') return solution ? `${solution.candidates.length} routes` : 'Standby';
    if (id === 'proofs') return solution ? `${satCertCount}/${totalCertCount} SAT` : 'Standby';
    return workflow ? `${workflow.total_pipeline_ms.toFixed(0)} ms` : shipment.hs_code;
  };

  return (
    <CorridorHomepage
      scenarios={scenarios}
      viewMode={viewMode}
      onToggleViewMode={handleToggleViewMode}
      onLoadScenario={handleSelectScenario}
    >
      <div className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <h1>
            <CorridorBrandMark size={20} />
            ParetoLane
          </h1>
          <span className="brand-divider" aria-hidden="true">
            |
          </span>
          <p className="brand-subtitle tabular">
            <span>{shipment.bol_number}</span>
            <span>{shipment.teu_count} TEU</span>
            <span>HS {shipment.hs_code}</span>
            <span>
              {shipment.origin_node} → {shipment.destination_node}
            </span>
          </p>
        </div>

        <div className="status-cluster">
          <span className={`pill ${sseConnected ? 'ok' : 'warn'}`}>
            <Activity size={13} />
            {sseConnected ? 'SSE Live' : 'Connecting'}
          </span>
          {telemetry && (
            <span className="pill tabular" data-testid="telemetry-status-pill">
              <Radio size={13} />
              Telemetry: {telemetry.event_count} events ·{' '}
              {Object.keys(telemetry.edge_overrides ?? {}).length} overrides
            </span>
          )}
          {workflow && (
            <span className="pill tabular">
              {workflow.total_pipeline_ms.toFixed(1)} ms E2E · {workflow.workflow_id} (
              {workflow.status})
            </span>
          )}
        </div>
      </header>

      {errorMsg && (
        <div className="dispatch-banner error-banner" role="alert">
          <AlertTriangle size={15} style={{ verticalAlign: 'text-bottom', marginRight: 6 }} />
          {errorMsg.startsWith('No feasible route') ? (
            <>
              <strong>Z3 Regulatory / SLA Infeasibility:</strong> {errorMsg}
            </>
          ) : (
            <>
              Backend connection notice: {errorMsg}. Ensure <code>solver-py</code> (:8001) and{' '}
              <code>gateway-go</code> (:8080) are running.
            </>
          )}
        </div>
      )}

      <main className="twin-workstation">
        <aside className="side-rail" aria-label="Digital Twin Navigation">
          <div
            role="tablist"
            aria-orientation="vertical"
            aria-label="Corridor workstation views"
            className="side-tablist"
          >
            {WORKSPACE_TABS.map((tab, idx) => {
              const isSelected = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  ref={(el) => {
                    tabRefs.current[tab.id] = el;
                  }}
                  type="button"
                  role="tab"
                  id={`tab-${tab.id}`}
                  aria-selected={isSelected}
                  tabIndex={isSelected ? 0 : -1}
                  className="side-tab"
                  onClick={() => setActiveTab(tab.id)}
                  onKeyDown={(e) => handleTabKeyDown(e, idx)}
                >
                  <span className="side-tab-icon" aria-hidden="true">
                    {renderTabIcon(tab.id)}
                  </span>
                  <span className="side-tab-copy">
                    <span className="side-tab-label">{tab.label}</span>
                    <span className="side-tab-hint">{tab.hint}</span>
                  </span>
                  <span className="side-tab-meta tabular">{getTabMeta(tab.id)}</span>
                </button>
              );
            })}
          </div>

          {activeScenario && (
            <div className="rail-shipment-digest">
              <div className="rail-digest-head">
                <span className="section-label">Active Manifest</span>
                <button
                  type="button"
                  className="rail-link-btn"
                  onClick={() => setActiveTab('scenarios')}
                >
                  Switch <ArrowRight size={12} />
                </button>
              </div>
              <strong className="rail-digest-title">{activeScenario.title}</strong>
              <dl className="rail-digest-metrics tabular">
                <div>
                  <dt>HS Code</dt>
                  <dd className="mono">{shipment.hs_code}</dd>
                </div>
                <div>
                  <dt>Volume</dt>
                  <dd>{shipment.teu_count} TEU</dd>
                </div>
                <div>
                  <dt>Max SLA</dt>
                  <dd>{shipment.max_transit_hours.toFixed(0)} h</dd>
                </div>
                <div>
                  <dt>Ceiling</dt>
                  <dd>{shipment.max_temp_c.toFixed(1)} °C</dd>
                </div>
              </dl>
            </div>
          )}
        </aside>

        <section className="workspace-stage">
          {/* TAB 1: DISPATCH & MAP */}
          <div
            ref={(el) => {
              panelRefs.current.dispatch = el;
            }}
            id="panel-dispatch"
            role="tabpanel"
            aria-labelledby="tab-dispatch"
            tabIndex={activeTab === 'dispatch' ? 0 : undefined}
            {...(activeTab !== 'dispatch' ? { hidden: 'until-found' as unknown as boolean } : {})}
          >
            <div className="workspace-panel-inner">
              <div className="scenario-strip" aria-label="Quick Corridor Scenario Switcher">
                <div className="scenario-strip-label">
                  <span>Scenario Preset</span>
                  <button
                    type="button"
                    className="rail-link-btn"
                    onClick={() => setActiveTab('scenarios')}
                  >
                    Compare All {scenarios.length} <ArrowRight size={12} />
                  </button>
                </div>
                <div className="scenario-pill-row">
                  {scenarios.map((preset) => {
                    const active = activeScenarioId === preset.id;
                    return (
                      <button
                        key={preset.id}
                        type="button"
                        aria-pressed={active}
                        className={`scenario-pill ${active ? 'active' : ''}`}
                        onClick={() => handleSelectScenario(preset)}
                      >
                        <span className="scenario-pill-title">{preset.title}</span>
                        <span className="scenario-pill-specs tabular">
                          <span>{getScenarioDomainLabel(preset)}</span>
                          <span>{preset.shipment.teu_count} containers</span>
                          <span className="mono">{preset.shipment.hs_code}</span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
          {solution && workflow && (
            <div className="decision-header-panel">
              <div className="decision-top-row">
                <div>
                  <div className="decision-title-row">
                    <h2 className="decision-title">{solution.optimal_route.route_name}</h2>
                    <span className={`badge ${solution.optimal_route.z3_status === 'SAT' ? 'sat' : 'unsat'}`}>
                      Z3 {solution.optimal_route.z3_status}
                    </span>
                  </div>
                  <p className="decision-meta tabular">
                    <span>
                      {shipment.shipper} → {shipment.consignee}
                    </span>
                    <span className="mono">{solution.optimal_route.node_sequence.join(' → ')}</span>
                  </p>
                </div>

                <div className="btn-row">
                  <button
                    type="button"
                    className="btn"
                    onClick={() => openInspectorDialog('customs')}
                  >
                    <FileJson size={14} /> Inspect Customs JSON
                  </button>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => openInspectorDialog('z3')}
                  >
                    <ShieldCheck size={14} /> Z3 SMT-LIB2 Proofs
                  </button>
                  <button
                    type="button"
                    className="btn primary"
                    disabled={approving || workflow.status === 'DISPATCHED_BONDED_CORRIDOR'}
                    onClick={() => void handleApproveDispatch()}
                  >
                    <CheckCircle2 size={14} />
                    {workflow.status === 'DISPATCHED_BONDED_CORRIDOR'
                      ? 'Dispatched to Bonded Corridor'
                      : approving
                        ? 'Dispatching…'
                        : 'Approve & Dispatch Reroute'}
                  </button>
                </div>
              </div>

              {workflow.approval_receipt && (
                <div className="dispatch-banner">
                  <strong>
                    <CheckCircle2 size={15} style={{ verticalAlign: 'text-bottom', marginRight: 6 }} />
                    Bonded Corridor Dispatched ({workflow.approval_receipt.etir_seal_id})
                  </strong>
                  <span>
                    Tx: <span className="mono">{workflow.approval_receipt.transaction_hash}</span>
                  </span>
                  <span>APIs: {workflow.approval_receipt.dispatched_apis.join(', ')}</span>
                </div>
              )}

              <div className="kpi-grid">
                <div className="kpi-card">
                  <div className="kpi-label">Net Savings vs. Baseline</div>
                  <div className="kpi-value savings tabular">
                    {formatUSD(solution.unit_economics.net_savings_usd)}
                  </div>
                  <div className="kpi-sub tabular">
                    {formatAED(solution.unit_economics.net_savings_aed)} ·{' '}
                    {formatUSD(solution.optimal_route.total_economic_cost_usd)} optimal cost
                  </div>
                </div>

                <div className="kpi-card">
                  <div className="kpi-label">Transit &amp; SLA Margin</div>
                  <div className="kpi-value tabular">
                    {solution.optimal_route.total_hours.toFixed(1)} h
                  </div>
                  <div className="kpi-sub tabular">
                    {solution.unit_economics.hours_saved.toFixed(1)} h faster · SLA ceiling{' '}
                    {shipment.max_transit_hours.toFixed(0)} h
                  </div>
                </div>

                <div className="kpi-card">
                  <div className="kpi-label">Thermal Arrival Integrity</div>
                  <div className="kpi-value tabular">
                    {solution.optimal_route.predicted_arrival_temp_c.toFixed(1)} °C
                  </div>
                  <div className="kpi-sub tabular">
                    Ceiling {shipment.max_temp_c.toFixed(1)} °C ·{' '}
                    {shipment.is_temp_sensitive ? 'GDP Active Cold-Chain' : 'Ambient Freight'}
                  </div>
                </div>

                <div className="kpi-card">
                  <div className="kpi-label">Avoided Risk Exposure</div>
                  <div className="kpi-value tabular">
                    {formatUSD(
                      solution.unit_economics.demurrage_prevented_usd +
                        solution.unit_economics.spoilage_prevented_usd
                    )}
                  </div>
                  <div className="kpi-sub tabular">
                    Demurrage {formatUSD(solution.unit_economics.demurrage_prevented_usd)} ·
                    Spoilage {formatUSD(solution.unit_economics.spoilage_prevented_usd)}
                  </div>
                </div>
              </div>
            </div>
          )}

              <div className="dispatch-cockpit">
                <form
                  className="panel cockpit-controls-panel"
                  aria-label="Disruption and Constraint Controls"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void runSolve(shipment, disruption, paretoAlpha);
                  }}
                >
                  <h2 className="section-label">Disruption &amp; Constraints</h2>

                  <div className="control-group">
                    <div className="control-row">
                      <label htmlFor="hormuz-delay">Strait of Hormuz Choke Delay</label>
                      <span className="mono tabular">{disruption.hormuz_delay_hours} h</span>
                    </div>
                    <input
                      ref={hormuzSliderRef}
                      id="hormuz-delay"
                      type="range"
                      min={0}
                      max={120}
                      step={4}
                      value={disruption.hormuz_delay_hours}
                      onChange={(e) => {
                        const next = { ...disruption, hormuz_delay_hours: Number(e.target.value) };
                        setDisruption(next);
                        void runSolve(shipment, next, paretoAlpha);
                      }}
                    />
                  </div>

                  <div className="control-group">
                    <div className="control-row">
                      <label htmlFor="jebel-delay">Jebel Ali Berth Congestion</label>
                      <span className="mono tabular">
                        {disruption.jebel_ali_congestion_hours} h
                      </span>
                    </div>
                    <input
                      ref={jebelSliderRef}
                      id="jebel-delay"
                      type="range"
                      min={0}
                      max={72}
                      step={4}
                      value={disruption.jebel_ali_congestion_hours}
                      onChange={(e) => {
                        const next = {
                          ...disruption,
                          jebel_ali_congestion_hours: Number(e.target.value),
                        };
                        setDisruption(next);
                        void runSolve(shipment, next, paretoAlpha);
                      }}
                    />
                  </div>

                  <div className="control-group">
                    <div className="control-row">
                      <label htmlFor="pareto-alpha">MILP Pareto Weight (Speed ↔ Cost)</label>
                      <span className="mono tabular">α = {paretoAlpha.toFixed(2)}</span>
                    </div>
                    <input
                      ref={alphaSliderRef}
                      id="pareto-alpha"
                      type="range"
                      min={0}
                      max={1}
                      step={0.05}
                      value={paretoAlpha}
                      onChange={(e) => {
                        const nextAlpha = Number(e.target.value);
                        setParetoAlpha(nextAlpha);
                        void runSolve(shipment, disruption, nextAlpha);
                      }}
                    />
                  </div>

                  <label className="checkbox-label" htmlFor="reefer-fault">
                    <input
                      id="reefer-fault"
                      type="checkbox"
                      className={usesAccentFallback ? 'visually-hidden' : undefined}
                      checked={disruption.reefer_fault}
                      onChange={(e) => {
                        const next = {
                          ...disruption,
                          reefer_fault: e.target.checked,
                          reefer_ambient_drift_c_per_hour: e.target.checked ? 0.035 : 0.0,
                        };
                        setDisruption(next);
                        void runSolve(shipment, next, paretoAlpha);
                      }}
                    />
                    <span>Inject Maritime Reefer Fault (+0.035°C/h drift)</span>
                  </label>

                  <label className="checkbox-label" htmlFor="cepa-strict">
                    <input
                      id="cepa-strict"
                      type="checkbox"
                      className={usesAccentFallback ? 'visually-hidden' : undefined}
                      checked={disruption.require_cepa_zero_tariff}
                      onChange={(e) => {
                        const next = { ...disruption, require_cepa_zero_tariff: e.target.checked };
                        setDisruption(next);
                        void runSolve(shipment, next, paretoAlpha);
                      }}
                    />
                    <span>Enforce UAE-India CEPA 0% Duty Proof (Z3)</span>
                  </label>

                  <div className="telemetry-sync-card" aria-label="Live Telemetry Feed">
                    <div className="telemetry-sync-head">
                      <span className="section-label">Live Telemetry Feed</span>
                      <span className="mono tabular telemetry-sync-meta">
                        {telemetry ? `${telemetry.event_count} events` : 'Standby'} ·{' '}
                        {Object.keys(telemetry?.edge_overrides ?? {}).length} edge overrides
                      </span>
                    </div>
                    <div className="telemetry-source-pills">
                      {telemetry && telemetry.active_sources.length > 0 ? (
                        telemetry.active_sources.map((src) => (
                          <span key={src} className="shock-chip mono">
                            {src}
                          </span>
                        ))
                      ) : (
                        <span className="telemetry-empty-hint">
                          Awaiting Vizion / Lynx / MarineTraffic / Xeneta webhooks
                        </span>
                      )}
                    </div>
                    <div className="telemetry-sync-actions">
                      <button
                        type="button"
                        className="btn"
                        disabled={!telemetry || solving}
                        onClick={handleSyncLiveTelemetry}
                      >
                        <RefreshCw size={13} /> Sync Live Telemetry
                      </button>
                      <label className="checkbox-label telemetry-auto-toggle" htmlFor="auto-sync-telemetry">
                        <input
                          id="auto-sync-telemetry"
                          type="checkbox"
                          className={usesAccentFallback ? 'visually-hidden' : undefined}
                          checked={autoSyncTelemetry}
                          onChange={(e) => setAutoSyncTelemetry(e.target.checked)}
                        />
                        <span>Auto-re-solve</span>
                      </label>
                    </div>
                  </div>

                  <div className="cockpit-submit-row">
                    <button type="submit" className="btn primary" disabled={solving}>
                      <Play size={14} /> {solving ? 'Solving…' : 'Run Z3 + MILP'}
                    </button>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => setActiveTab('diagnostics')}
                    >
                      <FileText size={14} /> Edit BoL Text
                    </button>
                  </div>
                </form>

                <div className="cockpit-map-stage">
                  <CorridorMap
                    nodes={topology.nodes}
                    edges={topology.edges}
                    solution={solution}
                    hormuzDelayHours={disruption.hormuz_delay_hours}
                    jebelAliDelayHours={disruption.jebel_ali_congestion_hours}
                  />

                  {!solution && (
                    <div className="panel standby-panel" aria-live="polite">
                      <div className="standby-head">
                        <strong>Solver Verification Standby</strong>
                        <span className="badge unsat">Awaiting Z3 Proof</span>
                      </div>
                      <p className="standby-desc">
                        Active shipment constraints are locked for formal QF_LRA and HiGHS MILP
                        evaluation across {topology.nodes.length} corridor hubs.
                      </p>
                      <dl className="standby-specs tabular">
                        <div>
                          <dt>Bill of Lading</dt>
                          <dd className="mono">{shipment.bol_number}</dd>
                        </div>
                        <div>
                          <dt>Thermal Ceiling</dt>
                          <dd>{shipment.max_temp_c.toFixed(1)} °C</dd>
                        </div>
                        <div>
                          <dt>Transit SLA</dt>
                          <dd>{shipment.max_transit_hours.toFixed(0)} h</dd>
                        </div>
                        <div>
                          <dt>CEPA Origin</dt>
                          <dd>{shipment.cepa_value_add_pct.toFixed(0)}%</dd>
                        </div>
                      </dl>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* TAB 2: CORRIDOR SCENARIOS */}
          <div
            ref={(el) => {
              panelRefs.current.scenarios = el;
            }}
            id="panel-scenarios"
            role="tabpanel"
            aria-labelledby="tab-scenarios"
            tabIndex={activeTab === 'scenarios' ? 0 : undefined}
            {...(activeTab !== 'scenarios' ? { hidden: 'until-found' as unknown as boolean } : {})}
          >
            <div className="workspace-panel-inner">
              <div className="workspace-intro-panel">
                <div className="workspace-intro-head">
                  <div>
                    <h2 className="workspace-heading">Corridor Scenarios &amp; Cargo Archetypes</h2>
                    <p className="workspace-subcopy">
                      Compare India to UAE to EU bonded cargo manifests, thermal excursion risk,
                      and UAE-India CEPA 0% tariff rules before dispatching on the corridor map.
                    </p>
                  </div>
                  <button
                    type="button"
                    className="btn primary"
                    onClick={() => setActiveTab('dispatch')}
                  >
                    <Compass size={14} /> Return to Dispatch Map
                  </button>
                </div>

                <div className="scenario-cards-grid">
                  {scenarios.map((preset) => {
                    const isActive = activeScenarioId === preset.id;
                    const s = preset.shipment;
                    const d = preset.default_disruption;
                    return (
                      <article
                        key={preset.id}
                        className={`scenario-card ${isActive ? 'active' : ''}`}
                      >
                        <div className="scenario-card-top">
                          <span className="scenario-domain-tag">
                            {getScenarioDomainLabel(preset)}
                          </span>
                          <span className="mono scenario-hs-pill">HS {s.hs_code}</span>
                        </div>

                        <h3 className="scenario-card-title">{preset.title}</h3>
                        <p className="scenario-lane-copy tabular">
                          {s.origin_node} → {s.destination_node} ({s.bol_number})
                        </p>

                        <dl className="scenario-spec-grid tabular">
                          <div>
                            <dt>Cargo Value</dt>
                            <dd>{formatUSD(s.cargo_value_usd)}</dd>
                          </div>
                          <div>
                            <dt>Container Load</dt>
                            <dd>{s.teu_count} TEU</dd>
                          </div>
                          <div>
                            <dt>
                              <Clock size={12} /> Max SLA
                            </dt>
                            <dd>{s.max_transit_hours.toFixed(0)} h</dd>
                          </div>
                          <div>
                            <dt>
                              <Thermometer size={12} /> Ceiling
                            </dt>
                            <dd>
                              {s.is_temp_sensitive
                                ? `${s.initial_temp_c.toFixed(1)} to ${s.max_temp_c.toFixed(1)} °C`
                                : `${s.max_temp_c.toFixed(0)} °C Ambient`}
                            </dd>
                          </div>
                        </dl>

                        <div className="scenario-shock-tags tabular">
                          <span className="shock-chip">
                            Hormuz +{d.hormuz_delay_hours.toFixed(0)}h
                          </span>
                          <span className="shock-chip">
                            Jebel Ali +{d.jebel_ali_congestion_hours.toFixed(0)}h
                          </span>
                          <span className="shock-chip">
                            CEPA {s.cepa_value_add_pct.toFixed(1)}%
                          </span>
                          {d.reefer_fault && <span className="shock-chip warn">Reefer Fault</span>}
                        </div>

                        <div className="scenario-card-footer">
                          <button
                            type="button"
                            className={`btn ${isActive ? 'primary' : 'secondary'}`}
                            aria-pressed={isActive}
                            onClick={() => {
                              handleSelectScenario(preset);
                            }}
                          >
                            {isActive ? 'Active Scenario' : 'Load Scenario & Solve'}
                          </button>
                          {isActive && (
                            <button
                              type="button"
                              className="btn"
                              onClick={() => setActiveTab('dispatch')}
                            >
                              Inspect Map <ArrowRight size={14} />
                            </button>
                          )}
                        </div>
                      </article>
                    );
                  })}
                </div>
              </div>

              <div className="panel manifest-brief-panel">
                <h3 className="section-label">Selected Manifest Brief ({shipment.bol_number})</h3>
                <dl className="manifest-brief-grid tabular">
                  <div>
                    <dt>Shipper</dt>
                    <dd>{shipment.shipper}</dd>
                  </div>
                  <div>
                    <dt>Consignee</dt>
                    <dd>{shipment.consignee}</dd>
                  </div>
                  <div>
                    <dt>Commodity Description</dt>
                    <dd>{shipment.cargo_description}</dd>
                  </div>
                  <div>
                    <dt>Demurrage &amp; Time Cost</dt>
                    <dd>
                      {formatUSD(shipment.demurrage_usd_per_teu_day)}/TEU/day (VoT{' '}
                      {formatUSD(shipment.value_of_time_usd_per_hour)}/h)
                    </dd>
                  </div>
                </dl>
              </div>
            </div>
          </div>

          {/* TAB 3: ROUTE MATRIX */}
          <div
            ref={(el) => {
              panelRefs.current.routes = el;
            }}
            id="panel-routes"
            role="tabpanel"
            aria-labelledby="tab-routes"
            tabIndex={activeTab === 'routes' ? 0 : undefined}
            {...(activeTab !== 'routes' ? { hidden: 'until-found' as unknown as boolean } : {})}
          >
            <div className="workspace-panel-inner">
              {solution && workflow ? (
                <div className="panel">
                  <div className="workspace-intro-head">
                    <div>
                      <h2 className="workspace-heading">
                        Route Economics &amp; Multimodal Candidates
                      </h2>
                      <p className="workspace-subcopy">
                        Every corridor leg evaluated under Z3 QF_LRA regulatory feasibility and
                        HiGHS Pareto total economic cost.
                      </p>
                    </div>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => openInspectorDialog('customs')}
                    >
                      <FileJson size={14} /> Customs Payloads
                    </button>
                  </div>

                  <div
                    tabIndex={0}
                    role="region"
                    aria-labelledby="route-table-caption"
                    className="table-wrapper"
                  >
                    <table className="route-table">
                      <caption id="route-table-caption">
                        Multimodal Corridor Candidates: Z3 Formal Verification &amp; HiGHS MILP
                        Evaluation
                      </caption>
                      <thead>
                        <tr>
                          <th>Corridor Route</th>
                          <th>Z3 Proof</th>
                          <th className="num">Transit</th>
                          <th className="num">Arrival Temp</th>
                          <th className="num">Freight + Demurrage</th>
                          <th className="num">Risk / Penalty</th>
                          <th className="num">Total Economic Cost</th>
                        </tr>
                      </thead>
                      <tbody>
                        {solution.candidates.map((cand) => (
                          <tr key={cand.route_id} className={cand.is_optimal ? 'is-optimal' : undefined}>
                            <th>
                              <div className="route-cell-title">
                                <span>{cand.route_name}</span>
                                <span className="route-badges">
                                  {cand.is_optimal && <span className="badge sat">Optimal</span>}
                                  {cand.is_baseline && <span className="badge unsat">Baseline</span>}
                                </span>
                              </div>
                              {cand.z3_violation && (
                                <div className="route-violation">{cand.z3_violation}</div>
                              )}
                            </th>
                            <td>
                              <span className={`badge ${cand.z3_status === 'SAT' ? 'sat' : 'unsat'}`}>
                                {cand.z3_status}
                              </span>
                            </td>
                            <td className="mono num tabular">{cand.total_hours.toFixed(1)} h</td>
                            <td className="mono num tabular">
                              {cand.predicted_arrival_temp_c.toFixed(1)} °C
                            </td>
                            <td className="mono num tabular">
                              {formatUSD(cand.freight_cost_usd + cand.demurrage_cost_usd)}
                            </td>
                            <td className="mono num tabular">
                              {formatUSD(cand.tariff_penalty_usd + cand.spoilage_exposure_usd)}
                            </td>
                            <td className="mono num tabular">
                              <strong>{formatUSD(cand.total_economic_cost_usd)}</strong>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <div className="panel standby-panel">
                  <strong>Awaiting Solver Matrix</strong>
                  <p className="standby-desc">
                    Trigger a corridor solve from Dispatch &amp; Map to populate multimodal
                    candidate costs.
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* TAB 4: Z3 FORMAL PROOFS */}
          <div
            ref={(el) => {
              panelRefs.current.proofs = el;
            }}
            id="panel-proofs"
            role="tabpanel"
            aria-labelledby="tab-proofs"
            tabIndex={activeTab === 'proofs' ? 0 : undefined}
            {...(activeTab !== 'proofs' ? { hidden: 'until-found' as unknown as boolean } : {})}
          >
            <div className="workspace-panel-inner">
              {solution && workflow ? (
                <div className="workspace-intro-panel">
                  <div className="workspace-intro-head">
                    <div>
                      <h2 className="workspace-heading">
                        Z3 Formal Regulatory Certificates ({solution.z3_certificates.length}{' '}
                        evaluated)
                      </h2>
                      <p className="workspace-subcopy">
                        Deterministic SMT-LIB2 satisfiability audit across GDP thermal ceiling,
                        UAE-India CEPA rules of origin, and GCC e-TIR bonded seals.
                      </p>
                    </div>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => openInspectorDialog('z3')}
                    >
                      <ShieldCheck size={14} /> Open Full Proof Modal
                    </button>
                  </div>

                  <div className="z3-list">
                    {solution.z3_certificates.map((cert) => (
                      <div key={cert.route_id} className="z3-card">
                        <div className="z3-card-header">
                          <strong>{cert.route_name}</strong>
                          <span className={`badge ${cert.status === 'SAT' ? 'sat' : 'unsat'}`}>
                            {cert.status}
                          </span>
                        </div>
                        {cert.checks.map((chk) => (
                          <div key={chk.rule_id} className="z3-check-row">
                            <span>{chk.passed ? '✓ ' : '✗ '}</span>
                            <strong>{chk.rule_id}</strong> ({chk.law_reference}): {chk.detail}
                          </div>
                        ))}
                        <pre className="smt-code">{cert.smtlib_excerpt}</pre>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="panel standby-panel">
                  <strong>No Z3 Certificates Yet</strong>
                  <p className="standby-desc">
                    Run Z3 verification from Dispatch &amp; Map to generate SMT-LIB2 certificates.
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* TAB 5: BOL & DIAGNOSTICS */}
          <div
            ref={(el) => {
              panelRefs.current.diagnostics = el;
            }}
            id="panel-diagnostics"
            role="tabpanel"
            aria-labelledby="tab-diagnostics"
            tabIndex={activeTab === 'diagnostics' ? 0 : undefined}
            {...(activeTab !== 'diagnostics' ? { hidden: 'until-found' as unknown as boolean } : {})}
          >
            <div className="workspace-panel-inner diagnostics-split">
              <div className="panel">
                <h2 className="workspace-heading">
                  Bill of Lading Ingestion ({shipment.hs_code})
                </h2>
                <p className="workspace-subcopy">
                  Edit raw maritime Bill of Lading fields and re-extract strict Pydantic constraints
                  into Z3 + HiGHS.
                </p>
                <div className="control-group">
                  <label htmlFor="bol-input" className="control-row">
                    <span>Guided Bill of Lading Ingestion</span>
                    <span className="mono tabular">{shipment.hs_code}</span>
                  </label>
                  <textarea
                    id="bol-input"
                    className="bol-textarea bol-textarea-tall"
                    value={rawBolText}
                    onChange={(e) => setRawBolText(e.target.value)}
                  />
                </div>
                <div className="btn-row">
                  <button
                    type="button"
                    className="btn primary"
                    disabled={solving}
                    onClick={() => void handleParseAndSolve()}
                  >
                    <Cpu size={14} /> Parse BoL &amp; Re-Solve
                  </button>
                </div>
              </div>

              <div className="panel">
                <h2 className="workspace-heading">
                  Solver &amp; Pipeline Diagnostics
                </h2>
                {solution && workflow ? (
                  <>
                    <p className="workspace-subcopy tabular">
                      {workflow.total_pipeline_ms.toFixed(1)} ms E2E, T-GNN{' '}
                      {solution.gnn_warmstart.prune_ratio_pct.toFixed(1)}% variable pruning
                    </p>
                    <div className="diagnostics-grid">
                      <div className="diag-block">
                        <div className="diag-label">T-GNN Warm-Start</div>
                        <div className="diag-value tabular">
                          {solution.gnn_warmstart.pruned_variables} /{' '}
                          {solution.gnn_warmstart.fleet_scale_variables} vars pruned (
                          {solution.gnn_warmstart.prune_ratio_pct.toFixed(1)}%)
                        </div>
                        <div className="diag-sub">
                          {solution.gnn_warmstart.model_architecture}
                        </div>
                      </div>

                      <div className="diag-block">
                        <div className="diag-label">MILP Optimality &amp; Clearinghouse Fee</div>
                        <div className="diag-value tabular">
                          Gap {solution.optimality_gap_pct.toFixed(2)}% / Fee{' '}
                          {formatUSD(solution.unit_economics.platform_fee_usd)} (
                          {formatAED(solution.unit_economics.platform_fee_aed)})
                        </div>
                        <div className="diag-sub">
                          {solution.solver_engine} ({solution.unit_economics.clearinghouse_take_rate_pct.toFixed(0)}% take-rate)
                        </div>
                      </div>
                    </div>

                    <div className="telemetry-strip">
                      {workflow.stage_latencies.map((st) => (
                        <div className="stage-card" key={st.stage}>
                          <div className="stage-name">{st.stage}</div>
                          <div className="stage-meta">
                            <span>{st.component}</span>
                            <span className="stage-ms tabular">{st.duration_ms.toFixed(2)} ms</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="standby-desc">
                    Solver telemetry populates automatically once the first pipeline run completes.
                  </p>
                )}
              </div>

              <div className="panel diagnostics-full-span" aria-label="Canonical Compliance Gate">
                <div className="workspace-intro-head">
                  <div>
                    <h2 className="workspace-heading">
                      Canonical Compliance Gate (<code>/api/v1/validate-shipment</code>)
                    </h2>
                    <p className="workspace-subcopy">
                      Zero-Hallucination DCSA eBL 3.0 &amp; GCC 12-digit HS validation gate. Missing
                      mandatory customs fields trigger an explicit <code>VALIDATION_HOLD</code> that
                      blocks autonomous dispatch.
                    </p>
                  </div>
                  <div className="btn-row">
                    <button
                      type="button"
                      className="btn primary"
                      disabled={validatingGate}
                      onClick={() => void handleValidateShipment('valid')}
                    >
                      <ShieldCheck size={14} /> Test Valid DCSA eBL 3.0
                    </button>
                    <button
                      type="button"
                      className="btn"
                      disabled={validatingGate}
                      onClick={() => void handleValidateShipment('incomplete')}
                    >
                      <ShieldAlert size={14} /> Test Incomplete Manifest (Hold)
                    </button>
                  </div>
                </div>

                {gateResult?.kind === 'verified' && (
                  <div className="dispatch-banner" role="status">
                    <span className="badge sat">VERIFIED SHIPMENT</span>
                    <strong>{gateResult.shipment.internal_request_id}</strong>
                    <span className="mono">{gateResult.shipment.transport_document_ref}</span>
                    <span>
                      Incoterms {gateResult.shipment.incoterms_code} ·{' '}
                      {gateResult.shipment.consignment_items.length} verified item(s) · Autonomous
                      dispatch permitted
                    </span>
                  </div>
                )}

                {gateResult?.kind === 'hold' && (
                  <div className="validation-hold-panel" role="alert">
                    <div className="validation-hold-head">
                      <span className="badge unsat">{gateResult.hold.status}</span>
                      <strong>
                        Autonomous Dispatch Blocked ({gateResult.hold.internal_request_id})
                      </strong>
                      <span className="mono tabular">
                        {gateResult.hold.missing_compliance_fields.length} missing compliance
                        field(s)
                      </span>
                    </div>
                    <div
                      tabIndex={0}
                      role="region"
                      aria-labelledby="validation-hold-caption"
                      className="table-wrapper"
                    >
                      <table className="route-table">
                        <caption id="validation-hold-caption">
                          Zero-Hallucination ValidationHold Missing Compliance Fields
                        </caption>
                        <thead>
                          <tr>
                            <th>Field Path</th>
                            <th>Reason Code</th>
                            <th>Regulatory Reference</th>
                            <th>Detail</th>
                          </tr>
                        </thead>
                        <tbody>
                          {gateResult.hold.missing_compliance_fields.map((f) => (
                            <tr key={`${f.field_path}-${f.reason_code}`}>
                              <td className="mono">{f.field_path}</td>
                              <td>
                                <span className="badge unsat">{f.reason_code}</span>
                              </td>
                              <td className="mono">{f.regulatory_reference}</td>
                              <td>{f.message}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {gateResult?.kind === 'error' && (
                  <div className="dispatch-banner error-banner" role="alert">
                    <AlertTriangle size={14} /> {gateResult.message}
                  </div>
                )}
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* Native top-layer modal <dialog> without redundant ARIA overrides */}
      <dialog
        ref={dialogRef}
        id="customs-payload-dialog"
        className="customs-dialog"
        aria-labelledby="customs-dialog-title"
        {...({ closedby: 'any' } as Record<string, string>)}
      >
        <div className="dialog-header">
          <h2 id="customs-dialog-title">
            {modalTab === 'customs'
              ? 'Auto-Generated UAE / Oman Customs & Etihad Cargo Payloads'
              : 'Z3 SMT-LIB2 Formal Compliance Certificates'}
          </h2>
          <div className="btn-row">
            <button
              type="button"
              className={`btn ${modalTab === 'customs' ? 'primary' : ''}`}
              onClick={() => setModalTab('customs')}
            >
              Customs JSON
            </button>
            <button
              type="button"
              className={`btn ${modalTab === 'z3' ? 'primary' : ''}`}
              onClick={() => setModalTab('z3')}
            >
              Z3 Proofs
            </button>
          </div>
        </div>

        <div className="dialog-body">
          {solution && modalTab === 'customs' && (
            <>
              <div>
                <strong>Dubai Trade / Mirsal 2 &amp; Maqta Gateway ATLP + Green Corridor e-TIR</strong>
              </div>
              <pre className="json-block">
                {JSON.stringify(solution.customs_payloads, null, 2)}
              </pre>
            </>
          )}

          {solution &&
            modalTab === 'z3' &&
            solution.z3_certificates.map((cert) => (
              <div key={cert.route_id} className="z3-card">
                <div className="z3-card-header">
                  <strong>{cert.route_name}</strong>
                  <span className={`badge ${cert.status === 'SAT' ? 'sat' : 'unsat'}`}>
                    {cert.status}
                  </span>
                </div>
                {cert.violation_summary && (
                  <div style={{ color: 'var(--danger)', marginBottom: 4 }}>
                    {cert.violation_summary}
                  </div>
                )}
                <pre className="smt-code">{cert.smtlib_excerpt}</pre>
              </div>
            ))}
        </div>

        <div className="dialog-footer">
          <form method="dialog">
            <button type="submit" value="close" className="btn primary" autoFocus>
              Close
            </button>
          </form>
        </div>
      </dialog>
      </div>
    </CorridorHomepage>
  );
}
