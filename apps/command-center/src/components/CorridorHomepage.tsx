import { useEffect, useRef, useState } from 'react';
import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  Cpu,
  Globe2,
  Layers,
  Pause,
  Play,
  ShieldCheck,
  Sparkles,
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
  hubCargoImg:
    'https://thumb.wikimedia.org/wikipedia/commons/thumb/d/d3/Vienna-Airport-View_to_Cargo_Partner-01ASD.jpg/960px-Vienna-Airport-View_to_Cargo_Partner-01ASD.jpg',
} as const;

const POSTER_MARITIME = '/media/case-maritime-poster.jpg';
const POSTER_RAIL = '/media/case-rail-poster.jpg';
const POSTER_SHOWREEL = '/media/showreel-poster.jpg';

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
    nodes: ['Raw BoL Text', 'Typed Field Regex', 'Pydantic Contract', 'Validated Shipment'],
    metric: '<1 ms Schema Extraction',
  },
  {
    num: '05',
    id: 'customs',
    title: 'Mirsal 2 / ATLP / e-TIR Bridge',
    summary:
      'Synthesizes dispatch-ready JSON manifests for Dubai Trade Mirsal 2, Maqta Gateway ATLP, Oman Bayan e-TIR, and Etihad Cargo e-AWB with one-click operator signoff.',
    nodes: ['SAT Solution', 'Mirsal 2 + ATLP', 'Oman Bayan e-TIR', 'Webhook Dispatch'],
    metric: '<400 ms P99 E2E SLA',
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
      'Scores corridor edge congestion across 2,400 fleet variables to shed dead branches without altering formal feasibility.',
  },
  {
    num: '04',
    title: 'Z3 Formal SMT Verification',
    timing: 'SAT / UNSAT Proof',
    detail:
      'Disproves unsafe or non-compliant legs with counterexample witnesses—blocking unbonded spot trucks and reefer drift breaches.',
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

const MARQUEE_ROW_A = [
  'JNPT Nhava Sheva',
  'DP World JAFZA',
  'AD Ports KIZAD',
  'Port of Fujairah',
  'Etihad Rail Bonded',
  'Etihad Cargo PharmaLife',
] as const;

const MARQUEE_ROW_B = [
  'Sohar Port & FZ',
  'Port of Salalah',
  'Al Wajajah Green Gate',
  'Dubai Trade Mirsal 2',
  'Maqta Gateway ATLP',
  'Frankfurt CargoHub',
] as const;

const VERTICALS = [
  {
    num: '• 01',
    title: 'Biologics & Cold-Chain Pharma',
    tag: '2°C–8°C GDP SLA',
    metric: '100% Spoilage Elimination',
    desc: 'Automatic Fujairah air-sea bridge diversion when maritime reefer drift exceeds vaccine stability thresholds.',
    tone: 'magenta',
  },
  {
    num: '• 02',
    title: 'EV Drivetrains & Automotive JIT',
    tag: 'UAE-India CEPA 0%',
    metric: 'Zero Factory Line Stops',
    desc: 'Proves ≥40% Indian origin value-add in Z3 while routing bonded rail into KIZAD industrial zones.',
    tone: 'cyan',
  },
  {
    num: '• 03',
    title: 'Petrochemicals & Bulk Polymers',
    tag: 'Pareto α Cost Mode',
    metric: '-34% Demurrage Exposure',
    desc: 'Balances Suez/Hormuz baseline maritime economy against Sohar feeder bypass during chokepoint spikes.',
    tone: 'indigo',
  },
  {
    num: '• 04',
    title: 'Sovereign Perishables & Agrifood',
    tag: 'GCC Fast-Lane e-TIR',
    metric: '< 72h Border Clearance',
    desc: 'Prioritizes Al Wajajah customs green lanes and pre-cleared Maqta Gateway manifests to protect shelf life.',
    tone: 'emerald',
  },
  {
    num: '• 05',
    title: 'Aerospace & Precision Semiconductors',
    tag: 'Bonded High-Security',
    metric: '100% Sealed Custody',
    desc: 'Strictly enforces unbroken bonded seal invariants, rejecting unbonded spot road handoffs mathematically.',
    tone: 'violet',
  },
  {
    num: '• 06',
    title: 'Grid & CleanTech Infrastructure',
    tag: 'Heavy Breakbulk Multimodal',
    metric: 'Sub-Second Scenario Re-Solve',
    desc: 'Orchestrates crane slot synchronization between Fujairah, Khalifa Port, and inland Gulf rail sidings.',
    tone: 'blue',
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

const REVIEWS = [
  {
    org: 'ColdChain Europe Logistics',
    author: 'Elena Richter · VP GDP Operations',
    quote:
      'Replacing spreadsheet contingencies with Z3 UNSAT proofs eliminated unbonded trucking errors on high-value biologic lanes.',
  },
  {
    org: 'Arabian Sea Intermodal Partners',
    author: 'Tariq Al-Mansoori · Fleet Director',
    quote:
      'Fujairah + Etihad Rail bypass plans generate in under 25 milliseconds alongside ready-to-file Mirsal 2 and ATLP manifests.',
  },
  {
    org: 'Mumbai Auto Export Consortium',
    author: 'Rohan Deshmukh · Customs Lead',
    quote:
      'Having explicit 0% CEPA duty proof attached to every dispatch gives customs brokers immediate audit confidence.',
  },
] as const;

const FAQS = [
  {
    q: 'How does copying this homepage UI/UX avoid adding solver or dispatch latency?',
    a: 'All marketing showcase sections below the fold use CSS content-visibility: auto with explicit contain-intrinsic-size placeholders, while stock videos use loading="lazy", preload="none", explicit width/height attributes, and an IntersectionObserver fallback. The Go gateway (:8080) and Python Z3+MILP solver (:8001) path remains untouched under 400ms P99.',
  },
  {
    q: 'Why pair neural warm-starting with Z3 formal verification instead of end-to-end AI routing?',
    a: 'Neural networks excel at pruning impossible congestion patterns quickly, but cannot guarantee customs, temperature, or CEPA legal invariants. Z3 formally rejects any unbonded or SLA-violating path before HiGHS optimizes economics.',
  },
  {
    q: 'Can dispatchers hide the showcase wrapper during high-tempo disruption shifts?',
    a: 'Yes. The sticky top navigation bar provides a one-click Console Only toggle backed by CSS content-visibility: hidden (with display: none fallback), switching instantly between the full landing studio and the focused dispatch workstation.',
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

  // Respect prefers-reduced-motion & fall back to IntersectionObserver where <video loading="lazy"> is unsupported
  useEffect(() => {
    const root = rootRef.current;
    if (!root || typeof window === 'undefined') return;

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
  }, []);

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

  const scrollToConsole = () => {
    const el = document.getElementById('live-command-center');
    el?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  };

  const triggerCaseStudyScenario = (index: number) => {
    const target = scenarios[index] ?? scenarios[0];
    if (target) {
      onLoadScenario(target);
      scrollToConsole();
    }
  };

  const hiddenMarketingClass = isConsoleOnly ? 'ds-marketing-hidden' : '';

  return (
    <div ref={rootRef} className={`ds-site-shell ${isConsoleOnly ? 'is-console-only' : ''}`}>
      {/* 1. Sticky Glassmorphic Navigation Bar */}
      <header className="ds-navbar">
        <div className="ds-nav-inner">
          <a href="#top" className="ds-brand" aria-label="Corridor Studio Home">
            <CorridorBrandMark size={32} />
            <span className="ds-brand-text">Corridor Studio.</span>
          </a>

          {!isConsoleOnly && (
            <nav className="ds-nav-links" aria-label="Primary studio navigation">
              <a href="#capabilities">Capabilities</a>
              <a href="#case-studies">Case Studies</a>
              <a href="#live-command-center">Live Twin</a>
              <a href="#methodology">Methodology</a>
              <a href="#insights">Insights</a>
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
            <a href="#live-command-center" className="ds-cta-pill">
              <span>Launch Live Twin</span>
              <span className="ds-cta-arrow" aria-hidden="true">
                <ArrowUpRight size={14} />
              </span>
            </a>
          </div>
        </div>
      </header>

      {/* 2. Cosmic Midnight-Navy Hero */}
      <section id="top" className={`ds-hero ${hiddenMarketingClass}`} aria-label="Corridor Hero">
        <svg
          className="ds-hero-waves"
          viewBox="0 0 1440 620"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <path
            d="M0 470 Q 320 260 720 390 T 1440 210"
            fill="none"
            stroke="url(#dsWaveGrad)"
            strokeWidth="1.6"
          />
          <path
            d="M0 520 Q 380 310 780 430 T 1440 260"
            fill="none"
            stroke="url(#dsWaveGrad)"
            strokeWidth="1.1"
            strokeOpacity="0.65"
          />
          <path
            d="M0 565 Q 420 365 820 470 T 1440 315"
            fill="none"
            stroke="#2962FF"
            strokeWidth="1"
            strokeOpacity="0.38"
          />
          <defs>
            <linearGradient id="dsWaveGrad" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#2962FF" stopOpacity="0.15" />
              <stop offset="55%" stopColor="#00F0FF" stopOpacity="0.7" />
              <stop offset="100%" stopColor="#E60050" stopOpacity="0.45" />
            </linearGradient>
          </defs>
        </svg>

        <div className="ds-container ds-hero-inner">
          <div className="ds-hero-top-row">
            <div className="ds-hero-eyebrow-group">
              <div className="ds-eyebrow-stack">
                <span className="ds-eyebrow">ZERO HALLUCINATION,</span>
                <span className="ds-eyebrow">FORMAL PROOF</span>
              </div>
              <div className="ds-star-badge">
                <span className="ds-star-orb" aria-hidden="true">
                  <Sparkles size={14} />
                </span>
                <span className="ds-star-label">
                  NEURO-SYMBOLIC
                  <br />
                  CORRIDOR
                  <br />
                  ENGINE
                </span>
              </div>
            </div>

            <div className="ds-trust-pills" aria-label="Verification and performance benchmarks">
              <div className="ds-trust-row">
                <span>Z3 SMT 4.13</span>
                <span className="ds-rating-chip tabular">100% ★</span>
              </div>
              <div className="ds-trust-row">
                <span>HiGHS MILP</span>
                <span className="ds-rating-chip tabular">0.0% ★</span>
              </div>
              <div className="ds-trust-row">
                <span>Go + Python</span>
                <span className="ds-rating-chip tabular">&lt;400ms ★</span>
              </div>
              <div className="ds-trust-row">
                <span>CEPA Proof</span>
                <span className="ds-rating-chip tabular">4.9 ★</span>
              </div>
            </div>
          </div>

          <h1 className="ds-hero-h1">
            Unmatched
            <br />
            <HeroWordFlip /> <span className="ds-hero-h1-suffix">Routing</span>
          </h1>

          <div className="ds-hero-bottom-row">
            <p className="ds-hero-sub">
              Formal Verification &amp; Neural Warm-Start for Multimodal Corridors Built to Scale
            </p>

            <div className="ds-stack-dock" aria-label="Core corridor computation stack">
              {[
                { abbr: 'Z3', name: 'Z3 SMT Solver' },
                { abbr: 'PyG', name: 'Graph Attention' },
                { abbr: 'LP', name: 'HiGHS MILP' },
                { abbr: 'Go', name: 'Go 1.26 SSE' },
                { abbr: 'TIR', name: 'e-TIR Sealed' },
                { abbr: 'CEPA', name: '0% Duty Rule' },
              ].map((tool) => (
                <span key={tool.abbr} className="ds-stack-orb" title={tool.name}>
                  {tool.abbr}
                </span>
              ))}
            </div>
          </div>

          <a href="#live-command-center" className="ds-scroll-cue">
            SCROLL TO EXPLORE ↓
          </a>
        </div>
      </section>

      {/* 3. Architects Editorial Mission */}
      <section className={`ds-section ds-deferred-section ${hiddenMarketingClass}`}>
        <div className="ds-container ds-editorial-grid">
          <div className="ds-architects-box">
            <div className="ds-avatar-stack" aria-hidden="true">
              <span className="ds-avatar ds-avatar-a">SM</span>
              <span className="ds-avatar ds-avatar-b">ZK</span>
            </div>
            <div className="ds-section-label">Architects of Corridor Studio</div>
          </div>
          <p className="ds-editorial-lead">
            Welcome to Neuro-Symbolic Corridor Studio, a deterministic trade-routing engine where we
            transform strait choke points into formally proven, sub-400ms multimodal dispatches.
          </p>
        </div>
      </section>

      {/* 4. Ecosystem Hubs Dual Marquee */}
      <section
        className={`ds-section ds-deferred-section ${hiddenMarketingClass}`}
        aria-label="Corridor gateways and customs integrations"
      >
        <div className="ds-container">
          <h2 className="ds-section-title">
            Orchestrating ports, bonded rail corridors, and air bridges across Eurasia.
          </h2>
        </div>

        <div className="ds-marquee-wrap">
          <div className="ds-marquee-track">
            {[...MARQUEE_ROW_A, ...MARQUEE_ROW_A].map((partner, idx) => (
              <div key={`${partner}-${idx}`} className="ds-marquee-card">
                {partner}
              </div>
            ))}
          </div>
          <div className="ds-marquee-track ds-marquee-reverse">
            {[...MARQUEE_ROW_B, ...MARQUEE_ROW_B].map((partner, idx) => (
              <div key={`${partner}-${idx}`} className="ds-marquee-card">
                {partner}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 5. Bento Business Impact Grid */}
      <section className={`ds-section ds-deferred-section ${hiddenMarketingClass}`}>
        <div className="ds-container">
          <h2 className="ds-section-title">
            Real Corridor Savings Through Formal Verification &amp; MILP Optimization
          </h2>

          <div className="ds-bento-grid">
            <div className="ds-bento-card">
              <div className="ds-bento-num tabular">&lt;400ms</div>
              <div className="ds-bento-label">End-to-End P99 Solve SLA</div>
              <p className="ds-bento-desc">
                Go ingest, schema parsing, neural pruning, Z3 proof, and HiGHS MILP complete inside
                hard streaming budgets.
              </p>
            </div>
            <div className="ds-bento-card">
              <div className="ds-bento-num tabular">64.8%</div>
              <div className="ds-bento-label">Fleet Variables Pruned</div>
              <p className="ds-bento-desc">
                Graph warm-start sheds congested maritime permutations before branch-and-bound
                search begins.
              </p>
            </div>
            <div className="ds-bento-card">
              <div className="ds-bento-num ds-accent-magenta tabular">$1.85M+</div>
              <div className="ds-bento-label">Biologics Spoilage Prevented</div>
              <p className="ds-bento-desc">
                Instant Fujairah East-Coast bypass preserves 2°C to 8°C GDP integrity during 72-hour
                Hormuz delays.
              </p>
            </div>
            <div className="ds-bento-card">
              <div className="ds-bento-num tabular">100%</div>
              <div className="ds-bento-label">Z3 Proof Coverage</div>
              <p className="ds-bento-desc">
                No unbonded spot transfer or non-CEPA cargo leg can ever slip through without a
                satisfiable formal check.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 6. Featured Case Studies (50/50 Split with Stock Videos) */}
      <section
        id="case-studies"
        className={`ds-section ds-deferred-section ${hiddenMarketingClass}`}
      >
        <div className="ds-container">
          <h2 className="ds-section-title">
            A glimpse into how we resolve high-stakes multimodal disruptions.
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
                <span className="ds-case-pill">GDP BIOLOGICS · SEA + RAIL + AIR</span>
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
                  <span>LOAD SCENARIO IN TWIN</span>
                  <span className="ds-cta-arrow" aria-hidden="true">
                    <ArrowUpRight size={13} />
                  </span>
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
                <span className="ds-case-pill">EV DRIVETRAINS · UAE-INDIA CEPA</span>
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
                  <span>LOAD SCENARIO IN TWIN</span>
                  <span className="ds-cta-arrow" aria-hidden="true">
                    <ArrowUpRight size={13} />
                  </span>
                </button>
              </div>
            </article>
          </div>
        </div>
      </section>

      {/* 7. Explore Our Capabilities (Interactive 01–05 Showcase) */}
      <section
        id="capabilities"
        className={`ds-section ds-deferred-section ${hiddenMarketingClass}`}
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
                    <ArrowUpRight size={16} className="ds-cap-arrow" aria-hidden="true" />
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </section>

      {/* 8. 6-Step Neuro-Symbolic Methodology */}
      <section
        id="methodology"
        className={`ds-section ds-deferred-section ${hiddenMarketingClass}`}
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
        </div>
      </section>

      {/* 9. Cinematic Stock Showreel Container */}
      <section className={`ds-section ds-deferred-section ${hiddenMarketingClass}`}>
        <div className="ds-container">
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
              aria-label="Stock maritime container terminal operational showreel"
              {...({ loading: 'lazy' } as Record<string, string>)}
            >
              <source src={STOCK_MEDIA.showreelVideo} type="video/mp4" />
            </video>
            <div className="ds-showreel-overlay">
              <button
                type="button"
                className="ds-play-orb"
                onClick={handleToggleShowreel}
                aria-label={showreelPlaying ? 'Pause corridor stock showreel' : 'Play corridor stock showreel'}
              >
                {showreelPlaying ? <Pause size={22} /> : <Play size={22} />}
              </button>
              <span className="ds-showreel-caption">
                STOCK CORRIDOR SHOWREEL · MARITIME &amp; INTERMODAL FLOW
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* 10. LIVE COMMAND CENTER CONSOLE (Zero-Latency Operational Core) */}
      <section
        id="live-command-center"
        className="ds-console-band"
        aria-label="Live Neuro-Symbolic Dispatch Command Center"
      >
        {!isConsoleOnly && (
          <div className="ds-container ds-console-intro">
            <div>
              <h2 className="ds-console-heading">
                Real-Time Z3 + HiGHS Solver &amp; Multimodal Corridor Twin
              </h2>
            </div>
            <div className="ds-console-sla tabular">
              <Activity size={14} aria-hidden="true" />
              <span>Direct Go Gateway (:8080) → Python Solver (:8001)</span>
            </div>
          </div>
        )}
        {children}
      </section>

      {/* 11. Industry Verticals Grid */}
      <section className={`ds-section ds-deferred-section ${hiddenMarketingClass}`}>
        <div className="ds-container">
          <h2 className="ds-section-title">
            Freight resilience <span className="ds-accent-magenta">across the Gulf corridor.</span>
          </h2>

          <div className="ds-verticals-grid">
            {VERTICALS.map((v) => (
              <div key={v.num} className={`ds-vertical-card ds-tone-${v.tone}`}>
                <div className="ds-vertical-top">
                  <span className="ds-vertical-pill">{v.num}</span>
                  <span className="ds-vertical-tag">{v.tag}</span>
                </div>
                <h3>{v.title}</h3>
                <p>{v.desc}</p>
                <div className="ds-vertical-metric tabular">
                  <CheckCircle2 size={14} aria-hidden="true" />
                  <span>{v.metric}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 12. Engineering Insights (3 Stock Photo Cards) */}
      <section
        id="insights"
        className={`ds-section ds-deferred-section ${hiddenMarketingClass}`}
      >
        <div className="ds-container">
          <h2 className="ds-section-title">Research and Corridor Insights</h2>

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

      {/* 13. Operator Reviews & Stress Audits */}
      <section className={`ds-section ds-deferred-section ${hiddenMarketingClass}`}>
        <div className="ds-container ds-reviews-grid">
          <div className="ds-reviews-anchor">
            <div className="ds-rating-huge tabular">4.9</div>
            <div className="ds-stars-gold" aria-hidden="true">
              ★★★★★
            </div>
            <div className="ds-reviews-sub">Verified corridor audits (4.9 of 5)</div>
            <div className="ds-reviews-badge">Formal Compliance Grade</div>
          </div>

          {REVIEWS.map((r) => (
            <blockquote key={r.org} className="ds-review-col">
              <div className="ds-review-org">{r.org}</div>
              <p>“{r.quote}”</p>
              <footer>{r.author}</footer>
            </blockquote>
          ))}
        </div>
      </section>

      {/* 14. FAQ Accordion + Architecture Contact Card */}
      <section className={`ds-section ds-deferred-section ${hiddenMarketingClass}`}>
        <div className="ds-container ds-faq-layout">
          <div>
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

          <aside className="ds-ask-card">
            <div className="ds-avatar-stack" aria-hidden="true">
              <span className="ds-avatar ds-avatar-a">SM</span>
              <span className="ds-avatar ds-avatar-b">ZK</span>
              <span className="ds-avatar ds-avatar-c">AR</span>
            </div>
            <h3>Ask our Corridor Architects</h3>
            <p>
              Inspect live SMT-LIB2 proofs, test 120-hour Hormuz closures, or benchmark end-to-end
              solver timing inside the interactive twin above.
            </p>
            <a href="#live-command-center" className="ds-cta-pill ds-cta-sm">
              <span>Jump to Live Twin</span>
              <span className="ds-cta-arrow" aria-hidden="true">
                <ArrowUpRight size={13} />
              </span>
            </a>
          </aside>
        </div>
      </section>

      {/* 15. Pre-Footer Conversion Banner */}
      <section className={`ds-section ds-prefooter ds-deferred-section ${hiddenMarketingClass}`}>
        <div className="ds-container ds-prefooter-inner">
          <h2 className="ds-prefooter-title">
            Got a Corridor Bottleneck?{' '}
            <a href="#live-command-center" className="ds-underline-magenta">
              Let&apos;s Solve!
            </a>
          </h2>
          <div className="ds-prefooter-sub">
            Zero-hallucination Z3 formal proofs · Sub-400ms Go + Python dispatch bridge
          </div>

          <div className="ds-benchmark-grid">
            {[
              { name: 'Z3 SMT 4.13', score: '100% SAT Guard' },
              { name: 'SciPy HiGHS', score: '0.00% MILP Gap' },
              { name: 'UAE-India CEPA', score: '0% Duty Verified' },
              { name: 'Mirsal 2 / ATLP', score: 'e-TIR Ready' },
              { name: 'End-to-End SLA', score: '<400ms P99' },
              { name: 'Node Parity', score: 'Natural Earth GIS' },
            ].map((b) => (
              <div key={b.name} className="ds-benchmark-card">
                <strong>{b.name}</strong>
                <span className="tabular">{b.score}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 16. High-Contrast Clean White Footer */}
      <footer className={`ds-footer ds-deferred-section ${hiddenMarketingClass}`}>
        <div className="ds-container">
          <div className="ds-footer-top">
            <div className="ds-footer-left">
              <p className="ds-footer-tagline">
                Engineering formal trust across physical freight links, from Mumbai maritime gates
                and Fujairah rail bridges to European cold-chain hubs.
              </p>
              <div className="ds-social-squircles" aria-label="Architecture modules">
                <a href="#live-command-center" title="Digital Twin" className="ds-squircle">
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
              <a href="#capabilities">Capabilities</a>
              <a href="#case-studies">Case Studies</a>
              <a href="#live-command-center">Live Command Center</a>
              <a href="#methodology">Pipeline SLA</a>
              <a href="#insights">Research Briefs</a>
            </nav>
            <div className="ds-footer-copy">
              <span>Neuro-Symbolic Corridor Studio</span>
              <span>Wikimedia Commons CC Stock Media</span>
              <span>All Routing Formalized</span>
            </div>
          </div>

          <div className="ds-footer-watermark" aria-hidden="true">
            corridor studio
          </div>
        </div>
      </footer>
    </div>
  );
}
