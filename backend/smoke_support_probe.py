"""Run or inspect one explicitly authorized support probe against a local AgentLedger API."""
import argparse
import json
import os
from uuid import UUID

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--deployment-id", required=True, type=UUID)
    parser.add_argument("--attempt-id", required=True, type=UUID)
    parser.add_argument("--authorize-live-request", action="store_true")
    args = parser.parse_args()
    if not args.authorize_live_request:
        parser.error("The potentially billable request requires --authorize-live-request.")
    origin = httpx.URL(args.base_url)
    if (
        origin.scheme not in {"http", "https"} or origin.host not in {"localhost", "127.0.0.1", "::1"}
        or origin.userinfo or origin.query or origin.fragment or origin.path not in {"", "/"}
    ):
        parser.error("Use a loopback AgentLedger origin.")
    workspace_key = os.getenv("WORKSPACE_API_KEY")
    headers = {"X-Workspace-Key": workspace_key} if workspace_key else {}
    path = f"/adapters/customer-support/deployments/{args.deployment_id}/synthetic-probes/{args.attempt_id}"
    try:
        with httpx.Client(base_url=origin, timeout=150, follow_redirects=False, trust_env=False) as client:
            result = client.post(path, headers=headers, json={"authorize_live_request": True})
    except httpx.RequestError:
        print("No response from AgentLedger. Reuse the same attempt ID to inspect or resume safely.")
        return 2
    if not result.is_success:
        print(f"AgentLedger rejected the request (HTTP {result.status_code}).")
        return 2
    row = result.json()
    print(json.dumps(row, indent=2))
    return 0 if row["telemetry"]["provider_evidence"]["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
