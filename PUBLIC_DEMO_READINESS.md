# AgentLedger public demo readiness

This release candidate exposes a synthetic demonstration. It does not provide customer accounts, tenant isolation, or a public interface to a private workspace. No public deployment has been authorized or performed.

## Boundaries

- **Public demo mode** builds a separate FastAPI application. It registers only the frontend shell and build assets, mode and health endpoints, a fixed synthetic portfolio, and a non-persisting forecast preview. The existing economics engine calculates both the example forecasts and visitor previews. Private organization, workflow, execution, report, upload, analytics, ingestion, and provider routes are absent. A supplied workspace-key header cannot enable any of them. API docs are disabled.
- **No private database, credentials, or provider access in the demo.** The standalone Compose stack starts no PostgreSQL service, uses an in-memory SQLite URL for imports, and connects the API only to an internal network. Public routes acquire no database sessions. The app rejects configuration that enables hosted extraction or a probe or supplies a provider or workspace key in public demo mode. The browser renders the existing design with read-only sample data and an anonymous preview. No key is embedded in the assets or sent by the demo client. The private frontend code may still be present in the shared build, so isolation is enforced by the server.
- **Private mode** requires a nonblank server-side WORKSPACE_API_KEY at startup. Existing key checks still protect private routes. This is a shared administrator credential. It provides no per-user or per-organization isolation. Keep this mode on a trusted private network or behind an identity-aware proxy. Never point the public proxy at it.
- **Local mode** retains development compatibility, including optional keyless access. The default development Compose API binds to loopback. Do not publish that service or assume local mode is safe behind a public proxy.
- **Limits.** Private event listings default to 100 rows, cap at 1,000, and bound the offset at 100,000. The demo preview requires a body no larger than 16 KiB. The HTTPS proxy enforces request and connection limits, short timeouts, and an explicit route allowlist. Accepted paths have a per-IP budget of 10 requests/second with burst 30. Previews also have a per-IP budget of 12/minute with burst 6. Connection limits are 12 per IP and 96 aggregate. Rate and connection rejections use 429. The directly exposed proxy keys limits on its TCP peer IP and ignores caller-provided forwarding headers. [NGINX rate limit reference](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html)

## Exact deployment requirements and launch

Use a host with Docker Compose v2 and a dedicated DNS name. The standalone stack terminates HTTPS on NGINX using TLS 1.2 or 1.3. Provide a PEM certificate chain valid for that hostname and its private key as separate files outside the repository, with mount access limited to the operator and proxy. Renew externally and reload the proxy after renewal. Use DNS-based certificate validation or a separately managed certificate process. The stack has no HTTP listener or redirect. Publish only HTTPS. [NGINX TLS reference](https://nginx.org/en/docs/http/ngx_http_ssl_module.html)

From `backend`, set the certificate paths and use a dedicated public-demo project name. Example PowerShell loopback preview after approval to start it:

```powershell
$env:DEMO_TLS_CERT = 'C:/secure/demo/fullchain.pem'
$env:DEMO_TLS_KEY = 'C:/secure/demo/privkey.pem'
$env:DEMO_BIND_ADDRESS = '127.0.0.1'
$env:DEMO_HTTPS_PORT = '8443'
docker compose -p agentledger-public-demo -f compose.public-demo.yaml config --quiet
docker compose -p agentledger-public-demo -f compose.public-demo.yaml up --build -d --wait
```

Use a hostname matching the certificate and a trusted CA for the preview. For an approved public launch, set the intended public bind address and HTTPS port, typically 443. Configure DNS and the host firewall to expose only that ingress port. Do not merge this Compose file with the development stack, mount a private database or dotenv file, or forward access to an alternate API port. Use host environment or a secret manager for private deployment credentials. The public demo needs none. Before a production release, pin reviewed image digests, scan dependencies and images, and check host resource limits.

Verify HTTPS identity, `/health`, `/app-mode`, `/demo/portfolio`, and the example workflow in a real browser. Verify that private paths fail from outside the host and there is no direct connection to the API service. Exercise expected request bursts and oversized requests from the intended ingress. If a CDN or upstream proxy is introduced, configure trusted client IPs explicitly and repeat rate-limit testing.

## Monitoring and recovery

The API container health check calls `/health`. Configure an external HTTPS monitor for certificate expiry and endpoint availability. Collect the proxy's structured logs, which record method, status, duration, and rate-limit result without query strings, credential headers, or request bodies. Alert on sustained 429 or 5xx responses, significant latency shifts, and unhealthy containers. Configure host log rotation, retention, resource alarms, and an owner for each alert. Send a test alarm and practice rollback to the last verified image and configuration before opening the demo to the public. Access logs are operational signals and do not establish security on their own.

**Demo recovery:** The stack has no database volume or persisted visitor work. Restore availability by restarting the last verified images with the reviewed configuration and valid TLS files, then run the smoke checks. Keep the previous image and configuration accessible.

**Private PostgreSQL backup plan:** Schedule encrypted, access-controlled, off-host PostgreSQL 17 backups independently of the demo. Use credentials via a protected libpq service/passfile or a secret manager. For a small v1 private database, schedule a daily custom dump with `pg_dump --format=custom --file=agentledger.dump` using the private service connection. Store roles separately or provision them from reviewed configuration. Restore a copy to a new isolated database using `pg_restore --exit-on-error --no-owner --dbname=isolated_restore agentledger.dump`. Verify migrations, table counts, access controls, and a representative analysis before declaring recovery. Use a managed PITR strategy if the accepted recovery-point target is shorter than the dump interval. Record retention and measured recovery-point and recovery-time objectives. Never test restore by overwriting the working database. [PostgreSQL 17 backup reference](https://www.postgresql.org/docs/17/app-pgdump.html)

## Verification and remaining blockers

Backend regression tests exercise anonymous synthetic reads and previews, verify no public route calls a DB dependency, reject private reads and writes with and without a workspace header, and cover blank-key private mode, event pagination, and the request-size cap. The frontend regression test exercises the customer-support preview and verifies that the client sends no workspace key.

**Results:** 67 backend tests and 8 frontend tests passed, and the production build succeeded. The backend emitted its existing TestClient deprecation warning. An isolated Compose stack bound to loopback with a temporary TLS certificate passed the NGINX syntax check, HTTPS health check, security-header and synthetic data checks, and a valid anonymous forecast preview. The proxy returned 404 for tested private paths and 413 for a 16,385-byte request. A burst of 12 invalid previews returned six validation errors and six HTTP 429 responses. The proxy emitted the expected structured rate-limit log signal. The temporary containers and networks were stopped and removed without touching PostgreSQL or any volume.

Release blockers remain operator-owned. Public DNS and trusted TLS, external monitoring and alert delivery, host resource alarms and limits, image review, and the private backup/restore and rollback drills need verification in the intended environment. Local tests do not establish production availability, DDoS resistance, incident response, or multi-tenant security. IP limits can affect visitors behind shared NAT and can be spread across many source addresses. The demo requires no real customer inputs, and the interface asks visitors to use synthetic values only.
