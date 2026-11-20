"""Public routes with no database dependencies or private workspace entry points."""
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from demo_portfolio import bounds
from portfolio import ForecastPreview, preview_forecast
from security import DEMO_PREVIEW_PATH, PublicDemoSecurity, WorkspaceSecurity


@lru_cache(maxsize=1)
def sample_portfolio():
    """Compute example estimates from fixed, fictional assumptions without inserting rows."""
    organization = {"id": "demo", "name": "Synthetic demo"}
    details = []
    for key, title, department, unit, volume, minutes in (
        ("support", "Customer support", "Operations", "ticket", 900, 6),
        ("invoice", "Invoice intake", "Finance", "invoice", 400, 4),
    ):
        evidence = "Synthetic demonstration assumptions"
        payload = ForecastPreview.model_validate({
            "months": 12, "units_monthly": bounds(volume, volume + 200), "evidence": evidence,
            "baseline": {"name": "Manual handling", "evidence": evidence,
                         "manual_cost_usd_per_unit": bounds(Decimal(minutes) / 2, Decimal(minutes) * Decimal(".6"))},
            "implementation_usd": bounds(5000, 9000), "fixed_model_usd_monthly": bounds(0),
            "fixed_infrastructure_usd_monthly": bounds(100, 200), "maintenance_usd_monthly": bounds(100, 250),
            "review_usd_per_unit": bounds(1, 2), "rework_usd_per_unit": bounds(2, 4),
            "model_usd_per_unit": bounds(.12, .22), "infrastructure_usd_per_unit": bounds(.02, .05),
            "review_fraction": bounds(.2, .4), "rework_fraction": bounds(.05, .1),
        })
        details.append({
            "workflow": {"id": key, "name": title, "department": department, "unit": unit,
                         "benefit_pool": key, "outcome_metrics": []},
            "baselines": [], "deployments": [],
            "analyses": [{
                "id": key + "-forecast", "mode": "forecast", "created_at": "2026-01-01T00:00:00Z",
                "deployment_id": None,
                "snapshot": {"baseline": payload.baseline.model_dump(mode="json"), "measured": None,
                             "prior_estimates": None, "assumptions": {"months": payload.months, "evidence": evidence},
                             "estimates": preview_forecast(payload)["estimates"]},
            }],
        })
    return {"organization": organization, "details": details}


def create_public_demo(static_dir: str = "") -> FastAPI:
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None, redirect_slashes=False)
    app.add_middleware(WorkspaceSecurity, require_key=True, json_limit=16 * 1024, body_timeout=10)
    app.add_middleware(PublicDemoSecurity)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(_request, _error):
        return JSONResponse({"detail": "Check the forecast fields and allowed ranges."}, status_code=422)

    @app.get("/health")
    def health():
        return {"status": "healthy", "service": "agentledger-public-demo"}

    @app.get("/app-mode")
    def app_mode():
        return JSONResponse({"public_demo": True}, headers={"Cache-Control": "no-store"})

    @app.get("/demo/portfolio")
    def portfolio():
        return sample_portfolio()

    app.add_api_route(DEMO_PREVIEW_PATH, preview_forecast, methods=["POST"])

    if static_dir:
        directory = Path(static_dir)
        app.mount("/assets", StaticFiles(directory=directory / "assets"), name="demo-assets")

        @app.get("/")
        def index():
            return FileResponse(directory / "index.html", headers={"Cache-Control": "no-store"})

    return app
