"""Apply forward-only additive migrations without replacing existing records."""
from sqlalchemy import inspect, text
import domain  # Register the portfolio tables before applying schema changes.

from database import engine
from db_models import AgentEventRecord

# Freeze the first telemetry migration independently of later model changes.
TELEMETRY_COLUMNS = {
    "workflow": "VARCHAR(32)",
    "provider": "VARCHAR(32)",
    "model_latency_ms": "INTEGER",
    "usage_reported": "BOOLEAN",
    "provider_charge_usd": "NUMERIC(30, 14)",
    "estimated_cost_usd": "NUMERIC(30, 14)",
    "pricing": "JSON",
    "provider_request_id": "VARCHAR(255)",
    "validation_passed": "BOOLEAN",
    "requires_human_review": "BOOLEAN",
    "error_code": "VARCHAR(64)",
}


def migrate(target=engine):
    with target.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(44512061)"))
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"
        ))
        applied = set(connection.execute(text("SELECT version FROM schema_migrations")).scalars())
        if 1 not in applied:
            AgentEventRecord.__table__.create(connection, checkfirst=True)
            existing = {column["name"] for column in inspect(connection).get_columns(AgentEventRecord.__tablename__)}
            for name, sql_type in TELEMETRY_COLUMNS.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE agent_events ADD COLUMN {name} {sql_type}"))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_agent_events_workflow_created_at "
                "ON agent_events (workflow, created_at)"
            ))
            connection.execute(text("INSERT INTO schema_migrations (version) VALUES (1)"))
        if 2 not in applied:
            for table in (
                domain.Organization, domain.Workflow, domain.Baseline, domain.Deployment,
                domain.Execution, domain.Outcome, domain.Analysis,
            ):
                table.__table__.create(connection, checkfirst=True)
            connection.execute(text("INSERT INTO schema_migrations (version) VALUES (2)"))


if __name__ == "__main__":
    migrate()
    print("AgentLedger migrations applied.")
