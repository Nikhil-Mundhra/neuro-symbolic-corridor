import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { FALLBACK_SCENARIOS, FALLBACK_TOPOLOGY } from './data/fallbackData';
import { CorridorMap } from './components/CorridorMap';
import App from './App';


class MockEventSource {
  addEventListener = vi.fn();
  close = vi.fn();
  onerror: (() => void) | null = null;
}

beforeEach(() => {
  window.history.pushState({}, '', '/twin');
  vi.stubGlobal('EventSource', MockEventSource);
  vi.stubGlobal('CSS', { supports: () => true });
  vi.stubGlobal('scrollTo', vi.fn());
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.setAttribute('open', '');
  });
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.removeAttribute('open');
  });

  const mockWorkflow = {
    workflow_id: 'wf-test123',
    status: 'SOLVED',
    created_at_utc: '2026-11-13T12:00:00Z',
    total_pipeline_ms: 19.4,
    retry_count: 0,
    stage_latencies: [
      { stage: 'Go Gateway Ingest', component: 'Go 1.26', duration_ms: 1.1, status: 'DONE' },
      { stage: 'Z3 SMT + HiGHS MILP', component: 'Z3+HiGHS', duration_ms: 16.2, status: 'DONE' },
    ],
    solution: {
      solve_id: 's1',
      solver_engine: 'SciPy-HiGHS MILP + Z3 4.13 SMT',
      optimality_gap_pct: 0,
      total_solver_ms: 16.2,
      optimal_route: {
        route_id: 'ROUTE_FUJAIRAH_ETIHAD_AIR_BRIDGE',
        route_name: 'Fujairah Bypass + Bonded Rail + Etihad Cargo PharmaLife Air Bridge',
        node_sequence: ['INNSA', 'AEFJR', 'AEAUH', 'EUFRA'],
        edge_ids: ['E_INNSA_AEFJR_SEA', 'E_AEFJR_AEAUH_RAIL', 'E_AEAUH_EUFRA_AIR'],
        modes: ['SEA', 'ETIHAD_RAIL_BONDED', 'AIR_CARGO'],
        z3_status: 'SAT',
        z3_violation: null,
        total_hours: 92,
        freight_cost_usd: 27000,
        demurrage_cost_usd: 0,
        tariff_penalty_usd: 0,
        spoilage_exposure_usd: 0,
        total_economic_cost_usd: 27000,
        predicted_arrival_temp_c: 7.54,
        is_optimal: true,
        is_baseline: false,
      },
      candidates: [],
      z3_certificates: [],
      gnn_warmstart: {
        model_architecture: 'Temporal-GATv2',
        fleet_scale_variables: 2400,
        pruned_variables: 1800,
        prune_ratio_pct: 75,
        predicted_bottleneck_nodes: ['STRAIT_OF_HORMUZ'],
        edge_risk_scores: {},
      },
      pareto_frontier: [],
      unit_economics: {
        baseline_route_name: 'Baseline',
        baseline_total_cost_usd: 1877000,
        baseline_hours: 528,
        optimal_route_name: 'Fujairah Air Bridge',
        optimal_total_cost_usd: 27000,
        optimal_hours: 92,
        net_savings_usd: 1850000,
        net_savings_aed: 6794125,
        demurrage_prevented_usd: 4480,
        spoilage_prevented_usd: 1850000,
        hours_saved: 436,
        clearinghouse_take_rate_pct: 12,
        platform_fee_usd: 222000,
        platform_fee_aed: 815295,
      },
      stage_latencies: [],
      customs_payloads: {
        dubai_trade_mirsal2: {},
        maqta_gateway_atlp: {},
        oman_green_corridor_etir: {},
        etihad_cargo_eawb: {},
      },
    },
  };

  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      if (url.includes('/topology')) {
        return Promise.resolve(new Response(JSON.stringify(FALLBACK_TOPOLOGY), { status: 200 }));
      }
      if (url.includes('/scenarios')) {
        return Promise.resolve(new Response(JSON.stringify(FALLBACK_SCENARIOS), { status: 200 }));
      }
      if (url.includes('/approve')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              ...mockWorkflow,
              status: 'DISPATCHED_BONDED_CORRIDOR',
              approval_receipt: {
                approved_by: 'Dispatcher',
                approved_at_utc: '2026-11-13T12:01:00Z',
                transaction_hash: '0xabc123',
                dispatched_apis: ['Dubai Trade'],
                etir_seal_id: 'ETIR-GCC-wf-test123',
              },
            }),
            { status: 200 }
          )
        );
      }
      return Promise.resolve(new Response(JSON.stringify(mockWorkflow), { status: 200 }));
    })
  );
});

describe('fallbackData', () => {
  it('defines 10 Gulf Corridor nodes and default pharma scenario', () => {
    expect(FALLBACK_TOPOLOGY.nodes).toHaveLength(10);
    expect(FALLBACK_SCENARIOS[0].shipment.bol_number).toBe('BOL-INNSA-2026-8841');
  });
});

describe('CorridorMap', () => {
  it('renders Natural Earth + Tile SVG map, hub callouts, basemap switcher, and schematic toggle', () => {
    const { container } = render(
      <CorridorMap
        nodes={FALLBACK_TOPOLOGY.nodes}
        edges={FALLBACK_TOPOLOGY.edges}
        solution={null}
        hormuzDelayHours={72}
        jebelAliDelayHours={24}
      />
    );

    expect(screen.getByTestId('corridor-svg-map')).toBeInTheDocument();
    expect(container.querySelectorAll('path.geo-land-fill').length).toBeGreaterThan(20);

    // Clicking hub node opens zone inspector card
    const fujairahHub = container.querySelector('[data-node-id="AEFJR"]');
    expect(fujairahHub).not.toBeNull();
    if (fujairahHub) fireEvent.click(fujairahHub);
    expect(screen.getByText(/AEFJR ·/i)).toBeInTheDocument();

    // Switching basemap provider to pure offline Natural Earth vector mode
    const basemapSelect = screen.getByLabelText(/Tile Basemap Provider/i);
    fireEvent.change(basemapSelect, { target: { value: 'vector' } });
    expect(screen.getByText(/Natural Earth 50m\/110m Vector Geography/i)).toBeInTheDocument();

    // Switching to LLM-inspectable Schematic Graph mode
    const schematicBtn = screen.getByRole('button', { name: /Schematic Graph/i });
    fireEvent.click(schematicBtn);
    expect(screen.getByTestId('corridor-schematic-view')).toBeInTheDocument();
    expect(screen.getByText(/Hormuz Bypass vs Direct/i)).toBeInTheDocument();

    // Switching region preset returns to Geographic Map view and activates button
    const eurasiaBtn = screen.getByRole('button', { name: /India → UAE → EU Corridor/i });
    fireEvent.click(eurasiaBtn);
    expect(eurasiaBtn).toHaveClass('active');
    expect(screen.getByTestId('corridor-svg-map')).toBeInTheDocument();
  });
});

describe('App', () => {
  it('bootstraps, solves, opens customs dialog, and dispatches reroute', async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(/wf-test123/i)).toBeInTheDocument();
    });

    expect(screen.getAllByText(/^\$1,850,000$/).length).toBeGreaterThanOrEqual(1);

    // Side tablist exists with vertical orientation and switches to Corridor Scenarios
    const workTabs = screen.getByRole('tablist', { name: /Corridor workstation views/i });
    expect(workTabs).toHaveAttribute('aria-orientation', 'vertical');
    const dispatchTab = screen.getByRole('tab', { name: /Dispatch & Map/i });
    const scenariosTab = screen.getByRole('tab', { name: /Corridor Scenarios/i });
    fireEvent.keyDown(dispatchTab, { key: 'ArrowDown' });
    expect(scenariosTab).toHaveAttribute('aria-selected', 'true');
    expect(
      screen.getByRole('heading', { name: /EV Drivetrain Gearboxes \(CEPA\)/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: /Specialty Polymers \(Baseline Cost\)/i })
    ).toBeInTheDocument();
    fireEvent.keyDown(scenariosTab, { key: 'Home' });
    expect(dispatchTab).toHaveAttribute('aria-selected', 'true');

    fireEvent.click(screen.getByRole('button', { name: /Inspect Customs JSON/i }));
    expect(HTMLDialogElement.prototype.showModal).toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /Approve & Dispatch Reroute/i }));
    await waitFor(() => {
      expect(screen.getByText(/Dispatched to Bonded Corridor/i)).toBeInTheDocument();
    });
  });

  it('enforces Modern Web & A11y invariants: native <dialog closedby>, accessible table region, and slider/BoL interaction', async () => {
    // Test CSS.supports('accent-color') === false progressive enhancement fallback
    vi.stubGlobal('CSS', { supports: () => false });
    const { container } = render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/wf-test123/i)).toBeInTheDocument();
    });

    // 1. Native <dialog> invariant (no custom role="dialog" div overlays)
    const dialogEl = container.querySelector('dialog#customs-payload-dialog');
    expect(dialogEl).not.toBeNull();
    expect(dialogEl?.getAttribute('closedby')).toBe('any');
    expect(dialogEl?.getAttribute('role')).toBeNull();

    // 2. Switch between Z3 SMT-LIB2 and Customs JSON tabs inside dialog
    fireEvent.click(screen.getByRole('button', { name: /Z3 SMT-LIB2 Proofs/i }));
    expect(HTMLDialogElement.prototype.showModal).toHaveBeenCalled();
    const customsTabBtn = screen.getByRole('button', { name: /^Customs JSON$/i });
    fireEvent.click(customsTabBtn);

    // 3. Pointer light-dismiss fallback when closedBy is not on HTMLDialogElement.prototype
    if (dialogEl) {
      vi.spyOn(dialogEl, 'getBoundingClientRect').mockReturnValue({
        left: 100,
        right: 500,
        top: 100,
        bottom: 400,
        width: 400,
        height: 300,
        x: 100,
        y: 100,
        toJSON: () => ({}),
      });
      const downEv = new Event('pointerdown', { bubbles: true });
      Object.assign(downEv, { clientX: 10, clientY: 10 });
      dialogEl.dispatchEvent(downEv);

      const upEv = new Event('pointerup', { bubbles: true });
      Object.assign(upEv, { clientX: 10, clientY: 10 });
      dialogEl.dispatchEvent(upEv);

      expect(HTMLDialogElement.prototype.close).toHaveBeenCalled();
      fireEvent(dialogEl, new Event('close'));
      dialogEl.removeAttribute('open');
    }

    // 4. Accessible scrollable table region inside the Route Matrix side tab
    fireEvent.click(screen.getByRole('tab', { name: /Route Matrix/i }));
    const tableRegion = screen.getByRole('region', {
      name: /Multimodal Corridor Candidates/i,
    });
    expect(tableRegion).toHaveAttribute('tabIndex', '0');

    // Return to Dispatch & Map tab for live disruption controls & map interaction
    fireEvent.click(screen.getByRole('tab', { name: /Dispatch & Map/i }));

    // 5. Disruption sliders, checkboxes, and Guided BoL Parse trigger re-solve
    const hormuzSlider = screen.getByLabelText(/Strait of Hormuz Choke Delay/i);
    fireEvent.change(hormuzSlider, { target: { value: '96' } });

    const jebelSlider = screen.getByLabelText(/Jebel Ali Berth Congestion/i);
    fireEvent.change(jebelSlider, { target: { value: '36' } });

    const alphaSlider = screen.getByLabelText(/MILP Pareto Weight/i);
    fireEvent.change(alphaSlider, { target: { value: '0.75' } });

    const reeferCheckbox = screen.getByLabelText(/Inject Maritime Reefer Fault/i);
    expect(reeferCheckbox).toHaveClass('visually-hidden');
    fireEvent.click(reeferCheckbox);

    const cepaCheckbox = screen.getByLabelText(/Enforce UAE-India CEPA/i);
    fireEvent.click(cepaCheckbox);

    // 6. Parse BoL & Re-Solve flow
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.includes('/parse-bol')) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                shipment: FALLBACK_SCENARIOS[0].shipment,
                extraction_confidence: 0.96,
                extraction_ms: 0.4,
                extracted_tokens: ['HS=>3002.15.00'],
              }),
              { status: 200 }
            )
          );
        }
        return Promise.resolve(
          new Response(
            JSON.stringify({
              workflow_id: 'wf-parsed999',
              status: 'SOLVED',
              created_at_utc: '2026-11-13T12:05:00Z',
              total_pipeline_ms: 14.2,
              retry_count: 0,
              stage_latencies: [],
              solution: {
                solve_id: 's2',
                solver_engine: 'SciPy-HiGHS MILP + Z3 4.13 SMT',
                optimality_gap_pct: 0,
                total_solver_ms: 12.1,
                optimal_route: {
                  route_id: 'ROUTE_FUJAIRAH_ETIHAD_AIR_BRIDGE',
                  route_name: 'Fujairah Bypass',
                  node_sequence: ['INNSA', 'AEFJR', 'AEAUH', 'EUFRA'],
                  edge_ids: ['E_INNSA_AEFJR_SEA'],
                  modes: ['SEA'],
                  z3_status: 'SAT',
                  z3_violation: null,
                  total_hours: 92,
                  freight_cost_usd: 27000,
                  demurrage_cost_usd: 0,
                  tariff_penalty_usd: 0,
                  spoilage_exposure_usd: 0,
                  total_economic_cost_usd: 27000,
                  predicted_arrival_temp_c: 7.5,
                  is_optimal: true,
                  is_baseline: false,
                },
                candidates: [],
                z3_certificates: [
                  {
                    route_id: 'ROUTE_SOHAR_UNBONDED_SPOT_TRAP',
                    route_name: 'Unbonded Trap',
                    edge_ids: [],
                    status: 'UNSAT',
                    checks: [
                      {
                        rule_id: 'GCC_CUSTOMS_ETIR_SEAL',
                        law_reference: 'Art 98',
                        passed: false,
                        detail: 'VIOLATION',
                      },
                    ],
                    smtlib_excerpt: '(assert false)',
                    violation_summary: 'VIOLATION: Unbonded spot transit',
                  },
                ],
                gnn_warmstart: {
                  model_architecture: 'Temporal-GATv2',
                  fleet_scale_variables: 2400,
                  pruned_variables: 1800,
                  prune_ratio_pct: 75,
                  predicted_bottleneck_nodes: ['STRAIT_OF_HORMUZ'],
                  edge_risk_scores: {},
                },
                pareto_frontier: [],
                unit_economics: {
                  baseline_route_name: 'Baseline',
                  baseline_total_cost_usd: 1877000,
                  baseline_hours: 528,
                  optimal_route_name: 'Fujairah',
                  optimal_total_cost_usd: 27000,
                  optimal_hours: 92,
                  net_savings_usd: 1850000,
                  net_savings_aed: 6794125,
                  demurrage_prevented_usd: 4480,
                  spoilage_prevented_usd: 1850000,
                  hours_saved: 436,
                  clearinghouse_take_rate_pct: 12,
                  platform_fee_usd: 222000,
                  platform_fee_aed: 815295,
                },
                stage_latencies: [],
                customs_payloads: {
                  dubai_trade_mirsal2: {},
                  maqta_gateway_atlp: {},
                  oman_green_corridor_etir: {},
                  etihad_cargo_eawb: null,
                },
              },
            }),
            { status: 200 }
          )
        );
      })
    );

    // 6. Switch to BoL & Diagnostics side tab for BoL Parse & Re-Solve + Telemetry Diagnostics
    fireEvent.click(screen.getByRole('tab', { name: /BoL & Diagnostics/i }));
    const bolTextarea = screen.getByLabelText(/Guided Bill of Lading Ingestion/i);
    fireEvent.change(bolTextarea, { target: { value: 'BILL OF LADING: BOL-NEW-101' } });
    const parseBtn = screen.getByRole('button', { name: /Parse BoL & Re-Solve/i });
    await waitFor(() => {
      expect(parseBtn).not.toBeDisabled();
    });
    fireEvent.click(parseBtn);

    await waitFor(() => {
      expect(screen.getByText(/wf-parsed999/i)).toBeInTheDocument();
    });

    // 7. Solver & Pipeline Diagnostics appear directly in the BoL & Diagnostics panel
    expect(screen.getByText(/Solver & Pipeline Diagnostics/i)).toBeInTheDocument();
    expect(screen.getByText(/Temporal-GATv2/i)).toBeInTheDocument();
  });

  it('displays Z3 infeasibility alert when all corridor routes fail constraints', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.includes('/corridor/topology')) {
          return Promise.resolve(new Response(JSON.stringify(FALLBACK_TOPOLOGY), { status: 200 }));
        }
        if (url.includes('/scenarios')) {
          return Promise.resolve(new Response(JSON.stringify(FALLBACK_SCENARIOS), { status: 200 }));
        }
        if (url.includes('/solve')) {
          return Promise.resolve(
            new Response(
              JSON.stringify({ detail: 'No feasible route satisfies 2°C ceiling at 120h Hormuz choke' }),
              { status: 422 }
            )
          );
        }
        return Promise.resolve(new Response('{}', { status: 404 }));
      })
    );
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        /Z3 Regulatory \/ SLA Infeasibility: No feasible route/i
      );
    });
  });

  it('displays accessible alert banner when gateway returns an error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response('Bad Gateway', { status: 502 })))
    );
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/Gateway returned 502/i);
    });
  });

  it('renders Corridor Studio homepage UI/UX with lazy stock videos, interactive capability tabs, and Console Only toggle', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.includes('/corridor/topology')) {
          return Promise.resolve(new Response(JSON.stringify(FALLBACK_TOPOLOGY), { status: 200 }));
        }
        if (url.includes('/scenarios')) {
          return Promise.resolve(new Response(JSON.stringify(FALLBACK_SCENARIOS), { status: 200 }));
        }
        if (url.includes('/solve')) {
          return Promise.resolve(new Response('{}', { status: 404 }));
        }
        return Promise.resolve(new Response('{}', { status: 404 }));
      })
    );

    window.history.pushState({}, '', '/');
    const { container } = render(<App />);

    expect(container.querySelector('#live-command-center')).toBeNull();
    expect(screen.getByText('ParetoLane.')).toBeInTheDocument();
    expect(
      screen.getAllByText(/The Autonomous Cargo Rerouting & Customs Engine/i).length
    ).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole('heading', { level: 1, name: /Unmatched/i })).toBeInTheDocument();

    const tablist = screen.getByRole('tablist', { name: 'Engine capability selector' });
    expect(tablist).toBeInTheDocument();
    const prunerTab = screen.getByRole('tab', { name: '02. PyG Graph Warm-Start Pruner' });
    fireEvent.click(prunerTab);
    expect(prunerTab).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('0.17 ms Variable Pruning')).toBeInTheDocument();

    const videos = Array.from(container.querySelectorAll('video'));
    expect(videos).toHaveLength(3);
    for (const video of videos) {
      expect(video.getAttribute('loading')).toBe('lazy');
      expect(video.getAttribute('preload')).toBe('none');
      expect(Number(video.getAttribute('width'))).toBeGreaterThan(0);
      expect(Number(video.getAttribute('height'))).toBeGreaterThan(0);
    }

    const consoleToggle = screen.getByRole('button', { name: 'Console Only' });
    expect(consoleToggle).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(consoleToggle);

    expect(window.location.pathname).toBe('/twin');
    expect(container.querySelector('#live-command-center')).not.toBeNull();
    expect(container.querySelector('.ds-hero')).toBeNull();

    const fullToggle = screen.getByRole('button', { name: 'Full Experience' });
    expect(fullToggle).toHaveAttribute('aria-pressed', 'true');
    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
  });
});
