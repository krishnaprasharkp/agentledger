"""Populate a named synthetic organization through the public AgentLedger API."""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
from dotenv import load_dotenv


def bounds(low, high=None):
    return {"low": low, "high": low if high is None else high}


def post(client, path, payload):
    response = client.post(path, json=payload)
    if not response.is_success:
        raise RuntimeError(f"{path} returned {response.status_code}: {response.text}")
    return response.json()


def seed(client):
    name = "Northwind | Synthetic demo " + uuid4().hex[:8]
    organization = post(client, "/portfolio/organizations", {"name": name})
    now = datetime.now(timezone.utc)
    end = now - timedelta(seconds=5)
    start = end - timedelta(days=30)
    forecasts, assessments, deployments = [], [], {}
    examples = (
        ("Invoice intake", "Finance", "invoice", "invoice", "validation_passed", 12, 6),
        ("Service desk triage", "Information Technology", "ticket", "service_desk", "escalated", 24, 9),
    )
    for title, department, unit, adapter, metric, cost, volume in examples:
        flow = post(client, f"/portfolio/organizations/{organization['id']}/workflows", {
            "name": title, "department": department, "unit": unit, "benefit_pool": adapter + "_staff_capacity",
            "outcome_metrics": [metric],
        })
        path = f"/portfolio/workflows/{flow['id']}"
        baseline = post(client, path + "/baselines", {
            "name": "Illustrative manual workflow", "evidence": "Synthetic demo inputs. Replace with a documented time study.",
            "manual_cost_usd_per_unit": bounds(cost - 2, cost + 2),
            "outcome_per_unit": {metric: bounds(0.92, 0.98) if adapter == "invoice" else bounds(0.3, 0.5)},
        })
        deployment = post(client, path + "/deployments", {"name": title + " pilot", "adapter": adapter})
        deployment_id = deployment["id"]
        deployments[adapter] = deployment_id
        common = {
            "baseline_id": baseline["id"],
            "evidence": "Synthetic demonstration. All rates and valuations are illustrative inputs.",
            "implementation_usd": bounds(75, 110), "fixed_model_usd_monthly": bounds(0),
            "fixed_infrastructure_usd_monthly": bounds(2, 4), "maintenance_usd_monthly": bounds(10, 16),
            "review_usd_per_unit": bounds(2, 4), "rework_usd_per_unit": bounds(3, 7),
            "outcome_valuation": {
                metric: {"direction": 1 if adapter == "invoice" else -1, "usd_per_metric_unit": bounds(0, 1)},
            },
        }
        forecasts.append(post(client, path + "/forecasts", common | {
            "months": 12, "units_monthly": bounds(volume, volume * 2), "review_fraction": bounds(0.15, 0.35),
            "rework_fraction": bounds(0.05, 0.2), "model_usd_per_unit": bounds(0.01, 0.06),
            "infrastructure_usd_per_unit": bounds(0.01, 0.05),
            "expected_outcomes_per_unit": {
                metric: bounds(0.88, 0.98) if adapter == "invoice" else bounds(0.12, 0.28),
            },
        })["id"])
        for index in range(volume):
            at = (start + timedelta(days=2 + index * 2)).isoformat()
            run_id = f"synthetic-{adapter}-{index}"
            costs = {"model_charge_usd": "0.02", "infrastructure_charge_usd": "0.01", "data_origin": "synthetic"}
            if adapter == "invoice":
                post(client, f"/portfolio/deployments/{deployment_id}/executions", costs | {
                    "external_run_id": run_id, "occurred_at": at, "units": 1, "reviewed_units": int(index % 3 == 0),
                    "reworked_units": int(index == 0), "succeeded": True, "latency_ms": 250 + 30 * index,
                    "outcomes": {metric: int(index != 0)},
                })
            else:
                post(client, f"/adapters/service-desk/deployments/{deployment_id}/tickets", costs | {
                    "ticket_run_id": run_id, "opened_at": (datetime.fromisoformat(at) - timedelta(minutes=20)).isoformat(),
                    "resolved_at": at, "escalated": index % 4 == 0, "reopened": index == 1,
                    "human_reviewed": index % 3 == 0, "agent_latency_ms": 400 + 25 * index,
                })
        assessments.append(post(client, path + "/assessments", common | {
            "deployment_id": deployment_id, "start": start.isoformat(), "end": end.isoformat(),
        })["id"])
    rollup = post(client, f"/portfolio/organizations/{organization['id']}/rollup", {
        "analysis_ids": forecasts, "disjoint_attribution_confirmed": True,
        "shared_items": [{"key": "shared_platform_setup", "kind": "implementation", "usd": bounds(12, 18),
                          "evidence": "Synthetic shared platform setup, excluded from both workflows."}],
    })
    return {"organization": organization, "deployments": deployments, "forecasts": forecasts,
            "assessments": assessments, "synthetic_forecast_rollup": rollup}


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    headers = {"X-Workspace-Key": os.getenv("WORKSPACE_API_KEY", "")}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=30) as client:
        print(json.dumps(seed(client), indent=2))


if __name__ == "__main__":
    main()
