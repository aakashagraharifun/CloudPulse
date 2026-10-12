
# CloudPulse Design System

This document defines how CloudPulse looks and behaves. Its goal is a calm, professional analytics product where **the data is the loudest thing on the screen** and every number can be trusted.

The landing page structure follows the conventions of modern FinOps products such as CloudZero: a strong hero, three value pillars, a "raw spend to real answers" workflow, feature deep-dives, FAQ and a closing call to action. CloudPulse uses **no third-party branding, customer logos, testimonials or invented statistics**. Every claim on the landing page describes something the product actually does.

---

## 1. Principles

1. **Evidence over decoration.** Every figure shown comes from the API. There are no placeholder metrics or decorative charts in the product.
2. **Honest states.** Loading, empty, error and success states are designed, not left as afterthoughts. Missing data is shown as missing (a gap), never as zero.
3. **One currency at a time.** Amounts in different currencies are never added together. The currency in view is always visible.
4. **Explain, don't assert.** Investigation text states what the billing data shows and says clearly when it cannot determine a cause.
5. **Every control works.** A button, filter or link either does something real or does not exist.

## 2. Brand

| Element | Value | Notes |
| --- | --- | --- |
| Name | CloudPulse | One word, capital C and P |
| Logo mark | A rounded square holding a pulse line | Drawn in `components/brand/logo.tsx` (inline SVG) |
| Voice | Plain, precise, calm | "Spend rose 540% above baseline", not "Huge spike!!" |

## 3. Color tokens

Tokens live in `frontend/src/app/globals.css` (`@theme`). The UI uses Tailwind's **slate** neutrals plus one brand blue.

### UI

| Token | Hex | Use |
| --- | --- | --- |
| `--color-brand-600` | `#2a78d6` | Primary buttons, links, active nav, chart series 1 |
| `--color-brand-700` | `#1c5cab` | Primary hover |
| `--color-brand-50` | `#eef5fd` | Selected rows, active nav background |
| `--color-ink` | `#0b1b33` | Landing hero background, headings on light |
| Page background | slate-50 `#f8fafc` | Dashboard canvas |
| Card surface | `#ffffff` | Cards, tables, charts (validated chart surface) |
| Border | slate-200 `#e2e8f0` | Hairline borders and dividers |
| Text primary / secondary / muted | slate-900 / slate-600 / slate-500 | Never use a series color for text |

### Status and severity (reserved)

Status colors are **never** used for data series and **always** appear with a text label (and an icon where space allows), so meaning never depends on color alone.

| Meaning | Hex | Used for |
| --- | --- | --- |
| Good | `#0ca30c` (text `#006300`) | Within budget, delivery sent, decreases |
| Warning | `#fab219` | Medium severity, budget warning |
| Serious | `#ec835a` | High severity |
| Critical | `#d03b3b` | Critical severity, over budget, failures |
| Low / informational | slate-500 | Low severity |

### Chart palette

Charts use the validated categorical palette from the data-visualization method, assigned **in this fixed order and never cycled**:

| Slot | Hex | Slot | Hex |
| --- | --- | --- | --- |
| 1 blue | `#2a78d6` | 5 magenta | `#e87ba4` |
| 2 orange | `#eb6834` | 6 green | `#008300` |
| 3 aqua | `#1baf7a` | 7 violet | `#4a3aa7` |
| 4 yellow | `#eda100` | 8 red | `#e34948` |

The palette was validated against the white chart surface (`#ffffff`) with `validate_palette.js --mode light`:

- All checks pass. The worst adjacent CVD ΔE is 9.1 and the worst normal-vision ΔE is 19.6.
- Slots 3–5 are below 3:1 contrast. The relief rule therefore applies: every breakdown chart is paired with a visible table of values, and every chart has a tooltip.
- Most CloudPulse charts are single-series (slot 1, blue). The investigation chart uses slot 2 (orange) for the expected baseline and the *critical* status color, with a legend label, for anomalous days.

Chart chrome: gridlines slate-200 (1px, solid, horizontal only), axis labels slate-500 at 12px with tabular figures.

The product UI is light-mode only for the MVP. Dark mode is a documented future step: it needs its own validated chart steps rather than an automatic inversion.

## 4. Typography

| Role | Spec |
| --- | --- |
| Font | Geist Sans (bundled through the `geist` package, so no network is needed at build time), Geist Mono for IDs |
| Page title | 24px / 600 |
| Section title (card) | 14px / 600, slate-900 |
| Body | 14px / 400, slate-700 |
| Small / meta | 12px / 500, slate-500 |
| Stat value | 24–28px / 600, proportional figures |
| Hero figure (landing) | 48–60px / 600, tight tracking |
| Table numbers | `tabular-nums`, right-aligned |

Resource IDs, usage types and account numbers render in Geist Mono so they are easy to scan and copy.

## 5. Layout

- **Landing page:** max width 1200px, 24px gutters (16px on phones), alternating light and ink sections.
- **Dashboard shell:** a 240px left sidebar on screens of at least 1024px. On smaller screens the sidebar becomes a top bar with a menu button. A top bar shows the data status ("Data through Oct 11, 2026"), the currency selector and a **Sample data** badge whenever synthetic data is loaded.
- **Content:** max width 1280px with a 12-column responsive grid. KPI tiles sit 4-up on desktop, 2-up on tablet and stacked on phones.
- **Spacing scale:** 4 / 8 / 12 / 16 / 24 / 32 px. Cards use 20px padding, 12px radius and a 1px border with no heavy shadows.

## 6. Components

| Component | Behavior |
| --- | --- |
| **Card** | White surface, hairline border, optional title / description / action slot |
| **Stat tile** | Label (sentence case), value, optional signed delta "vs previous 30 days". Delta color reflects direction × desirability: for cost, an increase is shown in critical text and a decrease in good text, always with an arrow and a sign |
| **Badge** | Severity, status and "Sample data" badges are always text, never just a dot |
| **Meter** | Budget utilization. The fill color follows state (brand, then warning, then critical); the track is a light step of the same hue; the percentage is shown as text |
| **Buttons** | Primary (brand), secondary (white with border), ghost, danger. Disabled and busy states are explicit ("Uploading…") |
| **Forms** | Labels above fields, inline validation messages from the API's `error.details`, required fields marked |
| **Tables** | Sticky header and right-aligned numbers. Long IDs truncate with the full value in `title`. Paginated where the API paginates |
| **States** | `LoadingState` (skeleton), `EmptyState` (explanation plus the action that fixes it), `ErrorState` (API message plus Retry) |

## 7. Charts

| Chart | Form | Why |
| --- | --- | --- |
| Daily spend | Area (2px line, 10% wash) | Change over time. Gaps for days without data |
| Monthly spend | Columns (≤24px, 4px rounded top) | Comparing discrete periods. Partial months are labelled |
| Top contributors | Horizontal bars plus a table | Magnitude ranking, with long names readable |
| Incident evidence | Area of actual spend, expected baseline points, anomalous days marked | Shows observed versus expected directly |

All charts:
- show a tooltip on hover (crosshair on time series);
- format values in the active currency;
- use a single y-axis (never dual-axis);
- avoid a legend box for a single series, because the card title names it;
- show the empty state when the selected range has no data.

## 8. Interaction

- Filters sit in one row above the content they affect: date-range presets (7 / 30 / 90 days, month to date) and custom dates, granularity, group-by and dimension filters.
- Clicking a breakdown row drills down: it adds that value as a filter.
- Destructive actions (deleting an import, budget or channel) ask for confirmation and describe the consequence.
- After an import, the data status, overview and incidents refresh automatically.

## 9. Accessibility

- Text contrast is at least 4.5:1 (slate-600 or darker on white for body text).
- Severity and status always include text labels, and charts always have a tabular equivalent on the same page.
- Every input has a `<label>`. Icon-only buttons have an `aria-label`.
- Focus rings are visible (2px brand outline). Navigation and dialogs work with the keyboard.
- The layout works at 360px width with no horizontal page scroll; wide tables scroll inside their own container.

## 10. shadcn/ui components

The project is set up for [shadcn/ui](https://ui.shadcn.com) (`frontend/components.json`), so `npx shadcn@latest add <component>` drops new components into `src/components/ui/`.

- **Tokens:** the shadcn semantic colours (`background`, `foreground`, `primary`, `muted`, `accent`, `border`, `ring`, …) are defined in `globals.css` and mapped onto the CloudPulse palette. `:root` matches the light dashboard. `.dark` is the navy *ink* palette. Tailwind v4 has no `tailwind.config.js`; theme extensions live in `globals.css` (`@theme`).
- **Helpers:** `cn()` in `src/lib/utils.ts` (clsx + tailwind-merge). `components/ui/button.tsx` and `badge.tsx` are the shadcn versions. The dashboard still uses its own `components/ui/primitives.tsx`.
- **Theme:** `next-themes` provides `useTheme()`, with the app fixed to light. Dark sections opt in locally by wrapping content in `<div className="dark">`, as the landing hero does.
- **Landing hero** (`components/ui/hero-section.tsx`, with `mockup.tsx` and `glow.tsx`):
  - It renders on the ink palette, with a brand-blue glow and staggered entrance animations (`animate-appear`, `delay-*`). The animations are switched off for `prefers-reduced-motion`.
  - Its image is a real screenshot of the dashboard with the built-in sample data (`public/images/cloudpulse-dashboard.png`), labelled *Sample data*.
