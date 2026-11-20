# Provider validation

## Status

The OpenAI execution path is implemented. **No live provider request was made during verification.** The user subsequently authorized one potentially billable OpenAI request. A follow-up preflight found no LLM credential, workspace access key, or effective dated pricing for the configured model. The probe was disabled. No attempt was created and the authorization was unused. No production PostgreSQL records or running deployment were changed.

## Architecture

The customer-support probe reuses the HTTPX structured-completion transport already used for invoice extraction. It uses the configured OpenAI model with the official OpenAI API origin. The only input is a fixed fictional password-reset ticket. The provider returns one structured category, with a 128-token output cap. A correct classification is success. A different valid category is an application failure and retains available usage evidence.

A probe runs only against a dedicated deployment with adapter **customer_support_probe**. It writes to the existing workflow execution JSON telemetry without a migration. The generic ingestion endpoint cannot fabricate a probe record for that deployment. Probes use synthetic workload provenance and are excluded from business ROI assessments. The frontend and existing economics formulas are unchanged.

## Evidence fields

Use the probe response or **GET /portfolio/deployments/{deployment_id}/executions** to inspect the execution. Existing workspace access controls apply.

| Location | Evidence |
| --- | --- |
| Execution | Deployment ID, attempt UUID in external_run_id, UTC timestamp, synthetic data origin, and success boolean |
| Telemetry | Model, nullable provider-reported input and output token counts, elapsed request milliseconds, and estimated model cost in USD |
| Provider evidence | Provider, scenario identifier, requested and provider-reported model, optional provider request ID and HTTP status, classification, status, and safe failure code |
| Pricing evidence | Requested pricing snapshot and the exact reported model's pricing snapshot when available. Includes input and output USD rates per million tokens, source, currency, and effective date |
| Billing | The OpenAI probe leaves model_charge_usd unset. The estimate is not an invoice or a reported per-request charge. |

## Cost and failure handling

Estimated API cost is **(input tokens × input USD per million + output tokens × output USD per million) ÷ 1,000,000**. Pricing comes from LLM_PRICING_JSON and must be explicitly dated. The requested model needs a dated entry before any request. The estimate uses the exact provider-reported model entry effective on or before the UTC execution date. If that model is unpriced, the model is missing, or either count is unavailable, the estimate stays unknown. Partial token counts are retained. The formula does not apply cache, service-tier, batch, tax, discount, or billing adjustments.

Enablement, credentials, workspace access protection, pricing, and explicit request authorization are checked before creating an attempt or contacting OpenAI. The service reserves a unique attempt in the existing execution table before sending. There is no automatic retry or redirect. Posting the same attempt UUID returns the reserved or completed record without sending again, including after a timeout or while the first request is pending. A crash can leave a pending record, and a timeout cannot establish whether the provider processed or billed the request. Do not create a fresh attempt ID to resolve that uncertainty without separate authorization.

Raw provider responses, exception diagnostics, and credentials are excluded from the evidence record. A failed provider call returns the recorded attempt with failure status and a safe error code. A rejected preflight returns an HTTP error and creates no attempt.

## Optional authorized live smoke

1. Obtain explicit approval for one potentially billable request. Provision a dedicated deployment via the existing portfolio API using the adapter name above. Use a disposable development workspace if preferred.
2. Set SUPPORT_LIVE_PROBE_ENABLED=true, LLM_API_KEY, LLM_MODEL, WORKSPACE_API_KEY, and LLM_PRICING_JSON in the server environment. Keep extraction in its current mode. Use the official OpenAI base URL. Set USD, the pricing effective date, and the actual source for the requested model and any distinct reported model snapshot. No default rates are assumed.
3. From backend, pass a known deployment UUID and a new attempt UUID exactly once. The local smoke client reads WORKSPACE_API_KEY from its environment. Reuse the same UUID to inspect after an uncertain response.

```powershell
.\.venv\Scripts\python.exe smoke_support_probe.py --deployment-id <deployment-uuid> --attempt-id <attempt-uuid> --authorize-live-request
```

Set the enable flag back to false after the live test window. A real run would still need verification of credential access, response model, actual token and request ID fields, and reconciliation against the configured price source. Billing confirmation requires provider billing evidence.

## Test results

The complete backend suite passed with **48 tests** using isolated SQLite and mocked provider HTTP responses. **11** probe cases cover stored and retrievable telemetry, estimated cost separation, replay and pending replay, missing configuration and explicit authorization, timeout, rate limiting, malformed and incorrect responses, partial or absent usage, an unpriced provider-reported model, and rejection of manually submitted probe evidence. All existing backend tests passed. The suite emitted the existing Starlette TestClient deprecation warning. Mocked records existed only in the isolated test database.
