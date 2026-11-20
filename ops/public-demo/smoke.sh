#!/usr/bin/env bash
# Validate the public surface over HTTPS using the system trust store.
set -euo pipefail
origin=${1:-}
resolve=${2:-}
[[ $origin =~ ^https://[a-zA-Z0-9.-]+(:[0-9]+)?$ ]] || {
    echo 'Usage: bash smoke.sh https://demo.example.com [demo.example.com:443:127.0.0.1]' >&2
    exit 1
}
request=(curl --silent --show-error --max-time 10 --noproxy '*')
[[ -z $resolve ]] || request+=(--resolve "$resolve")
"${request[@]}" --fail "$origin/health" | python3 -c '
import json, sys
if json.load(sys.stdin) != {"status": "healthy", "service": "agentledger-public-demo"}:
    sys.exit("Unexpected demo health response")
'
"${request[@]}" --fail "$origin/app-mode" | python3 -c '
import json, sys
if json.load(sys.stdin) != {"public_demo": True}:
    sys.exit("Public demo mode not active")
'
"${request[@]}" --fail "$origin/demo/portfolio" | python3 -c '
import json, sys
d = json.load(sys.stdin)
if d["organization"]["id"] != "demo" or not d["details"]:
    sys.exit("Synthetic portfolio missing")
'
"${request[@]}" --fail "$origin/" | python3 -c '
import sys
if "id=\"root\"" not in sys.stdin.read():
    sys.exit("Dashboard shell is missing")
'
for path in /portfolio/organizations /events /openapi.json; do
    status=$("${request[@]}" -o /dev/null -w '%{http_code}' "$origin$path")
    [[ $status == 404 ]] || { echo "Unexpected read exposure at $path (HTTP $status)" >&2; exit 1; }
done
for path in /portfolio/forecasts/preview /events /invoices/upload /adapters/customer-support/deployments/example/synthetic-probes/example; do
    status=$("${request[@]}" -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' --data-binary '{}' "$origin$path")
    [[ $status == 404 ]] || { echo "Unexpected write exposure at $path (HTTP $status)" >&2; exit 1; }
done
python3 - <<'PY' | "${request[@]}" --fail -H 'Content-Type: application/json' --data-binary @- "$origin/demo/forecasts/preview" | python3 -c '
import json, sys
if json.load(sys.stdin)["estimates"]["period_net_benefit_usd"] != {"low": "4800", "high": "4800"}:
    sys.exit("Unexpected synthetic preview")
'
import json
zero = {"low": 0, "high": 0}
rates = {key: zero for key in (
    "implementation_usd", "fixed_model_usd_monthly", "fixed_infrastructure_usd_monthly",
    "maintenance_usd_monthly", "review_usd_per_unit", "rework_usd_per_unit",
    "model_usd_per_unit", "infrastructure_usd_per_unit", "review_fraction", "rework_fraction",
)}
print(json.dumps(dict(rates, evidence="Synthetic deployment smoke", months=12,
    units_monthly={"low": 100, "high": 100}, baseline={"name": "Synthetic", "evidence": "Smoke",
    "manual_cost_usd_per_unit": {"low": 4, "high": 4}})))
PY
echo 'Public HTTPS smoke checks passed.'
