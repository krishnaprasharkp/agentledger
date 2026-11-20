# AgentLedger frontend refinement

## Design review

1. Nested, shadowed panels gave sections and metrics similar visual weight.
2. Small headings and figures made the main financial result difficult to spot.
3. Saturated blue, navigation glyphs, and badges competed with meaningful financial states.
4. Workflow tiles made it difficult to compare analysis coverage and read figures across workflows.
5. The same panel treatment made setting assumptions, reviewing results, and editing configuration feel like the same task.

## Design system

- **Color.** Warm off-white canvas, a light neutral navigation rail, and dark ink. Deep teal marks primary actions and selected states. Green, red, and amber mark favorable, unfavorable, and uncertain financial outcomes.
- **Type.** A local system sans stack with one page title, smaller section headings, and compact labels. Tabular figures align values in tables, summaries, and charts. Long explanations have a constrained reading width.
- **Spacing and rules.** Section spacing and thin dividers establish hierarchy. Inputs, keyboard focus, and financial status remain visible without wrapping each section in a card.
- **Components.** Tables support structured comparisons. Charts preserve signed ranges, zero markers, provenance, exact values, and keyboard tooltips. A mobile chart layout places the series labels and values above each track.
- **Interaction.** Visible focus, keyboard-scrollable tables, focus movement on navigation and wizard steps, delayed access confirmation until the API returns, and reduced-motion support. No runtime dependency or font download was added.

## Page changes

| Page | Refinement |
| --- | --- |
| Overview | A financial ledger leads with estimated net benefit and adjacent cost and benefit ranges. Reporting mode, period, currency, and source stay near the numbers. Workflow comparison and guidance have distinct roles. |
| AI Workflows | A dense table shows department, work unit, deployments, analysis coverage, provenance, and the latest applicable net benefit. Existing search, workflow links, and invoice tools remain available. |
| Evaluate AI | A step rail frames the existing guided form. Range instructions are clearer, advancing or going back focuses the active step, and example and saved results retain their existing calculation and record-saving behavior. |
| Reports | Report setup and output are distinct. Attribution confirmation is easier to find. Results state how many shared items were counted and preserve the existing export. |
| Settings | Configuration rows pair each section's purpose with its controls. Workspace access confirmation follows the actual response. |

## Verification

The final production build passed, all 4 frontend tests passed, and all 48 backend tests passed. A separate [HTTP and DOM check](verification/frontend-refinement/agentledger-review.html) exercised the five pages against a temporary SQLite demo instance, including forecast recalculation, invalid input, chart controls, report JSON generation, and a simulated access error. Its asynchronous harness emitted React test wrapping warnings. The backend suite emitted the existing TestClient deprecation warning.

The browser host was unavailable, so there are no before/after screenshots. Visual rendering at desktop, tablet, and mobile widths, native downloads, and pointer and touch behavior remain unverified. The work stayed in the frontend and its verification harness. No deployment, API, financial definition, database record, or benchmark definition was changed.
