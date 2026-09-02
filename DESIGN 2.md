---
name: open-tam GTM Landing Page
description: Professional DevOps console — dark-first, blue-cyan accent, semantic status colors; alerts in, RCA report out.
colors:
  bg: "#0B1016"
  bg-soft: "#0E141C"
  panel: "#121A24"
  panel-hi: "#17212E"
  border: "#1F2C3D"
  border-strong: "#2E405A"
  text: "#E8EFF7"
  text-2: "#9DB0C3"
  text-3: "#64798F"
  accent: "#38BDF8"
  accent-soft: "rgba(56,189,248,.12)"
  cta: "#2563EB"
  cta-hi: "#1D4ED8"
  ok: "#34D399"
  warn: "#FBBF24"
  crit: "#F87171"
  code-bg: "#0D131B"
  code-text: "#C9D6E5"
  code-dim: "#64798F"
  code-border: "#1B2836"
  console-bar: "#111823"
  data-cyan: "#7DD3FC"
typography:
  display:
    fontFamily: "Inter, Noto Sans SC, system-ui, sans-serif"
    fontSize: "clamp(1.9rem, 4vw, 3rem)"
    fontWeight: 800
    lineHeight: 1.18
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "Inter, Noto Sans SC, system-ui, sans-serif"
    fontSize: "clamp(1.3rem, 2.2vw, 1.7rem)"
    fontWeight: 800
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Inter, Noto Sans SC, system-ui, sans-serif"
    fontSize: "0.92–0.96rem"
    fontWeight: 400
    lineHeight: 1.65
  label:
    fontFamily: "JetBrains Mono, monospace"
    fontSize: "0.66–0.78rem"
    fontWeight: 600
    letterSpacing: "0.1–0.18em"
    textTransform: uppercase
  mono:
    fontFamily: "JetBrains Mono, monospace"
    fontSize: "0.74–0.86rem"
    fontWeight: 400–600
    lineHeight: 1.6–1.9
rounded:
  module: "12px"
  card: "10px"
  code-block: "8px"
  tag-pill: "6px"
  button: "8px"
spacing:
  wrap-max-width: "1200px"
  wrap-padding: "clamp(14px, 3vw, 32px)"
  module-gap: "2.6rem"
  module-body-padding: "1.8rem"
  grid-gap: "1.2rem"
components:
  brand:
    mark: ">_ glyph on accent background, JetBrains Mono 700"
    name: "Open TAM (Inter 700 1.08rem)"
    sub: "SRE AGENT (mono uppercase 0.68rem, text-3)"
  theme-seg:
    shape: "segmented control, 8px radius, aria-pressed states"
  btn-primary:
    backgroundColor: "{colors.cta}"
    textColor: "#FFFFFF"
    rounded: "{rounded.button}"
    padding: "0.72rem 1.5rem"
  btn-ghost:
    border: "1px solid {colors.border-strong}"
    textColor: "{colors.text}"
    hover: "accent border + accent text"
  console:
    backgroundColor: "{colors.code-bg}"
    border: "1px solid {colors.border-strong}"
    rounded: "{rounded.module}"
    bar: "{colors.console-bar}, 3 status dots crit/warn/ok, mono title, RUNNING pill"
  ledger:
    backgroundColor: "{colors.code-bg}"
    rounded: "{rounded.card}"
    rowGrid: "3.6rem 6.4rem 1fr auto"
  doc:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.card}"
    tab: "panel-hi strip with mono filename + ok pill"
  gauge:
    backgroundColor: "{colors.bg-soft}"
    cells: "10 segments 20px tall; on-g=ok, on-a=accent, ghost=dashed"
  roadmap:
    layout: "6-col grid with timeline rail; done=ok node, now=accent pulsing node, todo=dashed"
  tty:
    backgroundColor: "{colors.code-bg}"
    rounded: "{rounded.module}"
---

# Design System: open-tam GTM Landing Page

## Overview

**Creative North Star: "Ops Console（值班控制台）"** · approved 2026-08-31

The page reads like the on-call console an SRE already knows: Grafana/Datadog/Linear vocabulary — dark neutral panels, hairline borders, a blue-cyan accent, mono type for anything machine-produced, and semantic status colors (ok / warn / crit) that are never decorative. The hero is a live investigation console: alert in (IN), orchestrator dispatching MCP tool calls (ORCH), three-part RCA report out (OUT). Below the hero, each section is a numbered panel (01–07) in the same flat panel system.

Two hard commitments from the approved direction:

1. **IA/copy 1:1 inheritance** — this was a visual reskin, not a content rewrite. Every section title, ledger row, report paragraph, and CTA label carries over from the previous version. Do not invent metrics or copy.
2. **Brand casing** — display text uses **Open TAM** (capital O, capital TAM): `<title>`, meta description, topbar wordmark, hero aria-label, footer. Commands and paths stay lowercase `open-tam` (CLI title bars, Quick Start block, `reports/` paths). Never "OPEN TAM", "Open Tam", or "OpenTam" in display text.

**Key characteristics:**
- Dark-first: `[data-theme="dark"]` is the default; `[data-theme="light"]` overrides the same tokens. Console/terminal/code surfaces stay dark in BOTH themes (fixed `--code-*` values) — a real console stays dark under office lighting.
- Dot-grid background (24px radial dots at `--dot-grid` opacity) over `--bg` — the only texture on the page. No grain, no gradients on surfaces.
- Status semantics: green = success/pass/observation, amber = warning, red = deny/danger only. The primary CTA is blue (`--cta`), NOT red.
- Sequential LED term animation in the hero console (70ms stagger) is the only ambient motion besides two pulse dots and the "now" roadmap node.

## Colors

All colors live as CSS custom properties on `:root` (dark) with a `[data-theme="light"]` override block. Components never hardcode a theme-dependent color; they reference tokens. Fixed dark surfaces (`--code-*`, `#111823` console bar, `#7DD3FC` data cyan, `#55677D`/`#223042` ledger details) intentionally do NOT flip in light mode.

### Core (dark default / light override)
- **bg** `#0B1016` / `#F5F7FA` — page ground, covers >70% of any viewport.
- **bg-soft** `#0E141C` / `#EDF1F6` — inset cards (cell-mod, gauge, mslot), tags.
- **panel** `#121A24` / `#FFFFFF` — modules, doc card, footer plate.
- **panel-hi** `#17212E` / `#F8FAFC` — active segment, doc-tab strip.
- **border** `#1F2C3D` / `#E3E9F0` — all hairline borders.
- **border-strong** `#2E405A` / `#CBD5E1` — emphasis borders, timeline rail, dashed outlines.
- **text** `#E8EFF7` / `#0F1B2D` — primary. **text-2** `#9DB0C3` / `#47586E` — body/secondary. **text-3** `#64798F` / `#7A8AA0` — captions, EN sub-labels.
- **accent** `#38BDF8` / `#0284C7` — data highlights, links, focus rings, `--no` chips, LED terms, "now" states. **accent-soft** is the 12%/10% tint behind accent chips.
- **cta** `#2563EB` / `#1D4ED8` — primary button ONLY. Hover `--cta-hi`. Blue is the action color; it never appears as passive decoration.
- **ok** `#34D399` / `#059669` — pass, observation, done, RUNNING. **warn** `#FBBF24` / `#B45309` — warning (console bar dot only, currently). **crit** `#F87171` / `#DC2626` — DENY entries, console-bar first dot.

### Fixed code surfaces (never themed)
- **code-bg** `#0D131B`, **code-border** `#1B2836`, **code-text** `#C9D6E5`, **code-dim** `#64798F`, console bar `#111823`.
- **data-cyan `#7DD3FC`** — function names, IN/ledger type labels, TTY prompts. Brighter than accent because it sits on code-bg.

### Named rules

**The Action-Is-Blue Rule.** Exactly one element per page uses `--cta`: the primary hero button. Red (`--crit`) is never an action color — it marks DENY and terminal-bar chrome only.

**The Console-Stays-Dark Rule.** `.console`, `.ledger`, `.sig`, `.tty` keep their dark values in light theme. Light theme only lifts page chrome. If a code surface inherits a themed token, that's a bug.

**The Token-Only Rule.** No component declares its own hex except the fixed code surfaces listed above. New colors go through `:root`/`[data-theme="light"]` first.

## Typography

**Fonts:** Inter (Latin UI, 400–800) + Noto Sans SC (CJK, 400–900) + JetBrains Mono (code/data, 400–700). Single Google Fonts stylesheet. Saira Condensed is retired.

- **Display / h1** (800, clamp(1.9rem, 4vw, 3rem), 1.18, -0.01em): hero thesis. One per page.
- **Headline / h2** (800, clamp(1.3rem, 2.2vw, 1.7rem)): module titles, paired with the mono `.no` number chip and right-aligned mono `.en` uppercase sub-label.
- **Title / h3** (700, 1.1–1.25rem): cell titles (with 8px ok-dot), report-side heading.
- **Body** (400, 0.92–0.96rem, 1.65): paragraphs; `--text-2`.
- **Label** (mono, 600–700, 0.64–0.78rem, 0.1–0.18em, uppercase): eyebrow, pills, cl-tags, EN sub-labels, RUNNING/STATUS chips.
- **Mono** (400–600, 0.74–0.86rem): ledger rows, signatures, console lines, TTY, file paths, `.fname`, audit log.

**The Readout Rule** (carried over): anything the system produced — trace entries, commands, paths, audit lines, tool signatures — is JetBrains Mono. No exceptions.

## Layout

Single vertical stack: hero (min-height 100svh) → numbered modules (01–07, margin-top 2.6rem) → footer plate. No sticky nav; the topbar (brand + theme segmented control) scrolls away. Container `.wrap` max-width 1200px, padding clamp(14px, 3vw, 32px).

**Hero grid (>1080px):** `minmax(0,5fr) minmax(0,6fr)` — copy left, console right, gap clamp(2rem, 4vw, 3.5rem), vertically centered, min-height 100svh with clamp padding. Topbar above with 1px bottom border.

**Internal grids (desktop):** mech/gauges `repeat(3,1fr)` gap 1.2rem; report-wrap `minmax(280px,46%) 1fr` gap 1.8rem; roadmap `repeat(6,1fr)` with an absolute timeline rail (`.road::before`, top 9px, spanning 8.333%→91.667%) and 12px node dots per slot.

**Collapse at 1080px:** hero → 1 column (copy above console), hero min-height released, mech/gauges → 1 col, report-wrap → 1 col, roadmap → 3 cols and the timeline rail/nodes are hidden.

**641–1080px:** mech/gauges 2 cols.

**Collapse at 640px:** roadmap → 2 cols; module padding tightens (1.3rem 1.1rem); `.module-h` wraps with `.en` taking a full-width row; `.cline` drops the status dot; `.trow2 .fn` goes auto-width and wraps; `.lrow` → 3 cols with the hole column hidden; CTA buttons go `flex:1`; TTY pre drops to .78rem.

## Elevation & Depth

Flat surfaces, hairline borders, one shadow token: `--shadow` = `0 8px 24px -12px rgba(0,0,0,.55)` (dark) / `0 8px 20px -12px rgba(15,27,45,.22)` (light). Applied to modules, console, tty, doc, foot-plate — never animated, never hover-increased.

Interaction feedback is border/color only: cell-mod and btn-ghost borders shift to accent on hover; copybtn text/border to accent; primary button darkens to `--cta-hi` and presses down 1px. No translateY lifts, no scale, no glow-on-hover.

Glow exists only as "powered-on" state semantics: lit LED terms (`0 0 6px rgba(56,189,248,.55)`) and the pulsing "now" node ring (`pulse-ring`, `0 0 0 6px accent-soft`).

## Shapes

Quiet rounding in the 6–12px band — console-grade, not playful: modules/console/tty/foot-plate 12px; cards (ledger, doc, cell-mod, gauge, mslot, audit containers) 10px; sig/code blocks 8px; buttons 8px; tags/chips/pills 6px; pills and nodes 999px. No 0px surfaces, no blob radii.

All structural borders are 1px solid `--border` (header dividers included). Dashed is reserved for "not yet real": `.tag.off`, `.mslot.todo`, `.cells i.ghost`, `.later` details container, and the doc `.meta` evidence divider. The theme segmented control is the only 2-segment strip; its active segment uses panel-hi + text (no accent fill).

## Components

### Topbar / Brand
Flex row, space-between, 1px bottom border. Brand: `>_` mono glyph on accent background (dark ink in dark theme, white in light) + "Open TAM" (700) + "SRE AGENT" mono uppercase sub. Theme segmented control: two buttons (深色/浅色) with `aria-pressed` synced by JS.

### Hero
- `.eyebrow` — mono uppercase pill with pulsing 6px accent dot, accent text, panel bg.
- `.sub` — audience line with bold text names, `--text-2`.
- `.cta-row` — `.btn-primary` (cta bg, white text) + `.btn-ghost` (border-strong). Anchors styled as buttons, `text-decoration:none`, `:active` presses 1px.

### Console window (hero)
`.console` on code-bg, 12px radius, border-strong. Bar (`#111823`): crit/warn/ok dots, mono title `open-tam investigate --alert-file /tmp/alert.json` (ellipsis), RUNNING pill (ok border + pulsing dot). Body: three `.cline` rows (grid `auto 1fr auto`) with `.cl-tag` chips — IN (data-cyan), ORCH (accent), OUT (ok) — plus `.cl-status` 8px ok dot. The ORCH row contains `.cl-tools`: two `.trow2` rows (`fn` label 8.6rem fixed + `.terms` LED strip of 12 `.term` bars, 10px tall, flex:1 max 26px; query_logs' last two `.ghost`). LEDs light sequentially (70ms stagger, 600ms initial delay) via `flow()` — runs once on `load`, `mouseenter` fallback, `flown` guard. Guardrail rendered as `.tag` chip row.

### Modules (01–07)
`.module` panel, 1px border, 12px radius, `--shadow`. Header `.module-h`: `.no` mono chip (accent on accent-soft), h2, right mono `.en` uppercase sub-label; 1px bottom border. Body `.module-b` 1.8rem padding.

### Trace ledger (02)
`.ledger` code-bg, 10px radius. `.lrow` grid `3.6rem 6.4rem 1fr auto`: row number (`#55677D`), type (`thought`/`tool_call` data-cyan · `observation` ok · `report` bright white), description (code-text), 5 hole LEDs (5px; `#223042` off, accent on). Even rows +2% white overlay.

### Mechanism cells (01, 03)
`.cell-mod` bg-soft, 10px radius, hover border accent. h3 with 8px ok dot. `.sig` code block with `.fn` data-cyan function names. `.audit` mono log with `.deny` crit / `.pass` ok. `.swap` rows of `.tag` chips joined by `.arr`.

### Report doc (04)
`.doc` panel card, 10px radius. `.doc-tab` panel-hi strip: mono `.fname` + ok pill "已定位". `.doc-body`: numbered sections (`<b><i>01</i>结论摘要</b>` — i is mono accent), lists in text-2, `.meta` evidence line under a dashed top border.

### Gauges (05)
`.gauge` bg-soft, 10px radius. Header: CJK metric name + mono uppercase EN. `.cells`: 10 flex segments, 20px tall, 3px radius — `.on-g` ok (hit rate), `.on-a` accent (steps/cost), `.ghost` transparent dashed. Fault registry: `.tag` chips with `.tag.off` for excluded hypotheses.

### Roadmap (06)
6-col grid, timeline rail + node dots. States: `.done` (ok node, DONE chip), `.now` (accent node with `pulse-ring` 2s, NOW chip, accent border), `.todo` (dashed border, PLAN chip, bg node). `<details class="later">` for deferred items with ▸/▾ marker.

### TTY (07)
`.tty` code-bg, 12px radius. Bar like console bar with `open-tam · no-key demo` + copy button (mono, border-strong; hover accent; JS writes clipboard, shows "copied" 1.2s). `pre` mono .86rem, 1.9 line-height; `.p` prompts data-cyan, `.c` comments code-dim.

### Footer
`.foot-plate` panel bar: "Open TAM · SRE AGENT" (mono suffix accent) + nav links (text-2 → accent hover). `.foot-note` row of text-3 disclaimers below.

## Motion

- LED flow: `.term` light-up, 70ms stagger, 600ms delay, once per page load (`flown` guard; `mouseenter` fallback; all-lit immediately under `prefers-reduced-motion`).
- `pulse-dot` (2s eyebrow / 1.6s RUNNING) and `pulse-ring` (2s, "now" node) — opacity/box-shadow only.
- Reveals: `.reveal` translateY(16px)→0 + fade .55s via IntersectionObserver, gated on `html.js` (no-JS keeps content visible). `#shot` hash forces `.in`-equivalent state and kills the hero min-height for full-page screenshots.
- `prefers-reduced-motion: reduce` disables scroll-behavior smooth, all pulses, and reveal transitions.

## Debug & verification hooks (URL hash)

- `#light` — force light theme (dark is default).
- `#shot` — collapse hero min-height, force reveals visible, stop pulse animations. Use for full-page captures and any window taller than a normal viewport.
- `#measure` — on DOMContentLoaded sets `<title>` to `H<scrollHeight>|W<scrollWidth>|I<innerWidth>`; assert `W ≤ I` (no horizontal overflow). Combine as `#measure-shot` so measured H matches `#shot` layout.

## Do's and Don'ts

### Do:
- **Do** reference tokens for every themed color; put new colors in `:root`/`[data-theme="light"]` first.
- **Do** keep code surfaces (`.console`, `.ledger`, `.sig`, `.tty`) on fixed `--code-*` values in both themes.
- **Do** use "Open TAM" in display text and lowercase `open-tam` for commands, paths, and package references.
- **Do** render all machine output in JetBrains Mono; all EN uppercase labels mono with ≥0.1em tracking.
- **Do** use status colors semantically: ok=pass/complete, warn=warning, crit=deny/danger, accent=data/highlight/now, cta=primary action only.
- **Do** keep dashed = "not yet / excluded" (todo milestones, ghost cells, off tags, later container, meta divider).
- **Do** give interactive feedback via border/text color shifts; press feedback via `:active` translateY(1px) on buttons only.
- **Do** preserve a11y furniture: skip link, `:focus-visible` accent outline (offset 2), `aria-pressed` theme control, `aria-label` on hero/ledger/table roles, no nested interactive elements.
- **Do** verify with the hash hooks before delivery: `#measure-shot` W≤I at 1440/768/500 (CLI) and 320/375/414 (emulated), screenshots in both themes.

### Don't:
- **Don't** use red as an action or emphasis color; it's DENY/console-chrome only. Primary action is `--cta` blue.
- **Don't** theme the code surfaces — no light-mode terminal, no accent-tinted code background.
- **Don't** add gradients to panels, glassmorphism, backdrop-filter, or decorative glows; the only texture is the 24px dot grid.
- **Don't** exceed 12px radius or drop below 6px; no pill-shaped cards, no circular buttons.
- **Don't** add hover elevation, parallax, or new ambient animation beyond the LED flow and the two pulse patterns.
- **Don't** invent metrics or copy — all numbers/demo data come from the repo's fault registry (cpu_spike sample) and roadmap; IA/copy is inherited 1:1.
- **Don't** use fonts outside Inter / Noto Sans SC / JetBrains Mono. The three-font system is closed.
- **Don't** make the hero shorter than 100svh on desktop (release only ≤1080px or via `#shot`).
- **Don't** introduce icon libraries or emoji; visuals are CSS-only plus the `>_` brand glyph.
