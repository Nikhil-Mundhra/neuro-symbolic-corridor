import { useEffect, useRef, useState } from 'react';
import {
  ArrowRight,
  CheckCircle2,
  ChevronRight,
  Cpu,
  Globe2,
  Layers,
  Pause,
  Play,
  ShieldCheck,
  Terminal,
} from 'lucide-react';
import type { ScenarioPreset } from '../types';
import { CorridorBrandMark } from './CorridorBrandMark';

export type HomepageViewMode = 'full' | 'console';

interface CorridorHomepageProps {
  scenarios: ScenarioPreset[];
  viewMode: HomepageViewMode;
  onToggleViewMode: (mode: HomepageViewMode) => void;
  onLoadScenario: (preset: ScenarioPreset) => void;
  children: React.ReactNode;
}

const HERO_FLIP_WORDS = ['Z3+MILP', 'Cold-Chain', 'CEPA 0%', 'Bonded Rail'] as const;

const STOCK_MEDIA = {
  maritimeVideo: '/media/case-maritime.mp4',
  railVideo: '/media/case-rail.mp4',
  showreelVideo: '/media/showreel.mp4',
  airCargoImg: '/media/insight-air-cargo.jpg',
  coldChainImg: '/media/insight-cold-chain.jpg',
  portCranesImg: '/media/insight-port-cranes.jpg',
} as const;

const POSTER_MARITIME = '/media/case-maritime-poster.jpg';
const POSTER_RAIL = '/media/case-rail-poster.jpg';
const POSTER_SHOWREEL = '/media/showreel-poster.jpg';

const SLA_STAGES = [
  { stage: '01. Go Gateway Ingest', role: 'SSE stream & durable state', budget: '< 10 ms' },
  { stage: '02. Guided BoL Extraction', role: 'Strict Pydantic schema lock', budget: '< 25 ms' },
  { stage: '03. T-GNN Variable Pruning', role: 'Congestion arc masking', budget: '< 30 ms' },
  { stage: '04. Z3 SMT + HiGHS MILP', role: 'Formal SAT check & optimal duals', budget: '< 200 ms' },
  { stage: '05. Customs Payload Bridge', role: 'Mirsal 2, ATLP, Bayan e-TIR', budget: '< 50 ms' },
] as const;

const CAPABILITIES = [
  {
    num: '01',
    id: 'z3',
    title: 'Z3 SMT Regulatory Compiler',
    summary:
      'Every candidate route is compiled into symbolic QF_LRA constraints validating GDP thermal ceilings, GCC bonded e-TIR seals, and UAE-India CEPA 40% value-add tariff proofs before solver selection.',
    nodes: ['BoL Schema', 'Z3 QF_LRA Check', 'CEPA + e-TIR Guard', 'SAT Certificate'],
    metric: '0% Hallucinated Routes',
  },
  {
    num: '02',
    id: 'gnn',
    title: 'PyG Graph Warm-Start Pruner',
    summary:
      'A graph attention encoder scores choked arcs across Hormuz and Jebel Ali in sub-millisecond time, pruning 64.8% of infeasible fleet-scale binary variables prior to branch-and-bound.',
    nodes: ['Congestion Tensor', 'PyG Attention', '64.8% Arc Mask', 'Pruned MILP Graph'],
    metric: '0.17 ms Variable Pruning',
  },
  {
    num: '03',
    id: 'milp',
    title: 'SciPy-HiGHS Pareto MILP Engine',
    summary:
      'Solves globally optimal cost-vs-latency tradeoffs across sea, bonded rail, green-corridor truck, and PharmaLife air legs with exact dual bounds and tunable Pareto α weight.',
    nodes: ['SAT Route Set', 'HiGHS Simplex', 'Pareto α Tradeoff', '0.00% Opt Gap'],
    metric: '14.9 ms Exact Optimum',
  },
  {
    num: '04',
    id: 'bol',
    title: 'Schema-Locked BoL Extractor',
    summary:
      'Extracts HS codes, cargo value, origin value-add %, and reefer SLA bounds from raw bills of lading directly into typed Pydantic structures without free-form text generation.',
    nodes: ['Raw BoL Text', 'Typed Field Parser', 'Pydantic Contract', 'Validated Shipment'],
    metric: '< 1 ms Schema Extraction',
  },
  {
    num: '05',
    id: 'customs',
    title: 'Mirsal 2 / ATLP / e-TIR Bridge',
    summary:
      'Synthesizes dispatch-ready JSON manifests for Dubai Trade Mirsal 2, Maqta Gateway ATLP, Oman Bayan e-TIR, and Etihad Cargo e-AWB with one-click operator signoff.',
    nodes: ['SAT Solution', 'Mirsal 2 + ATLP', 'Oman Bayan e-TIR', 'Webhook Dispatch'],
    metric: '< 400 ms P99 E2E SLA',
  },
] as const;

const METHODOLOGY_STEPS = [
  {
    num: '01',
    title: 'Gateway Stream Ingest',
    timing: '< 10 ms · Go 1.26',
    detail:
      'High-concurrency Go gateway ingests carrier alerts, Strait of Hormuz delay spikes, and BoL triggers with durable workflow checkpoints.',
  },
  {
    num: '02',
    title: 'Typed BoL Schema Parsing',
    timing: '< 25 ms · Pydantic',
    detail:
      'Locks unstructured shipping manifests into deterministic HS code, reefer excursion, CEPA origin %, and SLA contracts.',
  },
  {
    num: '03',
    title: 'Neural Warm-Start Pruning',
    timing: '< 30 ms · Graph Neural',
    detail:
      'Scores corridor edge congestion across fleet variables to shed dead branches without altering formal feasibility.',
  },
  {
    num: '04',
    title: 'Z3 Formal SMT Verification',
    timing: 'SAT / UNSAT Proof',
    detail:
      'Disproves unsafe or non-compliant legs with counterexample witnesses, blocking unbonded spot trucks and reefer drift breaches.',
  },
  {
    num: '05',
    title: 'HiGHS MILP Optimization',
    timing: '< 200 ms · Exact Duals',
    detail:
      'Computes minimum economic cost across freight, demurrage, spoilage risk, and duty exposure at 0.00% optimality gap.',
  },
  {
    num: '06',
    title: 'Customs Payload & SSE Push',
    timing: '< 50 ms · Human Signoff',
    detail:
      'Streams verified route deltas over Server-Sent Events and generates Mirsal 2, ATLP, and Bayan e-TIR payloads for dispatch approval.',
  },
] as const;

const GATEWAY_NODES = [
  { code: 'INNSA', name: 'JNPT Nhava Sheva', zone: 'IN-CEPA-ORIGIN' },
  { code: 'AEFJR', name: 'Port of Fujairah', zone: 'AE-FUJAIRAH-CUSTOMS' },
  { code: 'AEKHL', name: 'Khalifa Port (KIZAD)', zone: 'AE-AUH-KIZAD' },
  { code: 'AEJEA', name: 'Jebel Ali (JAFZA)', zone: 'AE-DXB-JAFZA' },
  { code: 'OMSOH', name: 'Sohar Port & FZ', zone: 'OM-SOHAR-FZ' },
  { code: 'AEWAJ', name: 'Al Wajajah Gate', zone: 'GCC-GREEN-CORRIDOR' },
  { code: 'AEAUH', name: 'Etihad Cargo AUH', zone: 'AE-AUH-AIR-BONDED' },
  { code: 'EUFRA', name: 'Frankfurt / Rotterdam', zone: 'EU-ICS2-CLEARANCE' },
] as const;

const VERTICALS = [
  {
    num: '01',
    title: 'Biologics & Cold-Chain Pharma',
    tag: '2°C to 8°C GDP SLA',
    metric: 'Thermal drift protection',
    desc: 'Automatic Fujairah air-sea bridge diversion when maritime reefer drift exceeds vaccine stability thresholds.',
  },
  {
    num: '02',
    title: 'EV Drivetrains & Automotive JIT',
    tag: 'UAE-India CEPA 0%',
    metric: 'Bilateral origin proof',
    desc: 'Proves >= 40% Indian origin value-add in Z3 while routing bonded rail into KIZAD industrial zones.',
  },
  {
    num: '03',
    title: 'Petrochemicals & Bulk Polymers',
    tag: 'Pareto α Cost Mode',
    metric: 'Demurrage mitigation',
    desc: 'Balances Suez/Hormuz baseline maritime economy against Sohar feeder bypass during chokepoint spikes.',
  },
  {
    num: '04',
    title: 'Sovereign Perishables & Agrifood',
    tag: 'GCC Fast-Lane e-TIR',
    metric: 'Pre-cleared green lanes',
    desc: 'Prioritizes Al Wajajah customs green lanes and pre-cleared Maqta Gateway manifests to protect shelf life.',
  },
  {
    num: '05',
    title: 'Aerospace & Precision Semiconductors',
    tag: 'Bonded High-Security',
    metric: 'Unbroken seal custody',
    desc: 'Strictly enforces unbroken bonded seal invariants, rejecting unbonded spot road handoffs mathematically.',
  },
  {
    num: '06',
    title: 'Grid & CleanTech Infrastructure',
    tag: 'Heavy Breakbulk Multimodal',
    metric: 'Sub-second re-solve',
    desc: 'Orchestrates crane slot synchronization between Fujairah, Khalifa Port, and inland Gulf rail sidings.',
  },
] as const;

const INSIGHTS = [
  {
    img: STOCK_MEDIA.coldChainImg,
    alt: 'Temperature-controlled pharmaceutical cold-chain logistics facility',
    category: 'Formal Methods',
    date: 'Q4 Engineering Brief',
    title: 'Zero Regulatory Hallucination: Compiling CEPA Tariff Rules into Z3 SMT Proofs',
  },
  {
    img: STOCK_MEDIA.portCranesImg,
    alt: 'Container port ship-to-shore gantry cranes along deep-water terminal',
    category: 'Corridor Economics',
    date: 'Architecture Note',
    title: 'Cutting Strait of Hormuz Reroute Search Space by 64.8% with Neural Warm-Starts',
  },
  {
    img: STOCK_MEDIA.airCargoImg,
    alt: 'Widebody cargo freighter aircraft parked on ramp at Frankfurt hub',
    category: 'Multimodal Dispatch',
    date: 'Operations Playbook',
    title: 'Why Sea-Rail-Air Bridges Beat Pure Maritime Holding Costs for High-Value Biologics',
  },
] as const;

const FAQS = [
  {
    q: 'How does the showcase layer avoid adding latency to the live solver path?',
    a: 'All showcase sections below the live workstation use CSS content-visibility: auto with explicit contain-intrinsic-size placeholders, while media assets load lazily on intersection. The Go gateway (:8080) and Python Z3+MILP solver (:8001) pipeline remains isolated under its 400ms P99 SLA.',
  },
  {
    q: 'Why pair neural warm-starting with Z3 formal verification instead of end-to-end AI routing?',
    a: 'Graph neural encoders excel at pruning congested maritime permutations quickly, but cannot guarantee customs, temperature, or CEPA legal invariants. Z3 formally rejects any unbonded or SLA-violating path before HiGHS optimizes economics.',
  },
  {
    q: 'Can dispatchers hide the showcase wrapper during high-tempo disruption shifts?',
    a: 'Yes. The sticky top navigation bar provides a one-click Console Only toggle backed by CSS content-visibility: hidden (with display: none fallback), switching instantly between the full workstation view and the focused dispatch console.',
  },
  {
    q: 'Are all customs payloads and geographic map layers vendor-neutral?',
    a: 'Yes. The Command Center outputs JSON schemas aligned to Dubai Trade Mirsal 2, Maqta Gateway ATLP, Oman Bayan e-TIR, and Etihad Cargo e-AWB, while the SVG map pairs bundled Natural Earth coastlines with switchable Esri, OpenStreetMap, or offline vector layers.',
  },
] as const;

/** Isolated leaf component so word flip never triggers re-renders on the solver console */
function HeroWordFlip() {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    ) {
      return;
    }
    const id = window.setInterval(() => {
      setIndex((prev) => (prev + 1) % HERO_FLIP_WORDS.length);
    }, 2400);
    return () => window.clearInterval(id);
  }, []);

  return (
    <span className="ds-hero-flip" aria-live="off">
      {HERO_FLIP_WORDS[index]}
    </span>
  );
}

export function CorridorHomepage({
  scenarios,
  viewMode,
  onToggleViewMode,
  onLoadScenario,
  children,
}: CorridorHomepageProps) {
  const [activeCapIndex, setActiveCapIndex] = useState(0);
  const [showreelPlaying, setShowreelPlaying] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const showreelVideoRef = useRef<HTMLVideoElement | null>(null);

  const isConsoleOnly = viewMode === 'console';
  const activeCap = CAPABILITIES[activeCapIndex];

  useEffect(() => {
    const root = rootRef.current;
    if (!root || typeof window === 'undefined' || isConsoleOnly) return;

    const reducedMotionQuery = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    const syncReducedMotion = (prefersReduced: boolean) => {
      for (const video of root.querySelectorAll<HTMLVideoElement>(
        'video[autoplay], video[data-autoplay="true"]'
      )) {
        if (prefersReduced) {
          video.removeAttribute('autoplay');
          video.pause?.();
        }
      }
    };
    if (reducedMotionQuery) {
      syncReducedMotion(reducedMotionQuery.matches);
    }

    const onMotionChange = (event: MediaQueryListEvent) => syncReducedMotion(event.matches);
    reducedMotionQuery?.addEventListener?.('change', onMotionChange);

    const supportsLazyMedia =
      typeof HTMLMediaElement !== 'undefined' &&
      Object.hasOwn(HTMLMediaElement.prototype, 'loading');

    let observer: IntersectionObserver | null = null;
    if (typeof IntersectionObserver !== 'undefined') {
      const lazyVideos = root.querySelectorAll<HTMLVideoElement>('video[loading="lazy"]');
      const activateVideo = (media: HTMLVideoElement) => {
        const wantsAutoplay =
          media.dataset.autoplay === 'true' && !reducedMotionQuery?.matches;
        if (!supportsLazyMedia || wantsAutoplay) {
          if (!supportsLazyMedia) {
            if (media.dataset.src) {
              media.src = media.dataset.src;
              delete media.dataset.src;
            }
            for (const srcEl of media.querySelectorAll<HTMLSourceElement>('source[data-src]')) {
              if (srcEl.dataset.src) {
                srcEl.src = srcEl.dataset.src;
                delete srcEl.dataset.src;
              }
            }
          }
          const targetPreload = media.dataset.preload;
          media.preload =
            targetPreload === 'auto' || targetPreload === 'metadata' || targetPreload === ''
              ? targetPreload
              : 'metadata';
          media.load?.();
        }
        if (wantsAutoplay) {
          void media.play?.()?.catch?.(() => {});
        }
        observer?.unobserve(media);
      };

      observer = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            if (!entry.isIntersecting) continue;
            activateVideo(entry.target as HTMLVideoElement);
          }
        },
        { rootMargin: '200px 0px' }
      );

      for (const media of lazyVideos) {
        if (!media.dataset.preload && media.preload && media.preload !== 'none') {
          media.dataset.preload = media.preload;
        }
        media.preload = 'none';
        const rect = media.getBoundingClientRect?.();
        const isLaidOut = rect != null && rect.width > 0 && rect.height > 0;
        const inViewport =
          isLaidOut && rect.bottom >= -200 && rect.top <= (window.innerHeight || 0) + 200;
        if (inViewport && media.dataset.autoplay === 'true' && !reducedMotionQuery?.matches) {
          activateVideo(media);
        } else {
          observer.observe(media);
        }
      }
    }

    return () => {
      reducedMotionQuery?.removeEventListener?.('change', onMotionChange);
      observer?.disconnect();
    };
  }, [isConsoleOnly]);

  const handleToggleShowreel = () => {
    const vid = showreelVideoRef.current;
    if (!vid) return;
    if (vid.paused) {
      if (vid.readyState === 0) {
        vid.preload = 'auto';
        vid.load?.();
      }
      void vid.play?.()?.catch?.(() => {});
      setShowreelPlaying(true);
    } else {
      vid.pause?.();
      setShowreelPlaying(false);
    }
  };

  const openLiveTwin = () => {
    onToggleViewMode('console');
  };

  const triggerCaseStudyScenario = (index: number) => {
    const target = scenarios[index] ?? scenarios[0];
    if (target) {
      onLoadScenario(target);
    }
    openLiveTwin();
  };

  return (
    <div ref={rootRef} className={`ds-site-shell ${isConsoleOnly ? 'is-console-only' : ''}`}>
      {/* 1. Sticky Tactical Navigation Bar */}
      <header className="ds-navbar">
        <div className="ds-nav-inner">
          <a
            href={isConsoleOnly ? '/' : '#top'}
            className="ds-brand"
            aria-label="Corridor Studio Home"
            onClick={
              isConsoleOnly
                ? (e) => {
                    e.preventDefault();
                    onToggleViewMode('full');
                  }
                : undefined
            }
          >
            <CorridorBrandMark size={28} />
            <span className="ds-brand-text">Corridor Studio.</span>
          </a>

          {!isConsoleOnly && (
            <nav className="ds-nav-links" aria-label="Primary studio navigation">
              <a
                href="/twin"
                onClick={(e) => {
                  e.preventDefault();
                  openLiveTwin();
                }}
              >
                Live Twin
              </a>
              <a href="#capabilities">Capabilities</a>
              <a href="#case-studies">Case Studies</a>
              <a href="#methodology">Pipeline SLA</a>
              <a href="#insights">Briefs</a>
            </nav>
          )}

          <div className="ds-nav-actions">
            <button
              type="button"
              className="ds-mode-toggle"
              onClick={() => onToggleViewMode(isConsoleOnly ? 'full' : 'console')}
              aria-pressed={isConsoleOnly}
            >
              {isConsoleOnly ? 'Full Experience' : 'Console Only'}
            </button>
            <a
              href="/twin"
              className="ds-cta-pill"
              onClick={(e) => {
                e.preventDefault();
                openLiveTwin();
              }}
            >
              <span>Launch Live Twin</span>
              <ArrowRight size={14} aria-hidden="true" />
            </a>
          </div>
        </div>
      </header>

      {isConsoleOnly ? (
        /* Dedicated Live Digital Twin Page (/twin) */
        <section
          id="live-command-center"
          className="ds-console-band"
          aria-label="Live Neuro-Symbolic Dispatch Command Center"
        >
          {children}
        </section>
      ) : (
        <>
      {/* 2. Architectural Split Hero: Headline & Live Pipeline Contract */}
      <section id="top" className="ds-hero" aria-label="Corridor Hero">
        <div className="ds-container ds-hero-grid">
          <div className="ds-hero-copy">
            <h1 className="ds-hero-h1">
              Unmatched <HeroWordFlip />{' '}
              <span className="ds-hero-h1-suffix">Routing</span>
            </h1>
            <p className="ds-hero-sub">
              Deterministic multimodal rerouting and Z3 SMT compliance verification across the
              India, Oman, and UAE trade corridor.
            </p>
            <div className="ds-hero-actions">
              <a
                href="/twin"
                className="ds-cta-pill"
                onClick={(e) => {
                  e.preventDefault();
                  openLiveTwin();
                }}
              >
                <span>Open Live Twin</span>
                <ArrowRight size={14} aria-hidden="true" />
              </a>
              <a href="#capabilities" className="ds-secondary-link">
                Engine Architecture
              </a>
            </div>
          </div>

          <div className="ds-hero-contract" aria-label="Pipeline latency contract">
            <div className="ds-contract-head">
              <span>End-to-end solver contract</span>
              <span className="ds-contract-sla tabular">&lt; 400 ms P99</span>
            </div>
            <div className="ds-contract-rows">
              {SLA_STAGES.map((item) => (
                <div key={item.stage} className="ds-contract-row">
                  <div>
                    <strong>{item.stage}</strong>
                    <span>{item.role}</span>
                  </div>
                  <code className="tabular">{item.budget}</code>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* 4. Interactive Capabilities Showcase (01–05) */}
      <section
        id="capabilities"
        className="ds-section ds-deferred-section"
      >
        <div className="ds-container">
          <h2 className="ds-section-title">Explore our neuro-symbolic capabilities.</h2>

          <div className="ds-capabilities-grid">
            <div className="ds-capability-canvas" aria-live="polite">
              <div className="ds-cap-badge">{activeCap.metric}</div>
              <h3>
                {activeCap.num}. {activeCap.title}
              </h3>
              <p>{activeCap.summary}</p>
              <div className="ds-cap-flow">
                {activeCap.nodes.map((nodeLabel, idx) => (
                  <div key={nodeLabel} className="ds-cap-node-wrap">
                    <div className="ds-cap-node">
                      <Cpu size={14} aria-hidden="true" />
                      <span>{nodeLabel}</span>
                    </div>
                    {idx < activeCap.nodes.length - 1 && (
                      <span className="ds-cap-link" aria-hidden="true">
                        →
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div className="ds-capability-list" role="tablist" aria-label="Engine capability selector">
              {CAPABILITIES.map((cap, idx) => {
                const isActive = idx === activeCapIndex;
                return (
                  <button
                    key={cap.id}
                    type="button"
                    role="tab"
                    aria-selected={isActive}
                    className={`ds-capability-item ${isActive ? 'active' : ''}`}
                    onClick={() => setActiveCapIndex(idx)}
                  >
                    <span className="ds-cap-num tabular">{cap.num}.</span>
                    <span className="ds-cap-title">{cap.title}</span>
                    <ChevronRight size={16} className="ds-cap-arrow" aria-hidden="true" />
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </section>

      {/* 5. Featured Case Studies + Showreel (3 lazy <video> elements) */}
      <section
        id="case-studies"
        className="ds-section ds-deferred-section"
      >
        <div className="ds-container">
          <h2 className="ds-section-title">
            Resolving high-stakes multimodal disruptions with formal proofs.
          </h2>

          <div className="ds-case-stack">
            <article className="ds-case-card">
              <div className="ds-case-media">
                <video
                  key={STOCK_MEDIA.maritimeVideo}
                  muted
                  loop
                  playsInline
                  preload="none"
                  data-autoplay="true"
                  width={640}
                  height={360}
                  poster={POSTER_MARITIME}
                  aria-label="Stock maritime container terminal vessel berthing timelapse"
                  {...({ loading: 'lazy' } as Record<string, string>)}
                >
                  <source src={STOCK_MEDIA.maritimeVideo} type="video/mp4" />
                </video>
              </div>
              <div className="ds-case-body">
                <span className="ds-case-pill">GDP Biologics: Sea, Rail &amp; Air</span>
                <h3>Cipla JNPT → Fujairah Bypass → Etihad PharmaLife</h3>
                <p>
                  When Strait of Hormuz holding delays combine with active reefer thermal drift,
                  Z3 marks direct maritime routes UNSAT and shifts freight onto East-Coast UAE rail
                  and widebody cold-chain uplift.
                </p>
                <div className="ds-case-metrics tabular">
                  <span>-436h Transit</span>
                  <span>7.5 °C Arrival</span>
                  <span>$1.85M Protected</span>
                </div>
                <button
                  type="button"
                  className="ds-cta-pill ds-cta-sm"
                  onClick={() => triggerCaseStudyScenario(0)}
                >
                  <span>Load scenario in twin</span>
                  <ArrowRight size={13} aria-hidden="true" />
                </button>
              </div>
            </article>

            <article className="ds-case-card ds-case-reverse">
              <div className="ds-case-media">
                <video
                  key={STOCK_MEDIA.railVideo}
                  muted
                  loop
                  playsInline
                  preload="none"
                  data-autoplay="true"
                  width={640}
                  height={360}
                  poster={POSTER_RAIL}
                  aria-label="Stock intermodal freight train corridor footage"
                  {...({ loading: 'lazy' } as Record<string, string>)}
                >
                  <source src={STOCK_MEDIA.railVideo} type="video/mp4" />
                </video>
              </div>
              <div className="ds-case-body">
                <span className="ds-case-pill">EV Drivetrains: UAE-India CEPA</span>
                <h3>KIZAD Bonded Rail &amp; 46% Origin Value-Add Proof</h3>
                <p>
                  Validates strict 0% bilateral CEPA tariff eligibility across transshipment hops
                  while disqualifying unbonded spot trucking that would forfeit customs seals.
                </p>
                <div className="ds-case-metrics tabular">
                  <span>0% CEPA Duty</span>
                  <span>100% Sealed e-TIR</span>
                  <span>SAT Verified</span>
                </div>
                <button
                  type="button"
                  className="ds-cta-pill ds-cta-sm"
                  onClick={() => triggerCaseStudyScenario(1)}
                >
                  <span>Load scenario in twin</span>
                  <ArrowRight size={13} aria-hidden="true" />
                </button>
              </div>
            </article>
          </div>

          <div className="ds-showreel-frame">
            <video
              key={STOCK_MEDIA.showreelVideo}
              ref={showreelVideoRef}
              muted
              loop
              playsInline
              preload="none"
              data-autoplay="true"
              width={1280}
              height={540}
              poster={POSTER_SHOWREEL}
              onPlay={() => setShowreelPlaying(true)}
              onPause={() => setShowreelPlaying(false)}
              aria-label="Stock container port and freight rail operations showreel"
              {...({ loading: 'lazy' } as Record<string, string>)}
            >
              <source src={STOCK_MEDIA.showreelVideo} type="video/mp4" />
            </video>
            <div className="ds-showreel-bar">
              <span>Corridor Operations: Maritime &amp; Intermodal Flow</span>
              <button
                type="button"
                className="ds-play-btn"
                onClick={handleToggleShowreel}
                aria-label={showreelPlaying ? 'Pause corridor stock showreel' : 'Play corridor stock showreel'}
              >
                {showreelPlaying ? <Pause size={15} /> : <Play size={15} />}
                <span>{showreelPlaying ? 'Pause' : 'Play Reel'}</span>
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* 6. 6-Step Neuro-Symbolic Methodology & Active Gateways */}
      <section
        id="methodology"
        className="ds-section ds-deferred-section"
      >
        <div className="ds-container">
          <h2 className="ds-section-title">Inside our deterministic verification pipeline.</h2>

          <div className="ds-method-table">
            {METHODOLOGY_STEPS.map((step) => (
              <div key={step.num} className="ds-method-row">
                <span className="ds-method-num tabular">{step.num}.</span>
                <div className="ds-method-name">
                  <strong>{step.title}</strong>
                  <span className="tabular">{step.timing}</span>
                </div>
                <p className="ds-method-desc">{step.detail}</p>
              </div>
            ))}
          </div>

          <div className="ds-gateway-grid" aria-label="Corridor gateways and customs zones">
            {GATEWAY_NODES.map((g) => (
              <div key={g.code} className="ds-gateway-cell">
                <span className="ds-gateway-code mono">{g.code}</span>
                <strong>{g.name}</strong>
                <span className="ds-gateway-zone mono">{g.zone}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 7. Corridor Verticals & Engineering Briefs */}
      <section
        id="insights"
        className="ds-section ds-deferred-section"
      >
        <div className="ds-container">
          <h2 className="ds-section-title">Freight resilience across the Gulf corridor.</h2>

          <div className="ds-verticals-grid">
            {VERTICALS.map((v) => (
              <div key={v.num} className="ds-vertical-card">
                <div className="ds-vertical-top">
                  <span className="ds-vertical-pill tabular">{v.num}</span>
                  <span className="ds-vertical-tag">{v.tag}</span>
                </div>
                <h3>{v.title}</h3>
                <p>{v.desc}</p>
                <div className="ds-vertical-metric">
                  <CheckCircle2 size={14} aria-hidden="true" />
                  <span>{v.metric}</span>
                </div>
              </div>
            ))}
          </div>

          <h2 className="ds-section-title ds-sub-section-title">Research and Corridor Briefs</h2>
          <div className="ds-insights-grid">
            {INSIGHTS.map((post) => (
              <article key={post.title} className="ds-insight-card">
                <img
                  src={post.img}
                  alt={post.alt}
                  width={400}
                  height={225}
                  loading="lazy"
                  decoding="async"
                />
                <div className="ds-insight-meta">
                  <span>{post.category}</span>
                  <span>{post.date}</span>
                </div>
                <h3>{post.title}</h3>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* 8. Platform Architecture FAQ */}
      <section className="ds-section ds-deferred-section">
        <div className="ds-container">
          <h2 className="ds-section-title">Platform Architecture &amp; Operations</h2>

          <div className="ds-faq-list">
            {FAQS.map((item) => (
              <details key={item.q} className="ds-faq-item">
                <summary>{item.q}</summary>
                <div className="ds-faq-answer">{item.a}</div>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* 9. Unified Architectural Dark Footer */}
      <footer className="ds-footer ds-deferred-section">
        <div className="ds-container">
          <div className="ds-footer-top">
            <div className="ds-footer-left">
              <div className="ds-footer-brand">
                <CorridorBrandMark size={26} />
                <strong>Corridor Studio</strong>
              </div>
              <p className="ds-footer-tagline">
                Engineering formal trust across physical freight links, from Mumbai maritime gates
                and Fujairah rail bridges to European cold-chain hubs.
              </p>
              <div className="ds-social-squircles" aria-label="Architecture modules">
                <a
                  href="/twin"
                  title="Digital Twin"
                  className="ds-squircle"
                  onClick={(e) => {
                    e.preventDefault();
                    openLiveTwin();
                  }}
                >
                  <Globe2 size={16} />
                </a>
                <a href="#capabilities" title="Solver Core" className="ds-squircle">
                  <Cpu size={16} />
                </a>
                <a href="#methodology" title="Z3 Proofs" className="ds-squircle">
                  <ShieldCheck size={16} />
                </a>
                <a href="#case-studies" title="Corridor Layers" className="ds-squircle">
                  <Layers size={16} />
                </a>
                <a href="#insights" title="System Diagnostics" className="ds-squircle">
                  <Terminal size={16} />
                </a>
              </div>
            </div>

            <div className="ds-footer-offices">
              <div className="ds-office">
                <strong>UAE: KIZAD &amp; Fujairah Hub</strong>
                <span>Maqta Gateway ATLP, AD Ports &amp; Dubai Trade Mirsal 2 Bridge</span>
              </div>
              <div className="ds-office">
                <strong>Oman: Sohar &amp; Salalah Gateway</strong>
                <span>Al Wajajah Sealed e-TIR, Oman Bayan Green Corridor</span>
              </div>
              <div className="ds-office">
                <strong>India: JNPT Nhava Sheva</strong>
                <span>CEPA Origin Certificate Registry, Pharma GDP Cold-Chain</span>
              </div>
              <div className="ds-office">
                <strong>EU: Frankfurt &amp; Rotterdam</strong>
                <span>ICS2 Bonded Release, Active Thermal Chain Signoff</span>
              </div>
            </div>
          </div>

          <div className="ds-footer-bottom">
            <nav className="ds-footer-nav" aria-label="Footer navigation">
              <a
                href="/twin"
                onClick={(e) => {
                  e.preventDefault();
                  openLiveTwin();
                }}
              >
                Live Command Center
              </a>
              <a href="#capabilities">Capabilities</a>
              <a href="#case-studies">Case Studies</a>
              <a href="#methodology">Pipeline SLA</a>
              <a href="#insights">Research Briefs</a>
            </nav>
            <div className="ds-footer-copy">
              <span>Neuro-Symbolic Corridor Studio</span>
              <span>Formal Z3 Verification &amp; HiGHS MILP</span>
            </div>
          </div>
        </div>
      </footer>
        </>
      )}
    </div>
  );
}
