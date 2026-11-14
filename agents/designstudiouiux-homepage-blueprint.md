# Design Studio UI/UX (`https://www.designstudiouiux.com`) Reverse-Engineered Blueprint

Captured & reconstructed using `agents/reverse-engineer-anything/SKILL.md` (`morluto/rea`) runtime browser inspection of `https://www.designstudiouiux.com`.

## 1. Visual System & Tokens
- **Canvas Palette**: `#030718` (deep midnight obsidian navy) -> `#070c26` -> `#0b1238` alternating depth bands, transitioning cleanly at the footer into crisp high-contrast `#FFFFFF`.
- **Signature Accents**:
  - Electric Magenta (`#E60050` / `#E91E63`) for capsule CTAs, cycling H1 keyword, active service selector indicator, and underline emphasis.
  - Cyber Cyan (`#00F0FF`) & Cobalt Blue (`#2962FF`) for hero vector contours, star emblems, and live status dots.
- **Glass Surfaces**: Frosted translucent panels (`rgba(255, 255, 255, 0.04)`–`0.07`, `backdrop-filter: blur(16px)`), `1px solid rgba(255, 255, 255, 0.12)` hairline borders, and deep navy Bento tiles (`#0d153a`).
- **Typography**: Clean grotesk display headings (`72–84px` H1 `-0.03em` tracking, `44–56px` H2) paired with tabular numeric KPIs and crisp uppercase micro-eyebrows (`12–13px`, `0.10em` letter-spacing).

## 2. Structural Mapping to Neuro-Symbolic Corridor Domain
| `designstudiouiux.com` Section | Neuro-Symbolic Corridor Studio Reconstruction | Performance / Zero-Latency Strategy |
| :--- | :--- | :--- |
| Sticky glassmorphic top navbar (`Let's Start ↗`) | Brand `NS` emblem + `Corridor Studio.` + section anchors + `Console Only` toggle + `Launch Live Twin ↗` CTA | Pure CSS sticky backdrop; view toggle uses `@supports (content-visibility: hidden)` |
| Cosmic hero + cycling word + rating badges | `Unmatched [Z3+MILP / Cold-Chain / CEPA 0% / Bonded Rail] Routing` + solver SLA badges + 6 engine stack badges (`Z3`, `PyG`, `HiGHS`, `Go`, `e-TIR`, `CEPA`) | Above-the-fold eager paint; static inline SVG luminous wave backdrop |
| Founders intro + editorial statement | `Architects of Corridor Studio` + mission statement (Strait of Hormuz rerouting, Z3 formal verification) | `content-visibility: auto; contain-intrinsic-size: auto none auto 360px` |
| Dual client logo marquee | 12 Gulf–India–EU hub & customs gateway cards (`JNPT`, `JAFZA`, `KIZAD`, `Etihad Rail`, `Fujairah`, `Mirsal 2`, `ATLP`, `Bayan e-TIR`, etc.) | CSS transform marquee; paused automatically under `prefers-reduced-motion: reduce` |
| 4-card Bento metrics | `<400ms` P99 SLA, `64.8%` T-GNN pruning, `$1.85M+` biologics spoilage prevented, `100%` Z3 proof coverage | Deferred off-screen via `content-visibility: auto` |
| Split case studies with looping video | Biologics Cold-Chain (`INNSA -> AEFJR -> AEAUH -> EUFRA`) & Automotive JIT CEPA (`46% VA`) with `LOAD SCENARIO ↗` buttons wired to live solver | `<video loading="lazy" preload="none" width height>` + inline SVG poster + `IntersectionObserver` fallback |
| Interactive Services 01–05 + left diagram | Interactive 5-stage verification & solver selector syncing live inline SVG schematic | Zero network fetches; React state only |
| 01–06 Design Methodology rows | 6-stage deterministic neuro-symbolic pipeline breakdown (`Gateway Ingest` -> `e-TIR Dispatch`) | `content-visibility: auto` |
| Full-width video showreel | Stock maritime port aerial video container with play/pause toggle | `<video loading="lazy" preload="none">` + reduced-motion guard |
| Live Digital Twin (`#live-command-center`) | Existing Command Center (`sidebar`, `decision-header`, `CorridorMap` SVG+XYZ tiles, `route-table`, `<details>` audits) | Completely untouched solver API calls & SSE stream; `<400ms` SLA invariant preserved |
| 01–06 Industry Verticals | Pharma Biologics, EV Drivetrains, Specialty Polymers, Food Cold-Chain, Semis/Aero, CleanTech Grid | `content-visibility: auto` |
| News & Insights (3 cards) | Technical notes on Z3 CEPA proofs, Temporal-GATv2 pruning, and Hormuz bypass economics | `loading="lazy" decoding="async"` stock thumbnails |
| Reviews (`4.9 / 5`) + FAQ Accordion + Pre-Footer CTA | Audit endorsements + native `<details>` FAQ accordion (`modern-web-guidance` compliant) + benchmark badges | Native `<details>` with no headings inside `<summary>` |
| Contrasting Pure White Footer (`#FFFFFF`) | Global corridor hubs (`UAE`, `Oman`, `India`, `EU`), repository/doc links, and giant lowercase `corridor studio` watermark | Light contrast band via scoped `.ds-footer` styling |
