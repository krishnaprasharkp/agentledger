from fastapi import HTTPException

from domain import Deployment, Workflow
from portfolio import ExecutionInput, save_execution


def configured_invoice_deployment(db, deployment_id):
    if deployment_id is None:
        return None
    deployment = db.get(Deployment, deployment_id)
    if deployment is None or deployment.adapter != "invoice":
        raise HTTPException(503, "The configured invoice deployment is unavailable.")
    return deployment


def record_invoice_execution(db, deployment, invoice_run, data_origin):
    workflow = db.get(Workflow, deployment.workflow_id)
    no_model_request = invoice_run.model_latency_ms is None
    outcomes = {"validation_passed": int(invoice_run.validation_passed is True)}
    payload = ExecutionInput(
        external_run_id=str(invoice_run.run_id),
        occurred_at=invoice_run.created_at,
        units=1,
        data_origin=data_origin,
        reviewed_units=int(invoice_run.requires_human_review is True),
        reworked_units=int(invoice_run.status == "failure"),
        succeeded=invoice_run.status == "success",
        latency_ms=invoice_run.latency_ms,
        model=invoice_run.model,
        input_tokens=invoice_run.input_tokens if invoice_run.usage_reported else None,
        output_tokens=invoice_run.output_tokens if invoice_run.usage_reported else None,
        model_invoked=not no_model_request,
        model_charge_usd=invoice_run.provider_charge_usd,
        estimated_model_usd=invoice_run.estimated_cost_usd,
        estimated_model_evidence=invoice_run.pricing["source"] if invoice_run.pricing else None,
        outcomes={key: value for key, value in outcomes.items() if key in workflow.outcome_metrics},
    )
    save_execution(db, deployment, payload)
