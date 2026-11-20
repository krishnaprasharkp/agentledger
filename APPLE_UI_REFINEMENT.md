# AgentLedger Apple-inspired frontend refinement

The attached written brief was the reference for this pass. No separate approved visual preview was available in the attachment or workspace, so a visual match to that preview remains unverified. No proprietary Apple assets or exact product layouts were used.

## Design tokens and interaction

| Area | Implementation |
| --- | --- |
| Typography | Local system stack starting with Apple platform fonts, followed by Inter, Segoe UI, and system sans-serif. No font downloads. Larger near-black headlines, lighter supporting copy, and tabular figures for financial values. |
| Color | #F5F5F7 canvas, #FFFFFF surfaces, #1D1D1F text, neutral separators, and muted teal primary actions. #86868B is reserved for the large desktop Overview subtitle. Normal-size supporting text uses #646469 for contrast. Color-token contrast on the canvas is 3.33:1 for the large subtitle and 5.40:1 for supporting text. These are token checks, not a full accessibility audit. |
| Surfaces | Shared radii, subtle shadows on major surfaces, and row dividers inside tables and Settings. Individual metrics remain unboxed. |
| Navigation and input | Compact monochrome SVG line icons, a neutral selection background, organization selection in the workspace header, native cursors, visible keyboard focus, and reduced-motion handling. No decorative window controls. |

## Five pages

- **Overview.** The investment summary leads with estimated net benefit. ROI, payback, operating costs, and modeled benefits use the selected workflow or report's existing estimates. Reporting period, currency, and provenance sit above the figures. Sensitivity charts and a concise decision explanation precede the workflow comparison table.
- **AI Workflows.** The table separates department, evaluation status, financial outcome, latest saved analysis date, and the Evaluate action. Existing search and drill-downs remain.
- **Evaluate AI.** Shared form styles and a dedicated evaluation surface frame the existing steps, ranges, and explanations. The customer-support preview remains read-only.
- **Reports.** Configuration and output use separate surfaces. Existing attribution, calculations, assumptions, and JSON export remain available.
- **Settings.** Workspace access, organizations, and developer integrations appear as grouped rows. Credential storage and authentication behavior are unchanged.

## Verification and limits

- Production build passed. All 4 frontend tests and all 48 backend tests passed.
- The [HTTP and DOM verification report](verification/apple-ui/agentledger-review.html) covers all five pages using an isolated synthetic SQLite instance. It checks the Overview financial summary, workflow columns and actions, example recalculation and input validation, tooltip state, report attribution and JSON generation, and recovery from a simulated access error. The DOM harness emitted React asynchronous update warnings. The backend suite emitted its existing Starlette TestClient deprecation warning.
- The browser host was unavailable. No screenshots were captured. Desktop, tablet, and mobile rendering, visual tooltip placement, native cursor appearance, and native file downloads were not verified in a browser.
- No application deployment, production database change, new dependency, API change, financial definition change, benchmark implementation change, or billable provider request was made. API benchmarks were not rerun, so no performance comparison is claimed.
