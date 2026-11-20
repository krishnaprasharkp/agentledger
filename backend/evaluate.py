"""Score a deterministic synthetic PDF corpus against a running AgentLedger API."""
import argparse
import json
import os
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from statistics import median
from time import perf_counter_ns

import httpx
import pymupdf
from dotenv import load_dotenv

from invoice_agent.schemas import InvoiceData


@dataclass(frozen=True)
class Case:
    name: str
    pages: tuple[str, ...]
    expected: dict[str, str] | None
    validation: bool | None


def expected(number: str, total: str = "125.00"):
    return {
        "vendor_name": "Northwind Office Supplies", "invoice_number": number,
        "invoice_date": "2026-01-15", "currency": "USD", "subtotal": "100.00",
        "tax_amount": "25.00", "total_amount": total,
    }


def controlled(invoice: dict[str, str]) -> str:
    labels = ("Vendor", "Invoice Number", "Invoice Date", "Currency", "Subtotal", "Tax", "Total")
    return "\n".join(f"{label}: {value}" for label, value in zip(labels, invoice.values(), strict=True))


def corpus():
    standard = expected("EVAL-001")
    mismatch = expected("EVAL-002", "128.00")
    alternate = expected("EVAL-003")
    multipage = expected("EVAL-004")
    lines = controlled(multipage).splitlines()
    return [
        Case("controlled_valid", (controlled(standard),), standard, True),
        Case("controlled_discrepancy", (controlled(mismatch),), mismatch, False),
        Case("alternate_layout", (
            "Supplier: Northwind Office Supplies\nDocument ID: EVAL-003\nIssued 15 January 2026\n"
            "All amounts USD\nNet 100.00\nSales tax 25.00\nAmount due 125.00",
        ), alternate, True),
        Case("multiple_pages", ("\n".join(lines[:4]), "\n".join(lines[4:])), multipage, True),
        Case("missing_currency", (
            "\n".join(line for line in controlled(expected("EVAL-005")).splitlines()
                      if not line.startswith("Currency:")),
        ), None, None),
        Case("blank_pdf", ("",), None, None),
    ]


def pdf(case: Case) -> bytes:
    with pymupdf.open() as document:
        for page in case.pages:
            document.new_page().insert_text((72, 72), page)
        return document.tobytes()


def evaluate(client: httpx.Client):
    rows = []
    for case in corpus():
        start = perf_counter_ns()
        response = client.post("/invoices/process", files={"file": (case.name + ".pdf", pdf(case), "application/pdf")})
        latency_ms = (perf_counter_ns() - start) // 1_000_000
        # Authentication and infrastructure failures must never masquerade as correct rejections.
        if response.status_code not in {200, 422, 502, 503, 504}:
            response.raise_for_status()
            raise RuntimeError(f"Unexpected response {response.status_code} for {case.name}")
        run_id = response.headers.get("X-Run-ID")
        payload = response.json()
        fields = {}
        validation_match = None
        decision_correct = None
        if case.expected:
            actual = InvoiceData.model_validate(payload["invoice"]) if response.status_code == 200 else None
            truth = InvoiceData.model_validate(case.expected)
            fields = {key: actual is not None and getattr(actual, key) == getattr(truth, key)
                      for key in case.expected}
            validation_match = response.status_code == 200 and payload["validation"]["is_valid"] == case.validation
        else:
            decision_correct = response.status_code == 422
        execution = payload.get("execution", {})
        rows.append({
            "case": case.name, "status_code": response.status_code,
            "run_id": execution.get("run_id", run_id),
            "model": execution.get("model"),
            "field_matches": fields, "validation_match": validation_match, "correct_rejection": decision_correct,
            "client_latency_ms": latency_ms,
            "input_tokens": execution.get("input_tokens") if execution.get("usage_reported") else None,
            "output_tokens": execution.get("output_tokens") if execution.get("usage_reported") else None,
            "provider_charge_usd": execution.get("provider_charge_usd"),
            "estimated_cost_usd": execution.get("estimated_cost_usd"),
        })
    field_counts = Counter()
    field_matches = Counter()
    for row in rows:
        field_counts.update(row["field_matches"].keys())
        field_matches.update(row["field_matches"])
    labelled = [row for row in rows if row["field_matches"]]
    rejected = [row for row in rows if row["correct_rejection"] is not None]
    return {
        "dataset": "agentledger-synthetic-v1",
        "cases": rows,
        "summary": {
            "exact_invoice_matches": sum(all(row["field_matches"].values()) for row in labelled),
            "extractable_cases": len(labelled),
            "field_accuracy": {key: field_matches[key] / total for key, total in field_counts.items()},
            "validation_matches": sum(row["validation_match"] for row in labelled),
            "correct_rejections": sum(row["correct_rejection"] for row in rejected),
            "rejection_cases": len(rejected),
            "http_status_counts": dict(Counter(row["status_code"] for row in rows)),
            "median_client_latency_ms": median(row["client_latency_ms"] for row in rows),
            "successful_runs_with_usage": sum(row["input_tokens"] is not None for row in rows),
            "successful_provider_charge_usd": str(sum(
                (Decimal(row["provider_charge_usd"]) for row in rows if row["provider_charge_usd"] is not None),
                Decimal(0),
            )),
            "successful_billed_or_estimated_runs": sum(
                row["provider_charge_usd"] is not None or row["estimated_cost_usd"] is not None for row in rows
            ),
        },
    }


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    headers = {"X-Workspace-Key": os.environ["WORKSPACE_API_KEY"]} if os.getenv("WORKSPACE_API_KEY") else {}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=150) as client:
        report = evaluate(client)
    encoded = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
