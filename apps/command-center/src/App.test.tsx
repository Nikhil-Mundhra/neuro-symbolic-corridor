import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { FALLBACK_SCENARIOS, FALLBACK_TOPOLOGY } from './data/fallbackData';
import { CorridorMap } from './components/CorridorMap';
import App from './App';

// Mock DeckGL WebGL canvas for jsdom
vi.mock('@deck.gl/react', () => ({
  default: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="mock-deckgl">{children}</div>
  ),
}));

class MockEventSource {
  addEventListener = vi.fn();
  close = vi.fn();
  onerror: (() => void) | null = null;
}

beforeEach(() => {
  vi.stubGlobal('EventSource', MockEventSource);
  vi.stubGlobal('CSS', { supports: () => true });
  HTMLDialogElement.prototype.showModal = vi.fn();
  HTMLDialogElement.prototype.close = vi.fn();

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
  it('renders DeckGL stage and switches view mode buttons', () => {
    render(
      <CorridorMap
        nodes={FALLBACK_TOPOLOGY.nodes}
        edges={[]}
        solution={null}
        hormuzDelayHours={72}
        jebelAliDelayHours={24}
      />
    );
    expect(screen.getByTestId('mock-deckgl')).toBeInTheDocument();
    const eurasiaBtn = screen.getByRole('button', { name: /India → UAE → EU Corridor/i });
    fireEvent.click(eurasiaBtn);
    expect(eurasiaBtn).toHaveClass('active');
  });
});

describe('App', () => {
  it('bootstraps, solves, opens customs dialog, and dispatches reroute', async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(/wf-test123/i)).toBeInTheDocument();
    });

    expect(screen.getByText(/\$1,850,000/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Inspect Customs JSON/i }));
    expect(HTMLDialogElement.prototype.showModal).toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /Approve & Dispatch Reroute/i }));
    await waitFor(() => {
      expect(screen.getByText(/Dispatched to Bonded Corridor/i)).toBeInTheDocument();
    });
  });
});
