"""Closed-loop HTTP benchmark of the non-persisting forecast endpoint (loopback only)."""
import argparse
import asyncio
import json
import math
import os
import platform
import random
from collections import Counter
from pathlib import Path
from time import perf_counter

import httpx

ROUTE = "/portfolio/forecasts/preview"
SEED = 1729


def bounds(low, high=None):
    return {"low": str(low), "high": str(low if high is None else high)}


def payloads():
    rng = random.Random(SEED)
    for i in range(32):
        volume = rng.randrange(250, 3000)
        yield {
            "evidence": "Synthetic benchmark workload",
            "baseline": {"name": "Benchmark manual cost", "evidence": "Synthetic",
                         "manual_cost_usd_per_unit": bounds(3, "4.8"),
                         "outcome_per_unit": {"escalations": bounds(".1", ".15")}},
            "months": (6, 12, 24)[i % 3],
            "units_monthly": bounds(volume, volume + 200),
            "implementation_usd": bounds(8000, 12000),
            "fixed_model_usd_monthly": bounds(0, 80),
            "fixed_infrastructure_usd_monthly": bounds(80, 120),
            "maintenance_usd_monthly": bounds(250, 400),
            "review_usd_per_unit": bounds("1.5", "2.1"),
            "rework_usd_per_unit": bounds(3, 5),
            "model_usd_per_unit": bounds(".14", ".23"),
            "infrastructure_usd_per_unit": bounds(".04", ".08"),
            "review_fraction": bounds(".25", ".4"),
            "rework_fraction": bounds(".05", ".1"),
            "outcome_valuation": {"escalations": {"direction": -1, "usd_per_metric_unit": bounds(2, 3)}},
            "expected_outcomes_per_unit": {"escalations": bounds(".05", ".09")},
        }


def percentile(values, p):
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * p) - 1] if ordered else None


async def phase(client, concurrency, seconds, bodies):
    start = perf_counter()
    deadline = start + seconds

    async def worker(worker_id):
        results = []
        sequence = worker_id
        while perf_counter() < deadline:
            begin = perf_counter()
            timing_header = False
            try:
                response = await client.post(ROUTE, content=bodies[sequence % len(bodies)])
                timing_header = "server-timing" in response.headers
                status = str(response.status_code)
                if response.status_code == 200:
                    try:
                        status = "200" if "period_net_benefit_usd" in response.json()["estimates"] else "invalid_body"
                    except (ValueError, KeyError, TypeError):
                        status = "invalid_body"
            except httpx.TimeoutException:
                status = "timeout"
            except httpx.RequestError:
                status = "transport_error"
            elapsed_ms = (perf_counter() - begin) * 1000
            results.append((elapsed_ms, status, timing_header))
            sequence += concurrency
        return results

    blocks = await asyncio.gather(*(worker(i) for i in range(concurrency)))
    elapsed = perf_counter() - start
    results = [result for block in blocks for result in block]
    statuses = Counter(row[1] for row in results)
    success = [row[0] for row in results if row[1] == "200"]
    total = len(results)
    complete = sum(count for key, count in statuses.items() if key.isdecimal() or key == "invalid_body")
    return {
        "concurrency": concurrency, "seconds": elapsed, "attempts": total, "completed_http": complete,
        "successful": len(success), "http_completion_per_second": complete / elapsed,
        "success_per_second": len(success) / elapsed, "error_rate": (total - len(success)) / total,
        "timeouts": statuses["timeout"], "statuses": dict(statuses), "server_timing_header_count": sum(row[2] for row in results),
        "successful_latency_ms": {f"p{n}": percentile(success, n / 100) for n in (50, 95, 99)},
    }


async def main(args):
    origin = httpx.URL(args.origin)
    if (origin.scheme != "http" or origin.host not in {"127.0.0.1", "localhost", "::1"} or
            origin.userinfo or origin.path != "/" or origin.query or origin.fragment):
        raise SystemExit("Use a local HTTP origin without a path, credentials, or query.")
    headers = {"Content-Type": "application/json"}
    if os.getenv("WORKSPACE_API_KEY"):
        headers["X-Workspace-Key"] = os.environ["WORKSPACE_API_KEY"]
    bodies = [json.dumps(body, separators=(",", ":")).encode() for body in payloads()]
    health = {}
    async with httpx.AsyncClient(base_url=origin, trust_env=False, timeout=args.timeout, headers=headers) as client:
        schema = (await client.get("/openapi.json")).raise_for_status().json()
        contract = schema["paths"][ROUTE]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        if not contract.endswith("/ForecastPreview"):
            raise SystemExit("Unexpected request contract for read-only preview.")
        required = schema["components"]["schemas"]["ForecastPreview"]["required"]
        for body in bodies:
            response = await client.post(ROUTE, content=body)
            response.raise_for_status()
            if "period_net_benefit_usd" not in response.json()["estimates"]:
                raise SystemExit("Preview preflight did not return forecast estimates.")
        health = (await client.get("/health")).raise_for_status().json()
    runs = []
    for concurrency in (1, 5, 10, 20):
        limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
        async with httpx.AsyncClient(base_url=origin, limits=limits, timeout=args.timeout,
                                     headers=headers, trust_env=False) as client:
            warm = await phase(client, concurrency, args.warmup, bodies)
            if warm["error_rate"]:
                raise SystemExit("Warm-up returned failures at concurrency " + str(concurrency))
            run = await phase(client, concurrency, args.seconds, bodies)
            run["warmup"] = warm
            runs.append(run)
            print(f"Completed concurrency {concurrency}: {run['successful']} successful", flush=True)
    data = {
        "target": str(origin), "route": ROUTE, "openapi_version": schema["info"]["version"],
        "required_fields": required, "health_status": health.get("status"), "seed": SEED,
        "payload_count": len(bodies), "preflight_count": len(bodies), "warmup_seconds": args.warmup,
        "target_timed_seconds": args.seconds, "timeout_seconds_httpx": args.timeout, "python": platform.python_version(),
        "client_os": platform.platform(), "httpx": httpx.__version__, "runs": runs,
    }
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="http://127.0.0.1:8001")
    parser.add_argument("--warmup", type=float, default=5)
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--output", type=Path, required=True)
    opts = parser.parse_args()
    if min(opts.warmup, opts.seconds, opts.timeout) <= 0:
        parser.error("Timing parameters must be positive.")
    asyncio.run(main(opts))
