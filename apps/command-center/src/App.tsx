import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  FileJson,
  Layers,
  Play,
  ShieldCheck,
  Sparkles,
  Zap,
} from 'lucide-react';
import { CorridorMap } from './components/CorridorMap';
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
  }, [disruption.hormuz_delay_hours, disruption.jebel_ali_congestion_hours, paretoAlpha, syncSliderProgress]);

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
          throw new Error(`Gateway returned ${res.status}`);
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
          const topoData = (await topoRes.json()) as CorridorTopology;
          if (!cancelled) setTopology(topoData);
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
    es.addEventListener('workflow_update', () => setSseConnected(true));
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
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <h1>
            <ShieldCheck size={22} />
            Neuro-Symbolic Gulf Corridor Solver
          </h1>
          <p className="brand-subtitle">
            India (JNPT) → Oman Green Corridor (Salalah/Sohar) → UAE (Fujairah / KIZAD / JAFZA / AUH) → Europe
          </p>
        </div>

        <div className="status-cluster">
          <span className={`pill ${sseConnected ? 'ok' : 'warn'}`}>
            <Activity size={14} />
            {sseConnected ? 'Go Gateway SSE Live' : 'Polling / Connecting'}
          </span>
          {workflow && (
            <span className="pill ok mono">
              <Zap size={14} />
              {workflow.total_pipeline_ms.toFixed(1)} ms E2E
            </span>
          )}
          {workflow && (
            <span className="pill mono">
              WF: {workflow.workflow_id} ({workflow.status})
            </span>
          )}
        </div>
      </header>

      {errorMsg && (
        <div className="dispatch-banner" role="alert">
          <AlertTriangle size={15} style={{ verticalAlign: 'text-bottom', marginRight: 6 }} />
          Backend connection notice: {errorMsg}. Ensure <code>solver-py</code> (:8001) and{' '}
          <code>gateway-go</code> (:8080) are running.
        </div>
      )}

      {workflow && (
        <section className="telemetry-strip" aria-label="Sub-400ms Neuro-Symbolic Pipeline Telemetry">
          {workflow.stage_latencies.map((st) => (
            <div className="stage-card" key={st.stage}>
              <div className="stage-name">{st.stage}</div>
              <div className="stage-meta">
                <span>{st.component}</span>
                <span className="stage-ms">{st.duration_ms.toFixed(2)} ms</span>
              </div>
            </div>
          ))}
        </section>
      )}

      <main className="main-grid">
        <aside className="panel" aria-label="Disruption & Bill of Lading Controls">
          <div className="panel-header">
            <h2>
              <Sparkles size={16} /> Corridor Scenario Presets
            </h2>
          </div>

          <div className="scenario-tabs">
            {scenarios.map((preset) => (
              <button
                key={preset.id}
                type="button"
                className={`scenario-btn ${activeScenarioId === preset.id ? 'active' : ''}`}
                onClick={() => handleSelectScenario(preset)}
              >
                <strong>{preset.title}</strong>
                <span>{preset.subtitle}</span>
              </button>
            ))}
          </div>

          <div className="panel-header">
            <h2>
              <AlertTriangle size={16} /> Live Disruption Injection
            </h2>
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              void runSolve(shipment, disruption, paretoAlpha);
            }}
            style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}
          >
            <div className="control-group">
              <div className="control-row">
                <label htmlFor="hormuz-delay">Strait of Hormuz Choke Delay</label>
                <span className="mono">{disruption.hormuz_delay_hours} h</span>
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
                <span className="mono">{disruption.jebel_ali_congestion_hours} h</span>
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
                <span className="mono">α = {paretoAlpha.toFixed(2)}</span>
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

            <div className="control-group">
              <label htmlFor="bol-input" className="control-row">
                <span>Guided Bill of Lading Ingestion</span>
                <span className="mono">{shipment.hs_code}</span>
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
          </form>
        </aside>

        <section className="right-column">
          {solution && (
            <div className="kpi-grid">
              <div className="kpi-card">
                <div className="kpi-label">Shadow-Mode Net Savings</div>
                <div className="kpi-value savings">
                  {formatUSD(solution.unit_economics.net_savings_usd)}
                </div>
                <div className="kpi-sub">
                  {formatAED(solution.unit_economics.net_savings_aed)} |{' '}
                  {solution.unit_economics.hours_saved.toFixed(1)}h faster
                </div>
              </div>

              <div className="kpi-card">
                <div className="kpi-label">Demurrage &amp; Spoilage Prevented</div>
                <div className="kpi-value">
                  {formatUSD(
                    solution.unit_economics.demurrage_prevented_usd +
                      solution.unit_economics.spoilage_prevented_usd
                  )}
                </div>
                <div className="kpi-sub">
                  12% Clearinghouse Fee: {formatUSD(solution.unit_economics.platform_fee_usd)} (
                  {formatAED(solution.unit_economics.platform_fee_aed)})
                </div>
              </div>

              <div className="kpi-card">
                <div className="kpi-label">T-GNN Search-Tree Pruning</div>
                <div className="kpi-value">
                  {solution.gnn_warmstart.prune_ratio_pct.toFixed(1)}%
                </div>
                <div className="kpi-sub">
                  {solution.gnn_warmstart.pruned_variables} /{' '}
                  {solution.gnn_warmstart.fleet_scale_variables} fleet vars pruned
                </div>
              </div>

              <div className="kpi-card">
                <div className="kpi-label">Solver Core &amp; Optimality Gap</div>
                <div className="kpi-value mono">{solution.total_solver_ms.toFixed(1)} ms</div>
                <div className="kpi-sub">
                  HiGHS MILP Gap: {solution.optimality_gap_pct.toFixed(2)}% | Z3:{' '}
                  {solution.optimal_route.z3_status}
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
              <div className="panel-header">
                <h2>
                  <Layers size={16} /> Autonomous Execution Bridge &amp; 1-Click Dispatch
                </h2>
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
                  </strong>{' '}
                  — Tx: <span className="mono">{workflow.approval_receipt.transaction_hash}</span> |
                  APIs: {workflow.approval_receipt.dispatched_apis.join(' • ')}
                </div>
              )}

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
                      <th>Transit</th>
                      <th>Arrival Temp</th>
                      <th>Freight + Demurrage</th>
                      <th>Risk / Penalty</th>
                      <th>Total Economic Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {solution.candidates.map((cand) => (
                      <tr key={cand.route_id} className={cand.is_optimal ? 'is-optimal' : undefined}>
                        <th>
                          {cand.route_name}
                          {cand.is_optimal && (
                            <span className="badge sat" style={{ marginLeft: 8 }}>
                              OPTIMAL
                            </span>
                          )}
                          {cand.is_baseline && (
                            <span className="badge unsat" style={{ marginLeft: 8 }}>
                              BASELINE
                            </span>
                          )}
                        </th>
                        <td>
                          <span className={`badge ${cand.z3_status === 'SAT' ? 'sat' : 'unsat'}`}>
                            {cand.z3_status}
                          </span>
                        </td>
                        <td className="mono">{cand.total_hours.toFixed(1)} h</td>
                        <td className="mono">{cand.predicted_arrival_temp_c.toFixed(1)} °C</td>
                        <td className="mono">
                          {formatUSD(cand.freight_cost_usd + cand.demurrage_cost_usd)}
                        </td>
                        <td className="mono">
                          {formatUSD(cand.tariff_penalty_usd + cand.spoilage_exposure_usd)}
                        </td>
                        <td className="mono">
                          <strong>{formatUSD(cand.total_economic_cost_usd)}</strong>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {solution && (
            <div className="panel">
              <div className="panel-header">
                <h2>
                  <ShieldCheck size={16} /> Z3 SMT Formal Regulatory Certificates
                </h2>
              </div>
              <div className="z3-list">
                {solution.z3_certificates.slice(0, 4).map((cert) => (
                  <div key={cert.route_id} className="z3-card">
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        gap: 8,
                        marginBottom: 6,
                      }}
                    >
                      <strong>{cert.route_name}</strong>
                      <span className={`badge ${cert.status === 'SAT' ? 'sat' : 'unsat'}`}>
                        {cert.status}
                      </span>
                    </div>
                    {cert.checks.map((chk) => (
                      <div key={chk.rule_id} style={{ marginBottom: 4 }}>
                        <span>{chk.passed ? '✓ ' : '✗ '}</span>
                        <strong>{chk.rule_id}:</strong> {chk.detail}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
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
              Z3 SMT-LIB2
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
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
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
  );
}
