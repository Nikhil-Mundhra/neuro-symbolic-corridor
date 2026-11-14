import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  FileJson,
  Play,
  ShieldCheck,
} from 'lucide-react';
import { CorridorMap } from './components/CorridorMap';
import { CorridorHomepage, type HomepageViewMode } from './components/CorridorHomepage';
import { CorridorBrandMark } from './components/CorridorBrandMark';
import { FALLBACK_SCENARIOS, FALLBACK_TOPOLOGY } from './data/fallbackData';
import type {
  CorridorTopology,
  DisruptionState,
  ScenarioPreset,
  ShipmentSpec,
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
  const [modalTab, setModalTab] = useState<'customs' | 'z3'>('customs');
  const [viewMode, setViewMode] = useState<HomepageViewMode>('full');

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

  // Load topology & scenarios from gateway-go on boot
  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      try {
        const [topoRes, scenRes] = await Promise.all([
          fetch('/api/v1/corridor/topology'),
          fetch('/api/v1/scenarios'),
        ]);
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
    es.onerror = () => setSseConnected(false);
    return () => {
      es.close();
    };
  }, []);

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

  const openInspectorDialog = (tab: 'customs' | 'z3') => {
    setModalTab(tab);
    dialogRef.current?.showModal();
  };

  const solution = workflow?.solution ?? null;
  const usesAccentFallback = typeof CSS !== 'undefined' && !CSS.supports('accent-color', '#000');

  return (
    <CorridorHomepage
      scenarios={scenarios}
      viewMode={viewMode}
      onToggleViewMode={setViewMode}
      onLoadScenario={handleSelectScenario}
    >
      <div className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <h1>
            <CorridorBrandMark size={20} />
            Gulf Corridor Dispatch
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

      <main className="main-grid">
        <aside className="panel sidebar-panel" aria-label="Disruption & Bill of Lading Controls">
          <section className="sidebar-section">
            <h2 className="section-label">Corridor Scenarios</h2>
            <div className="scenario-tabs">
              {scenarios.map((preset) => (
                <button
                  key={preset.id}
                  type="button"
                  className={`scenario-btn ${activeScenarioId === preset.id ? 'active' : ''}`}
                  onClick={() => handleSelectScenario(preset)}
                >
                  <strong>{preset.title}</strong>
                  <span className="tabular">{preset.subtitle}</span>
                </button>
              ))}
            </div>
          </section>

          <form
            className="sidebar-section"
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
                <span className="mono tabular">{disruption.jebel_ali_congestion_hours} h</span>
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

            <details className="control-disclosure">
              <summary>Bill of Lading Ingestion ({shipment.hs_code})</summary>
              <div className="disclosure-body">
                <div className="control-group">
                  <label htmlFor="bol-input" className="control-row">
                    <span>Guided Bill of Lading Ingestion</span>
                    <span className="mono tabular">{shipment.hs_code}</span>
                  </label>
                  <textarea
                    id="bol-input"
                    className="bol-textarea"
                    value={rawBolText}
                    onChange={(e) => setRawBolText(e.target.value)}
                  />
                </div>

                <div className="btn-row">
                  <button
                    type="button"
                    className="btn secondary"
                    disabled={solving}
                    onClick={() => void handleParseAndSolve()}
                  >
                    <Cpu size={14} /> Parse BoL &amp; Re-Solve
                  </button>
                  <button type="submit" className="btn primary" disabled={solving}>
                    <Play size={14} /> {solving ? 'Solving…' : 'Run Z3 + MILP'}
                  </button>
                </div>
              </div>
            </details>
          </form>
        </aside>

        <section className="right-column">
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

          <CorridorMap
            nodes={topology.nodes}
            edges={topology.edges}
            solution={solution}
            hormuzDelayHours={disruption.hormuz_delay_hours}
            jebelAliDelayHours={disruption.jebel_ali_congestion_hours}
          />

          {solution && workflow && (
            <div className="panel">
              <div
                tabIndex={0}
                role="region"
                aria-labelledby="route-table-caption"
                className="table-wrapper"
              >
                <table className="route-table">
                  <caption id="route-table-caption">
                    Multimodal Corridor Candidates — Z3 Formal Verification &amp; HiGHS MILP Evaluation
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
          )}

          {solution && workflow && (
            <section className="secondary-disclosures" aria-label="Audit and Pipeline Diagnostics">
              <details className="enterprise-disclosure">
                <summary>
                  Z3 Formal Regulatory Certificates ({solution.z3_certificates.length} evaluated)
                </summary>
                <div className="disclosure-content">
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
                            <strong>{chk.rule_id}:</strong> {chk.detail}
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                </div>
              </details>

              <details className="enterprise-disclosure">
                <summary>
                  Solver &amp; Pipeline Diagnostics ({workflow.total_pipeline_ms.toFixed(1)} ms E2E ·
                  T-GNN {solution.gnn_warmstart.prune_ratio_pct.toFixed(1)}% pruned)
                </summary>
                <div className="disclosure-content">
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
                        Gap {solution.optimality_gap_pct.toFixed(2)}% · Fee{' '}
                        {formatUSD(solution.unit_economics.platform_fee_usd)} (
                        {formatAED(solution.unit_economics.platform_fee_aed)})
                      </div>
                      <div className="diag-sub">
                        {solution.solver_engine} ·{' '}
                        {solution.unit_economics.clearinghouse_take_rate_pct.toFixed(0)}% take-rate
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
                </div>
              </details>
            </section>
          )}
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
