"""Profile execution queries on a newly created, disposable PostgreSQL database."""
import argparse
import json
import os
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from api_latency import percentile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
SEED = 1729
BENCHMARK_DB = re.compile(r"agentledger_bench_[a-f0-9]{12}")
SIZES = (100, 1000, 10_000)
DEPLOYMENTS = 16
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

QUERIES = {
    "latest_deployment_executions": (
        "SELECT id, deployment_id, external_run_id, occurred_at, telemetry FROM workflow_executions "
        "WHERE deployment_id = %s ORDER BY occurred_at DESC LIMIT 25",
        (UUID(int=100),),
    ),
    "assessment_window": (
        "SELECT id, deployment_id, external_run_id, occurred_at, telemetry FROM workflow_executions "
        "WHERE deployment_id = %s AND occurred_at >= %s AND occurred_at < %s LIMIT 10001",
        (UUID(int=100), T0 + timedelta(days=10), T0 + timedelta(days=20)),
    ),
    "failed_executions_across_deployments": (
        "SELECT count(*) FROM workflow_executions WHERE telemetry->>'succeeded' = %s",
        ("false",),
    ),
}


def seed(conn, count):
    conn.exec_driver_sql(
        "INSERT INTO organizations (id,name) VALUES (%s,%s)", (UUID(int=1), "Benchmark workspace"),
    )
    conn.exec_driver_sql(
        "INSERT INTO workflows (id,organization_id,name,department,unit,benefit_pool,outcome_metrics) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)", (UUID(int=2), UUID(int=1), "Support benchmark", "Support", "ticket", "bench", "[]"),
    )
    conn.exec_driver_sql(
        "INSERT INTO ai_deployments (id,workflow_id,name,adapter) VALUES (%s,%s,%s,%s)",
        [(UUID(int=i + 100), UUID(int=2), f"Synthetic deployment {i}", "generic") for i in range(DEPLOYMENTS)],
    )
    rng = random.Random(SEED)
    rows = []
    for n in range(count):
        deployment = UUID(int=100 + rng.randrange(DEPLOYMENTS))
        timestamp = T0 + timedelta(seconds=rng.randrange(30 * 86400))
        telemetry = json.dumps({"units": 1, "reviewed_units": int(n % 5 == 0), "reworked_units": 0,
                                "succeeded": rng.random() >= .1, "data_origin": "synthetic", "model": "rules",
                                "latency_ms": rng.randrange(10, 200), "input_tokens": None, "output_tokens": None,
                                "model_charge_usd": None, "estimated_model_usd": None, "infrastructure_charge_usd": None})
        rows.append((UUID(int=1000 + n), deployment, f"bench-{n:06d}", timestamp, telemetry))
    conn.exec_driver_sql(
        "INSERT INTO workflow_executions (id,deployment_id,external_run_id,occurred_at,telemetry) VALUES (%s,%s,%s,%s,%s)",
        rows,
    )


def node_summary(plan):
    yield {"node": plan["Node Type"], "index": plan.get("Index Name"), "actual_rows": plan.get("Actual Rows")}
    for child in plan.get("Plans", []):
        yield from node_summary(child)


def query_metrics(conn, samples, warmups, size):
    rows = {}
    for name, (query, parameters) in QUERIES.items():
        elapsed = []
        planning = []
        wall = perf_counter()
        for i in range(warmups + samples):
            statement = conn.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query, parameters).scalar_one()[0]
            if i >= warmups:
                elapsed.append(statement["Execution Time"])
                planning.append(statement["Planning Time"])
        rows[name] = {
            "execution_ms": {"median": (sorted(elapsed)[(samples - 1)//2] + sorted(elapsed)[samples//2])/2,
                             "p95": percentile(elapsed, .95)},
            "planning_ms": {"median": (sorted(planning)[(samples - 1)//2] + sorted(planning)[samples//2])/2,
                            "p95": percentile(planning, .95)},
            "measured_samples": samples, "warmups": warmups, "wall_seconds_with_warmup": perf_counter() - wall,
            "nodes": list(node_summary(statement["Plan"])), "example_explain": statement,
        }
    print(f"Completed {size} execution rows", flush=True)
    return rows


def main(args):
    url = make_url(os.environ["BENCHMARK_DATABASE_URL"])
    if (url.drivername != "postgresql+psycopg" or url.host != "127.0.0.1" or
            not url.port or url.port in (5432, 5433) or not BENCHMARK_DB.fullmatch(url.database or "")):
        raise SystemExit("Use the generated disposable database via the benchmark launcher.")
    # This is assigned before importing the repository's schema and migration.
    os.environ["DATABASE_URL"] = os.environ["BENCHMARK_DATABASE_URL"]
    from migrate import migrate

    engine = create_engine(url, hide_parameters=True)
    report = {"seed": SEED, "sizes": {}, "deployment_count_per_size": DEPLOYMENTS, "record": "workflow_executions row"}
    with engine.connect() as conn:
        if conn.exec_driver_sql(
            "SELECT count(*) FROM pg_catalog.pg_namespace "
            "WHERE nspname NOT IN ('public','information_schema') AND nspname NOT LIKE 'pg_%%'",
        ).scalar_one():
            raise SystemExit("Refusing a database that already has application or benchmark schemas.")
        if conn.exec_driver_sql(
            "SELECT count(*) FROM pg_catalog.pg_class WHERE relnamespace = 'public'::regnamespace",
        ).scalar_one():
            raise SystemExit("Refusing a database that already has public relations.")
        report["postgresql"] = conn.exec_driver_sql("SELECT version()").scalar_one()
        report["settings"] = dict(conn.exec_driver_sql(
            "SELECT name, setting || COALESCE(' ' || unit,'') FROM pg_settings WHERE name IN "
            "('shared_buffers','effective_cache_size','max_parallel_workers_per_gather','jit','track_io_timing')"
        ).all())
    for size in SIZES:
        namespace = f"sample_{size}"
        with engine.begin() as conn:
            conn.exec_driver_sql(f"CREATE SCHEMA {namespace}")
        dataset_engine = create_engine(url, connect_args={"options": "-c search_path=" + namespace}, hide_parameters=True)
        try:
            migrate(dataset_engine)
            with dataset_engine.begin() as conn:
                seed(conn, size)
            with dataset_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.exec_driver_sql("VACUUM (ANALYZE) workflow_executions")
                records, heap, indexes, total = conn.exec_driver_sql(
                    "SELECT count(*), pg_relation_size('workflow_executions'), "
                    "pg_indexes_size('workflow_executions'), pg_total_relation_size('workflow_executions') "
                    "FROM workflow_executions",
                ).one()
                report["sizes"][str(size)] = {
                    "records": records, "heap_bytes": heap, "index_bytes": indexes, "table_total_bytes": total,
                    "queries": query_metrics(conn, args.samples, args.warmup, size),
                }
        finally:
            dataset_engine.dispose()
    engine.dispose()
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=200)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    opts = parser.parse_args()
    if min(opts.samples, opts.warmup) < 1:
        parser.error("Sample counts must be positive.")
    main(opts)
