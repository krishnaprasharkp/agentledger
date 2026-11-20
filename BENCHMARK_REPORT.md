# AgentLedger MVP benchmark

**Scope.** Loopback HTTP timing on the running FastAPI app, PostgreSQL query execution in a disposable database, and numerical checks on the current backend source. Only synthetic inputs were used. The HTTP benchmark called the in-memory forecast preview. It did not use the save endpoint, insert demo data, or contact an AI provider. The database benchmark used a new PostgreSQL container with a temporary in-memory data directory and stopped only that container. The running application and its database were left in place.

## 1. Forecast API latency and throughput

Target was Docker Compose’s running FastAPI service at `http://127.0.0.1:8001`. Its live OpenAPI document identifies **POST /portfolio/forecasts/preview** as **ForecastPreview**. The endpoint computes estimates without saving an analysis.

The required request fields are `evidence`, `baseline`, `months`, `units_monthly`, `implementation_usd`, `fixed_model_usd_monthly`, `fixed_infrastructure_usd_monthly`, `maintenance_usd_monthly`, `review_usd_per_unit`, `rework_usd_per_unit`, `model_usd_per_unit`, `infrastructure_usd_per_unit`, `review_fraction`, and `rework_fraction`. A baseline contains `name`, `evidence`, and `manual_cost_usd_per_unit`, with optional `outcome_per_unit`. Ranges use decimal low/high values, and months is an integer. The workload also supplied `outcome_valuation` and `expected_outcomes_per_unit` to exercise outcome calculations. Each client used 32 generated, valid support-workload payloads with 6-, 12-, and 24-month horizons and seed 1729.

| Concurrent requests | Timed seconds | Timed requests | p50 ms | p95 ms | p99 ms | HTTP completions/s | Successful/s | Errors | Timeouts |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 15.00 | 1,845 | 7.40 | 11.23 | 23.39 | 122.96 | 122.96 | 0 (0%) | 0 |
| 5 | 15.01 | 2,820 | 23.75 | 42.45 | 72.89 | 187.85 | 187.85 | 0 (0%) | 0 |
| 10 | 15.04 | 1,770 | 44.81 | 335.26 | 639.55 | 117.65 | 117.65 | 0 (0%) | 0 |
| 20 | 16.00 | 1,483 | 117.07 | 663.67 | 1,124.84 | 92.69 | 92.69 | 0 (0%) | 0 |

**Method.** A Windows Python HTTPX async client used a closed-loop workload, one outstanding call per worker, HTTP connection reuse, a five-second HTTPX timeout, and monotonic wall-clock timing. Each concurrency ran once in increasing order, with five seconds of untimed warm-up and a 15-second request-launch window. Requests still in flight at the end were drained and included in both counts and elapsed throughput time. Preflight sent each payload once. The 32 preflight requests and 2,380 warm-up attempts were excluded from timed stats. There were **7,918 timed requests over 61.06 seconds**. Success required HTTP 200 and the expected estimate field. Error rate counts unsuccessful attempts, including timeout or transport failure. Latency percentiles use nearest rank among successes.

**Interpretation.** These are client-observed end-to-end times, including loopback, Docker networking, request work, and response decoding and checks. The app supplied no server-timing header, so isolated processing time was unavailable. Throughput peaked at concurrency 5 in this run, while p95 and p99 climbed at higher concurrency. This single-host result does not establish the cause or production capacity. It excludes real network transit, persisted analysis writes, and provider latency. [HTTP results and live required fields](backend/tests/benchmarks/api_results.json)

## 2. PostgreSQL queries

A **record** is one row in `workflow_executions`, representing one synthetic workflow execution. Each dataset used one organization, one workflow, and 16 deployments. Only execution row count varied. No outcome or analysis rows were seeded. The generator used seed 1729, 30 days of UTC timestamps, and a synthetic success flag. Each dataset lived in its own fresh schema created by the repository migration.

| Execution rows | Heap bytes | Index bytes | Execution table total bytes |
| ---: | ---: | ---: | ---: |
| 100 | 40,960 | 49,152 | 131,072 |
| 1,000 | 376,832 | 212,992 | 630,784 |
| 10,000 | 3,727,360 | 1,728,512 | 5,496,832 |

Total means PostgreSQL’s `pg_total_relation_size` for the execution table, including auxiliary storage and indexes. It excludes the rest of the database and WAL.

| Rows | Query | Median execution ms | p95 execution ms | Representative plan |
| ---: | --- | ---: | ---: | --- |
| 100 | Latest 25 for one deployment | 0.038 | 0.065 | Sequential scan, sort, limit |
| 100 | One deployment, ten-day assessment window | 0.029 | 0.065 | Sequential scan, limit |
| 100 | Fleet-wide failure count by JSON telemetry flag | 0.220 | 0.327 | Sequential scan, aggregate |
| 1,000 | Latest 25 for one deployment | 0.139 | 0.222 | Composite bitmap index scan, bitmap heap scan, sort, limit |
| 1,000 | One deployment, ten-day assessment window | 0.049 | 0.083 | Composite bitmap index scan, bitmap heap scan, limit |
| 1,000 | Fleet-wide failure count by JSON telemetry flag | 1.811 | 2.544 | Sequential scan, aggregate |
| 10,000 | Latest 25 for one deployment | 0.042 | 0.080 | Backward composite index scan, limit |
| 10,000 | One deployment, ten-day assessment window | 0.187 | 0.323 | Composite bitmap index scan, bitmap heap scan, limit |
| 10,000 | Fleet-wide failure count by JSON telemetry flag | 21.681 | 27.152 | Sequential scan, aggregate |

**Method.** Run `VACUUM (ANALYZE)` per dataset. Then run each query on one connection with 20 excluded warm-ups and 200 measured repetitions under `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`. There were **1,800 timed executions**, 180 warm-ups, and approximately **10.43 seconds** across query loops including their warm-ups. That duration excludes database startup, fixture insertion, vacuum, and cleanup. Median is the mean of the two middle samples and p95 uses nearest rank. Table timings use PostgreSQL's instrumented **Execution Time**. Planning times are separately recorded in the JSON. For 10,000 rows, planning median/p95 was 0.061/0.108 ms for latest executions, 0.068/0.107 ms for the assessment window, and 0.103/0.153 ms for the fleet-wide count.

**Interpretation.** The application queries represented are the deployment's recent execution lookup and the assessment's execution retrieval. The fleet-wide count is a representative telemetry investigation using an unindexed JSON field. It is not an app endpoint. PostgreSQL chose `ix_workflow_executions_deployment_time` for the two deployment-filtered queries at 1,000 and 10,000 rows. The failure count scanned the full execution table. These are different queries, so their timing difference does not quantify an index speedup. Results are single-client, warm-cache figures with temporary memory-backed storage and plan instrumentation. They do not measure cold disk, full assessment response time, outcome lookups, or concurrent database load. [Measured query results and representative JSON plans](backend/tests/benchmarks/postgres_results.json)

## 3. Numerical correctness

The direct Python benchmark exercised **10 hand-specified economic scenarios** with **66 result positions**. Expected numbers were represented as exact rational fractions, independent of the implementation's decimal arithmetic. The assessment fixture includes missing-cost ranges, and the roll-up fixture checks aggregate arithmetic. Existing backend tests also check endpoint wiring, reporting windows, provenance, and attribution safeguards. All inputs are synthetic.

| Fixture | Independently expected → actual net benefit (USD) | Independently expected → actual ROI | Independently expected → actual payback (months) |
| --- | --- | --- | --- |
| Positive | $13 → $13 | 14.9425% → 14.9425% | 1 → 1 |
| Negative | −$24 → −$24 | −19.3548% → −19.3548% | 3.8462 → 3.8462 |
| Zero volume, fixed costs | −$37 → −$37 | −100% → −100% | unavailable → unavailable |
| Exact break-even, zero setup | $0 → $0 | 0% → 0% | 0 → 0 |
| Zero total cost | $10 → $10 | undefined → undefined | 0 → 0 |
| Cost interval includes zero | −$5–$2 → −$5–$2 | undefined → undefined | 0 to unavailable → 0 to unavailable |
| Customer support, 6-minute lower input | −$9,600–$49,546 → same | −22.8571%–253.1215% → same | 1.6682–60 → same |
| Customer support, 7-minute lower input | −$4,200–$49,546 → same | −10%–253.1215% → same | 1.6682–18.4615 → same |
| Assessment with missing-cost ranges | −$1–$2 → same | −1.7544%–3.7037% → same | 0.8–1.1429 → same |
| Roll-up with shared costs | $11 → $11 | 5.8201% → 5.8201% | 1.4762 → 1.4762 |

The independently calculated customer-support manual-value sensitivity width fell from $36,720 to $31,320. Review and implementation spans were $8,046 and $4,000 in both runs. The engine matched each span. Forecast intervals are conservative outer bounds and can combine extremes that do not occur together.

| Metric | Defined positions | Undefined positions matched | Maximum absolute error | Maximum relative error |
| --- | ---: | ---: | ---: | ---: |
| Net benefit bounds (USD) | 20 | 0 | 0 | 0 |
| ROI bounds (ratio) | 16 | 4 | 3.739655 × 10⁻²⁸ | 1.477415 × 10⁻²⁸ |
| Payback bounds (months) | 17 | 3 | 1.538462 × 10⁻²⁷ | 1.290323 × 10⁻²⁸ |
| Selected sensitivity widths (USD) | 6 | 0 | 0 | 0 |

Relative error is absolute error divided by the expected magnitude, excluding zero and undefined expectations. Exact zeros were checked on absolute error. The nonzero differences are at decimal rounding scale. These fixtures verify calculations under specified assumptions. They do not validate general financial accuracy, realized savings, pricing, forecast calibration, or the completeness of telemetry. [Full expected values, actual values, and errors](backend/tests/benchmarks/numerical_results.json) · [Independent audit fixtures](ECONOMICS_AUDIT.md)

## 4. Environment and reproduction

| Item | Measured environment |
| --- | --- |
| Host | Windows 11 25H2, build 26200. Intel Core i7-1360P, 12 physical cores and 16 logical CPUs visible. 16,849,256,448 bytes (15.69 GiB) usable host RAM. |
| Docker | Docker Desktop engine 29.9.3, Linux 6.18.33.2 under WSL2. Docker VM reports 16 logical CPUs and 8,161,751,040 bytes (7.60 GiB) RAM. |
| HTTP service | Existing Compose API container, image tag `backend-api`, OpenAPI version 1.0.0, container Python 3.13.18. Docker reported no explicit per-container CPU or memory limit. |
| Bench drivers | Windows Python 3.13.5 and HTTPX 0.28.1. Numerical benchmark ran directly in Python without database queries. |
| Database | PostgreSQL 17.12 on Linux x86-64 in an isolated `postgres:17` container. `shared_buffers` 128 MiB, `effective_cache_size` 4 GiB, `max_parallel_workers_per_gather` 2, JIT on, and I/O timing off. |

From `backend`, use the existing local development Python environment. The HTTP command needs the API listening on port 8001. The PostgreSQL launcher expects Docker on PATH or accepts its executable with `-Docker`.

```powershell
.\.venv\Scripts\python.exe tests/benchmarks/api_latency.py --output tests/benchmarks/api_results.json
.\tests\benchmarks\run_isolated_postgres.ps1
.\.venv\Scripts\python.exe tests/benchmarks/numerical_correctness.py --output tests/benchmarks/numerical_results.json
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Run the HTTP and database benchmarks sequentially to avoid them competing for resources. The database launcher generates a disposable database name and secret, requires an empty database, publishes a random loopback port, and stops only its own container. Existing Compose volumes are outside its scope. The HTTP client sends only to the loopback preview route and uses the workspace key from the environment if needed. Neither script logs credentials.

**Post-benchmark tests.** Backend **48 passed**, with one existing Starlette TestClient deprecation warning. Frontend **4 passed** using `npm test` and the default mocked API. No product code or financial definitions were changed.

## README-ready summary

> On a Windows 11 laptop with a Docker Desktop FastAPI service, the synthetic forecast preview handled 7,918 timed requests across concurrency 1, 5, 10, and 20 with no observed errors or timeouts. At concurrency 5, it achieved 187.85 successful requests/s with 42.45 ms client-observed p95. In isolated PostgreSQL 17.12, the indexed latest-25 execution lookup had 0.080 ms server-side p95 over 10,000 synthetic execution rows and 200 measured repetitions. Ten independent economics fixtures matched all 66 tested result positions within decimal rounding.

## Defensible résumé metrics

1. **API:** Measured **187.85 successful forecast previews/s at concurrency 5** with **42.45 ms p95 client-observed latency** on one local Docker Desktop deployment. That phase completed **2,820 timed requests**.
2. **Reliability during the benchmark:** **7,918 of 7,918 timed requests succeeded**, with **zero observed timeouts**, across concurrency levels 1, 5, 10, and 20. Describe this as the local benchmark result.
3. **Database:** Measured **0.080 ms PostgreSQL execution p95** over **200 warmed repetitions** of the indexed latest-25 query on **10,000 synthetic execution records**. State that this was an isolated, warm-cache benchmark.
4. **Numerics:** Reconciled **10 independent economic scenarios across 66 expected result positions**, including exact break-even and undefined ROI. Net benefit and selected sensitivity widths matched exactly in the fixtures. The maximum absolute ROI error was **3.74 × 10⁻²⁸ as a ratio**.

The measurements do not support claims about production capacity, a percentage speedup, real customer workloads, realized savings, or provider cost and latency.
