import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["EXTRACTION_PROVIDER"] = "rules"
os.environ["WORKSPACE_API_KEY"] = ""
os.environ["LLM_PRICING_JSON"] = "{}"
os.environ["STATIC_DIR"] = ""
os.environ.pop("INVOICE_DEPLOYMENT_ID", None)
os.environ["INVOICE_TELEMETRY_ORIGIN"] = "measured"

from database import Base, get_db
from main import app


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def override_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
