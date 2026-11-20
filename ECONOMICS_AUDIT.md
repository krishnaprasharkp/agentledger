# AgentLedger economics audit

20 November 2026 · Code review and isolated test verification. No production database, invoices, labor records, or provider bills were used. Expected values below were worked from fixture inputs using decimal arithmetic and checked against the backend. Dollar amounts are USD, and ROI is shown as a percentage of total cost.

## Formula and unit review

| Item | Reviewed calculation |
| --- | --- |
| Forecast period | Monthly work volume × forecast months. Review and rework each use their own fraction × period work units. |
| Assessment period | One deployment, inclusive UTC start and exclusive UTC end. Fixed monthly costs are prorated using elapsed time ÷ 30.4375 days. The observed volume is used directly. Empty windows are rejected. |
| Manual baseline | Work units × manual USD/unit. The evaluator converts minutes/unit × USD/hour ÷ 60 to USD/unit. This is a counterfactual value. |
| Outcome benefit | Direction × (AI outcome total − baseline outcome total) × USD/outcome unit. Rates per work unit become totals before subtraction. Negative effects reduce modeled benefits. |
| Operating costs | Fixed subscriptions, infrastructure, and maintenance × months, plus variable model and infrastructure charges, reviewed units × USD/reviewed unit, and reworked units × USD/reworked unit. Assessments prefer a reported model charge to an estimate for the same execution. Missing usage costs require explicit USD/execution ranges. |
| Net benefit and ROI | Modeled manual value + valued outcomes − operating cost − one-time implementation. ROI = net benefit ÷ (operating cost + implementation). ROI is unavailable if the cost interval includes zero. |
| Payback | Implementation ÷ monthly recurring net benefit, using the modeled steady rate. A positive setup cost has no finite payback when recurring net benefit is nonpositive. Zero implementation is zero months because there is no upfront amount to recover, even when the economics are unfavorable. |
| Organization roll-up | Add selected period dollars and uniquely keyed shared entries, then recompute net benefit, ROI, and payback. Shared recurring inputs are supplied for the full window. No averaging of workflow ROI percentages. |

## Independently calculated checks

Expected and actual values are rounded here for readability. The tests assert the underlying decimals.

| Case and fixture inputs | Expected | Actual |
| --- | --- | --- |
| Positive forecast. 2 months × 10 units/month × $5 manual value. Per unit $1 model and $0.50 usage infrastructure. Review 25% × $2 and rework 10% × $5. Fixed monthly costs $3 + $4 + $5. Setup $13. | Benefit $100, operating $74 ($10 review and $10 rework), net $13, ROI 14.94%, payback 1 month. | $100, $74 ($10 and $10), $13, 14.94%, 1 month. |
| Negative forecast. Same inputs, setup $50. | Net −$24, ROI −19.35%, payback 3.85 months beyond the 2-month forecast. | −$24, −19.35%, 3.85 months. |
| Break-even and zero-cost edges. One $7 manual unit and $7 operating cost, no setup. Then zero units and costs. | Break-even net $0 and ROI 0%, zero setup payback 0 months. All-zero case ROI unavailable. | $0, 0%, 0 months. All-zero ROI unavailable. |
| Zero volume. No units, $12/month fixed costs for 2 months and $13 setup. | Net −$37, ROI −100%, no payback. | −$37, −100%, no payback. |
| Assessment. 30 days 10h 30m, 10 units, 4 reviews × $2 and 3 reworks × $3. $4 model charge supersedes a $9 estimate. A separate $3 estimate contributes, one run made no model call, and one model cost is missing. $7 infrastructure observed, one infrastructure cost missing. $12 fixed and $8 setup. Four escalations versus six baseline escalations at $3 value each. | Missing costs rejected until both ranges are supplied. With model $1–$2 and infrastructure $2–$4, operating $46–$49, benefits $56, net −$1 to $2, ROI −1.75% to 3.70%, payback 0.80–1.14 months. Start included, end excluded, equivalent offset timestamps respected. | Both omissions rejected. $46–$49, $56, −$1 to $2, −1.75% to 3.70%, 0.80–1.14 months. Four in-window executions counted. |
| Roll-up. Workflows with benefits $100 + $80, operating $74 each, setup $13 each. Shared benefit $20, operating $10, setup $5. | Benefit $200, operating $158, setup $31, net $11, ROI 5.82%, payback 1.48 months. | $200, $158, $31, $11, 5.82%, 1.48 months. |
| Overlap and scope. Duplicate workflow, duplicate shared benefit entry, shared key matching a workflow pool, missing attribution confirmation, mismatched horizon, or cross-organization analysis. | Reject all six. Reject a second workflow with the same pool in its organization. | All six HTTP 422. Duplicate pool HTTP 409. |
| Legacy invoice analysis. 10 attempts, 8 processed, 2 sent to manual fallback, 2 reviewed. Manual 6 min, review 3 min, $60/h. $2 known model cost, one unknown modeled at $1, overhead $0.50/attempt. | Unknown model cost blocks estimation until supplied. Then manual $60, fallback $12, review $6, operating $26, $3.25/processed, net $34, ROI 130.77%. | Missing cost flagged. $60, $12, $6, $26, $3.25, $34, 130.77%. |

A separate negative-outcome check verified that a −$160 outcome effect can reduce $100 manual value to −$60 of modeled benefits, leaving net benefit of −$147 and ROI below −100%.

### Customer-support forecast

Held fixed at 12 months and 900–1,200 tickets/month. Labor was $30–$36/hour. Review was 25%–40% at $1.50–$2.10 each, and rework was 5%–10% at $3–$5 each. Model and variable infrastructure totaled $0.18–$0.31/ticket. Combined fixed infrastructure and maintenance totaled $330–$520/month, with $8,000–$12,000 setup. Upper manual time stayed at 8 minutes.

| Lower manual time | Expected and actual manual value per ticket | Expected and actual operating cost | Expected and actual net benefit | Expected and actual ROI |
| --- | --- | --- | --- | --- |
| 6 minutes | $3.00–$4.80 | $11,574–$30,000 | −$9,600 to $49,546 | −22.86% to 253.12% |
| 7 minutes | $3.50–$4.80 | $11,574–$30,000 | −$4,200 to $49,546 | −10.00% to 253.12% |

The low modeled manual benefit rose by $5,400 ($0.50 × 10,800 tickets), improving the lower ROI bound by 12.86 percentage points. The upper bound stayed fixed. These are hypothetical figures.

## Corrections and limitations

- **Corrected:** Calculate ROI directly from signed net benefit and total cost at each bound. Multiplying benefits by a rounded reciprocal could give exact break-even a tiny residual. Clarified the zero-setup payback edge described above.
- **Corrected:** Reject the reserved manual-baseline metric in the calculation, including preview. Prefix a colliding outcome's sensitivity key so it cannot hide the corresponding cost or implementation span.
- **Corrected:** Normalize newly ingested timestamps to UTC before storage and compute assessment elapsed time without a float conversion. Tests cover equivalent offsets and window boundaries. Historical snapshots and records were preserved.
- **Reviewed:** Interval arithmetic gives outer sensitivity bounds, not confidence intervals or paired scenarios. Sharing the same volume between costs and benefits, independent corner enumeration gave net bounds of −$3,660 to $47,008 at 6 minutes and $1,740 to $47,008 at 7 minutes. The engine's wider documented bounds were retained. A zero-crossing outer range can persist even when these paired corners are favorable.
- **Reviewed:** Observed workload, reported charges, and recorded outcomes are separate from prior model estimates and user assumptions in assessment snapshots. Synthetic provenance is preserved. The economics API expects costs already denominated in USD and performs no FX conversion. Extracted invoice amounts and their native currencies are not used as economics charges.
- **Requires evidence:** Distinct keys and user confirmation cannot detect the same staff capacity, shared costs, or benefits described differently. A test with a renamed copy of the $20 shared benefit and a positive attribution attestation produced $220 in total benefits, up from $200. Owners must substantiate distinct attribution, real labor displacement, and review versus rework effort. Results also depend on comparable baselines, complete telemetry, valid rates, and separately evidenced outcome valuations. This model does not establish realized cash savings, causal lift, or discounted investment returns.

**Verification** — Full backend suite passed with **37 tests**, including **12 new audit cases**, using isolated SQLite. The suite emitted one Starlette TestClient deprecation warning. No PostgreSQL data was modified and no running deployment was changed.
