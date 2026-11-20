# AgentLedger

AgentLedger evaluates the economics of enterprise AI adoption. Teams can forecast the value of a proposed workflow, assess a deployment using recorded telemetry, and compare workflows at the organization level. The two reference workflows are finance invoice intake and IT service desk triage.

## Run locally

Use Python 3.13, Node.js 22.12 or newer for frontend development, and PostgreSQL 17. Docker Compose provides the database, API, and dashboard together. Run these commands from the folder containing this README.

```powershell
cd backend
if (!(Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

For a fresh setup, set a strong, URL-safe `POSTGRES_PASSWORD` in the local `.env` file. Both database URLs in the template use that value. For an existing Compose database, use its current password and set any missing database variables in your existing local file. The Docker database URL uses `db:5432`.

```powershell
docker compose up --build -d
```

Open [the portfolio dashboard](http://localhost:8001/), [the API reference](http://localhost:8001/docs), or [the invoice adapter](http://localhost:8001/?view=invoice). The database binds to localhost on port 5433. The API container applies additive migrations before serving traffic. The existing Compose database service and named volume are retained. Keep the same Compose project and database credentials when upgrading an existing local installation.

For hot reload, start only PostgreSQL with `docker compose up -d db`. From `backend`, run the API in a second terminal.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m migrate
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

From `frontend` in another terminal, run `npm ci` and `npm run dev`, then open [Vite](http://localhost:5173/). Vite forwards API requests to the local backend. To serve a built frontend with FastAPI, run `npm run build` and set `STATIC_DIR=../frontend/dist` when starting FastAPI from `backend`.

## Reproducible portfolio demo

From `backend`, run the script against a development instance. Each run creates a distinctly named synthetic organization with two workflows, forecasts and assessments for each, and a forecast roll-up with one shared cost. The script prints record IDs and the illustrative roll-up.

```powershell
.\.venv\Scripts\python.exe demo_portfolio.py --base-url http://127.0.0.1:8000
```

Select the synthetic organization in the dashboard. The Overview switches between pre-adoption forecasts and post-adoption assessments and labels synthetic data. Open either workflow to compare its saved analyses, inspect its baseline and telemetry, and see what drives the estimated range.

Use **Evaluate AI** for a guided forecast or assessment. **Try an example** opens an editable hypothetical customer-support forecast that runs the same calculations without saving portfolio records. Enter manual processing time and labor cost or use a saved baseline. Fill in AI costs and the workload or assessment window. Optional upper values show how the estimate changes as inputs vary. Open additional costs and business outcomes to include maintenance, infrastructure, rework, valuation, or assumptions for missing charges.

Use **Reports** to combine one analysis per workflow with the same forecast horizon or exactly matching assessment dates. Confirm that the selected analyses cover distinct costs and benefits before calculating a report. Overview shows a workflow-level financial summary until a matching organization report is calculated. Reports are available for the current session and can be downloaded as JSON. Manage organizations and the optional workspace access key in **Settings**.

For a PDF demo, open the invoice adapter and upload `backend/sample_invoice.pdf`. To attach future invoice attempts to a portfolio deployment, create a deployment with `adapter: invoice`, declare `validation_passed` on its workflow if desired, set `INVOICE_DEPLOYMENT_ID` to that deployment UUID, and restart the API. A configured invoice run writes the legacy event and standardized event in one transaction. Historical events retain their original meaning and do not get assigned to an organization by inference. Set `INVOICE_TELEMETRY_ORIGIN=synthetic` when using a deployment exclusively for sample documents.

## Domain and API

| Entity | Role |
| --- | --- |
| Organization | Owns workflows and defines the portfolio being assessed |
| Workflow | Defines department, business unit of work, available outcome metrics, and a unique benefit-attribution pool |
| Baseline scenario | Stores the evidence reference, manual unit cost range, and comparable outcome ranges |
| AI deployment | Identifies a deployed workflow version and its adapter |
| Execution | Stores standardized volume, review, rework, usage, latency, and cost telemetry with a unique upstream run ID per deployment |
| Business outcome | Stores a configured metric and measured value tied to an execution |
| ROI analysis | Saves a forecast or assessment with its inputs, observation snapshot, and derived estimates |

Create organizations at `POST /portfolio/organizations` and workflows at `POST /portfolio/organizations/{id}/workflows`. Under `/portfolio/workflows/{id}`, use `POST /baselines`, `POST /deployments`, `POST /forecasts`, and `POST /assessments`. Record telemetry through `POST /portfolio/deployments/{id}/executions`. The service desk adapter accepts ticket resolution, escalation, reopening, and review events at `POST /adapters/service-desk/deployments/{id}/tickets` and maps them to the same execution contract. The dashboard submits these requests from the guided evaluator. The [OpenAPI reference](http://localhost:8000/docs) lists field schemas and the demo script supplies working request examples.

Generic outcome values are additive across work units in an execution. Baseline and forecast outcome values are defined per unit. To monetize a metric, set its direction to `1` when higher is better or `-1` when lower is better and supply a USD valuation range. Assessment requires complete coverage for each monetized metric. Unresolved tickets omit resolution time, so a window containing those tickets can still value escalation or resolution counts while a resolution-time valuation requires a cohort with complete duration coverage.

## Economics and evidence

- **Pre-adoption forecast.** Use a period in months, expected workload, review and rework fractions, variable and fixed recurring costs, implementation cost, and optional outcome valuations. The analysis records these as assumptions.
- **Post-adoption assessment.** Use one deployment and a past interval with an inclusive start and exclusive end. The model uses recorded volume, review and rework units, provider charges when recorded, and business outcomes. Labor rates, implementation cost, and baseline behavior remain evidence-linked inputs. Supply explicit ranges for executions with missing model or infrastructure cost. Provider charges take precedence over priced estimates for the same model run. Synthetic and measured events require separate assessment windows or deployments.
- **Derived results.** Counterfactual manual cost equals baseline cost per unit times volume. Modeled benefit adds the valued business-outcome delta. Operating cost includes variable model and infrastructure charges, recurring fixed costs, maintenance, human review, and rework. Net benefit subtracts operating and one-time implementation costs from modeled benefit. ROI divides net benefit by total cost when the denominator is positive across the input bounds. For assessments, recurring monthly inputs are prorated on a 30.4375-day month. Payback projects stable recurring net benefit from the same inputs and is open-ended when some scenarios lack positive recurring benefit. Each assessment includes the full implementation cost and represents a standalone comparison.
- **Uncertainty.** The engine propagates low and high input bounds and reports the dollar span for each component. Independent interval arithmetic can produce conservative outer bounds because volume affects both costs and benefits. The ranges describe input sensitivity. They are not statistical confidence intervals, evidence of realized cash savings, or audited financial results.
- **Attribution.** Roll-ups require unique workflow benefit pools, one analysis per workflow, matching reporting windows, disjoint synthetic and measured assessments, and explicit confirmation that attribution is disjoint. Enter shared costs and benefits once using unique attribution keys and the amount for the selected period. The operator must validate that differently named line items represent distinct underlying costs and benefits. Avoid valuing the same staff capacity in both the manual baseline and an additional outcome metric.
- **Scope.** The platform supports internal single-workspace evaluation. Baseline representativeness, pricing, valuation, and measurement coverage determine how the estimates can be used. Economics use USD. Extracted invoice amounts keep their source currency.

## Configuration

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy PostgreSQL DSN. Existing local value can be retained. |
| `COMPOSE_DATABASE_URL`, `POSTGRES_PASSWORD` | Required for the local Compose stack. The sample file derives the DSN from a URL-safe password. If setting the DSN explicitly, URL-encode any special characters in its password. PostgreSQL's initialization password applies to a new data directory. |
| `WORKSPACE_API_KEY` | Optional shared API key for loopback development. Set it for any shared deployment and pass it as `X-Workspace-Key` or apply it in the dashboard. |
| `EXTRACTION_PROVIDER` | `rules` by default, `openai` for direct OpenAI, or `compatible` for a configured Chat Completions gateway that supports strict JSON Schema. |
| `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`, `LLM_TIMEOUT_SECONDS` | Server-side provider authentication, model, URL, and timeout. Custom non-loopback endpoints require HTTPS. |
| `LLM_PRICING_JSON` | Map of `provider:response-model` to explicit USD rates per million input/output tokens and a pricing source. Unconfigured rates remain unknown. |
| `LLM_USAGE_COST_IS_USD` | Enable only for a compatible gateway whose `usage.cost` is documented as a USD per-request charge. Direct OpenAI extraction records token usage and uses configured estimates. |
| `INVOICE_DEPLOYMENT_ID`, `INVOICE_TELEMETRY_ORIGIN` | Optional destination for invoice adapter telemetry and its measured or synthetic provenance. |
| `STATIC_DIR` | Built dashboard directory if serving the frontend from FastAPI. |

Example of the **shape** of a pricing catalog with placeholder rates. Replace the model key, rates, and evidence with verified values before using it for estimates.

```dotenv
LLM_PRICING_JSON={"openai:replace-with-response-model":{"input_per_million":"0","output_per_million":"0","source":"Replace with verified pricing and effective date"}}
```

Pricing snapshots record the effective rates per run. Estimation uses all reported input tokens at the configured input rate, without applying cached-token discounts or billing adjustments. Confirm the provider's response model identifier and rate assumptions. Hosted extraction sends bounded PDF text to the configured provider and uses only structured extraction output followed by local validation. See [OpenAI Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs).

## Evaluation and tests

From `backend`, run the automated suite and the invoice evaluation. The test suite uses an isolated database and mock provider HTTP responses. The evaluator submits six generated PDFs with independent labels and records extraction denominators, mismatch detection, rejection decisions, HTTP status, latency, and available cost coverage. It exercises the selected server extractor and writes execution events, so target a dedicated evaluation instance. The rules baseline is expected to miss the alternate layout. A hosted run can incur provider charges.

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe evaluate.py --base-url http://127.0.0.1:8000 --output evaluation-report-local.json
```

Run `npm test` under `frontend` for evaluator and financial chart interaction tests. Run `npm run build` under `frontend` to type-check and build the dashboard. Keep synthetic results labeled and compare hosted and rules runs using the same corpus and isolated instances.

## Local performance benchmark

The synthetic forecast preview completed 7,918 timed loopback requests across concurrency 1, 5, 10, and 20 with no observed errors or timeouts. At concurrency 5, it reached 187.85 successful requests/s with 42.45 ms client-observed p95. An isolated PostgreSQL 17.12 run measured 0.080 ms server-side p95 for the indexed latest-25 lookup on 10,000 synthetic execution rows. Ten independent economics fixtures matched 66 expected result positions within decimal rounding. See [benchmark methodology and reproducible scripts](BENCHMARK_REPORT.md).

## Deploy

Build the container from the repository root with `docker build -f backend/Dockerfile -t agentledger .`. Use an internal network or a TLS-terminating proxy with organizational identity controls and request rate limits. Keep PostgreSQL private. Supply production secrets through the hosting platform, set a high-entropy workspace key, and use a managed PostgreSQL database or an operated equivalent. The container serves the frontend and API on port 8000 and runs as a non-root user. If the runtime account lacks schema permissions, apply migrations with a separate migration job and override the container command with `uvicorn main:app --host 0.0.0.0 --port 8000`. Use `/health` for process liveness.

The API bounds request bodies, PDF size and page count, and model input size. Invoice PDF bytes and extracted invoice text are not persisted by AgentLedger. Authorized users can see extracted fields in the upload response. The shared workspace key gates portfolio and telemetry access across the installation. Use isolated deployments for organizations requiring separate trust boundaries. Before enabling hosted extraction for enterprise documents, configure an approved provider and confirm the applicable data-handling terms.
