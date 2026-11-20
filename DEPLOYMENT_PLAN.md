# AgentLedger public demo deployment plan

## Scope and hosting

Use one **DigitalOcean Basic Regular Droplet with 1 vCPU, 2 GiB RAM, and 50 GiB SSD**, running Ubuntu 24.04 LTS on x86-64. Run the existing NGINX and FastAPI images with Docker Engine and Compose. NGINX serves the public TLS entry point and proxies the built React assets and synthetic API. Keep the production demo on a dedicated host and transfer the reviewed release over SSH. The source repository can stay private.

The Droplet is **US$12 per month before taxes**, including 2,000 GiB of monthly transfer at this size. Additional outbound transfer is US$0.01 per GiB. With an existing DNS zone, a free Let's Encrypt certificate, and basic free uptime monitoring, the planned baseline is US$12 per month. Domain registration, paid monitoring, taxes and overages are outside that estimate. DigitalOcean advertises trial credit for eligible customers. Budget for the recurring Droplet charge once any credit ends. [DigitalOcean Droplet pricing](https://www.digitalocean.com/pricing/droplets) · [Transfer charges](https://docs.digitalocean.com/products/droplets/details/pricing/) · [Let's Encrypt](https://letsencrypt.org/about/)

UptimeRobot's free plan provides basic checks at five-minute intervals. Budget for a separate certificate-expiry check because the managed expiry feature may require a paid plan. The single VM can go offline during recovery or maintenance. [UptimeRobot plan features](https://uptimerobot.com/pricing/)

| Surface | Exposure |
| --- | --- |
| NGINX TCP 443 | Public IPv4 after launch approval. During staging allow only authorized reviewer addresses. |
| SSH TCP 22 | Operator CIDR only, using key-based SSH. Use a DigitalOcean Cloud Firewall so filtering applies before Docker port publishing. |
| HTTP TCP 80 | Closed. Use DNS-01 for certificate issuance and renewal. |
| FastAPI TCP 8000 | Docker internal network only. Compose publishes no API port. |
| PostgreSQL/private workspace | Outside this host and deployment. No database service, persistent volume, private workspace key, or private data import. |

[DigitalOcean Cloud Firewall setup](https://docs.digitalocean.com/products/droplets/getting-started/recommended-droplet-setup/)

## Production configuration and safeguards

- The standalone Compose file fixes `APP_MODE=public_demo`, `EXTRACTION_PROVIDER=rules`, and `SUPPORT_LIVE_PROBE_ENABLED=false`; both API keys are blank. The internal network has no external route. The public portfolio uses bundled synthetic data and the forecasting preview computes without persistence. The in-memory SQLite URL satisfies shared application initialization. PostgreSQL is unnecessary.
- The release preflight verifies the rendered Compose config, including the isolation, environment, permissions, published port, image references and mount sources. The host environment file accepts only the hostname, bind address, HTTPS port and two certificate file paths. Never upload development `.env` files.
- NGINX terminates TLS 1.2/1.3, allowlists public routes and strips workspace credentials before proxying. It limits general requests to 10 per second per source IP with burst 30, preview requests to 12 per minute per source IP with burst 6, and preview bodies to 16 KiB. NGINX returns 429 when throttling. Use a DNS-only record to preserve peer IPs. A future CDN or load balancer requires revisiting how client IPs are trusted and how limits are applied.
- Docker caps FastAPI at 0.75 CPU, 512 MiB and 128 PIDs, and NGINX at 0.20 CPU, 128 MiB and 64 PIDs. The combined memory-plus-swap limit matches the memory limit, so neither container gets an additional swap allowance. The API filesystem is read-only with a 16 MiB temporary mount. Docker rotates each service's logs at 10 MB with up to three files. Normal proxy access logs omit IP addresses, paths, query strings, request bodies and credentials. Docker and NGINX diagnostic errors may include client or request metadata. Keep logs limited to operators and review retention before any forwarding.
- The API has a Docker health check and the proxy waits for it at startup. Both containers restart after a process exit. Docker health status alone does not restart a running unhealthy process. The public health probe goes through NGINX to FastAPI. The deployment smoke checks TLS trust, health, synthetic data, route isolation and a known forecast. See [PUBLIC_DEMO_READINESS.md](PUBLIC_DEMO_READINESS.md) for the application boundary and security regression coverage.

## Prepare a versioned release locally

Use a trusted Linux or WSL build environment with Bash, GNU coreutils, Docker Engine and Buildx. Inspect the official base images, choose reviewed digests and set the variables before the build. Run a vulnerability scan on the resulting images and record the reviewer and any release exceptions.

```bash
docker buildx imagetools inspect docker.io/library/node:22-bookworm-slim
docker buildx imagetools inspect docker.io/library/python:3.13-slim
docker buildx imagetools inspect docker.io/library/nginx:stable-alpine

export DEMO_NODE_BASE='docker.io/library/node:22-bookworm-slim@sha256:<reviewed-digest>'
export DEMO_PYTHON_BASE='docker.io/library/python:3.13-slim@sha256:<reviewed-digest>'
export DEMO_NGINX_BASE='docker.io/library/nginx:stable-alpine@sha256:<reviewed-digest>'
RELEASE=v1-demo
mkdir -p demo-releases
bash ops/public-demo/prepare-release.sh "$RELEASE" demo-releases
tar -C demo-releases -czf "agentledger-$RELEASE.tar.gz" "$RELEASE"
sha256sum "agentledger-$RELEASE.tar.gz" ops/public-demo/{deploy.sh,smoke.sh,check-compose.py,certbot-deploy-hook.sh,production.env.example}
```

Use a fresh release ID for each build. Retain the exact archive and checksums in private release storage. The same saved images are used for rollout and rollback. Rebuilding the source later may resolve different transitive Python dependencies, so use the saved artifact when repeating a release.

## Launch procedure after approval

1. Provision the recommended VM, enable unattended OS security updates and attach the cloud firewall. Start with SSH limited to operator IPs and TCP 443 limited to reviewer IPs. Run Docker commands with `sudo` instead of granting operators Docker-group membership by default. Install Docker Engine and the Compose and Buildx plugins from Docker's official Ubuntu repository. Compose v2.24.4 or newer is required for the production override. On the VM, run:

   ```bash
   sudo apt-get update
   sudo apt-get install -y certbot python3-certbot-dns-cloudflare openssl curl python3 util-linux ca-certificates
   sudo install -m 0755 -d /etc/apt/keyrings
   sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
   sudo chmod a+r /etc/apt/keyrings/docker.asc
   sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<'DOCKER_SOURCE'
   Types: deb
   URIs: https://download.docker.com/linux/ubuntu
   Suites: noble
   Components: stable
   Architectures: amd64
   Signed-By: /etc/apt/keyrings/docker.asc
   DOCKER_SOURCE
   sudo apt-get update
   sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
   sudo systemctl enable --now docker
   sudo docker version
   sudo docker compose version
   uname -m
   ```

   [Docker Engine installation on Ubuntu](https://docs.docker.com/engine/install/ubuntu/) · [Compose override syntax](https://docs.docker.com/reference/compose-file/merge/)

2. Set a dedicated demo hostname in an existing Cloudflare-managed zone. Create a DNS-only `A` record to the VM's public IPv4 address, leaving `AAAA` unset until IPv6 is deliberately enabled. Create a DNS edit token scoped to that zone. Keep it on the VM in a root-only directory and out of shell history and release artifacts. Fill in the actual host and operator email below. Use `sudoedit` to add the Certbot setting `dns_cloudflare_api_token = <zone-scoped-token>`.

   ```bash
   FQDN=demo.example.com
   EMAIL=operator@example.com
   getent ahostsv4 "$FQDN"
   sudo install -d -m 0700 /etc/agentledger-demo
   sudo install -m 0600 /dev/null /etc/agentledger-demo/cloudflare.ini
   sudoedit /etc/agentledger-demo/cloudflare.ini
   sudo certbot certonly --non-interactive --agree-tos --email "$EMAIL" \
     --dns-cloudflare --dns-cloudflare-credentials /etc/agentledger-demo/cloudflare.ini \
     --cert-name "$FQDN" -d "$FQDN"
   ```

   [Cloudflare DNS-only records](https://developers.cloudflare.com/dns/proxy-status/) · [Certbot Cloudflare plugin](https://certbot-dns-cloudflare.readthedocs.io/en/stable/index.html)

3. From the build workstation, confirm the SSH host fingerprint and transfer only the release and host helpers. Record the archive and helper SHA-256 sums through a separate trusted channel.

   ```bash
   RELEASE=v1-demo
   REMOTE=operator@demo.example.com
   ssh "$REMOTE" 'umask 077; mkdir -p ~/agentledger-handoff'
   scp "agentledger-$RELEASE.tar.gz" ops/public-demo/{deploy.sh,smoke.sh,check-compose.py,certbot-deploy-hook.sh,production.env.example} \
     "$REMOTE:agentledger-handoff/"
   ```

   On the VM, compare the output with the verified checksums **before** trusting the files or extracting the archive. Extract only into a fresh release directory.

   ```bash
   cd ~/agentledger-handoff
   RELEASE=v1-demo
   sha256sum "agentledger-$RELEASE.tar.gz" deploy.sh smoke.sh check-compose.py certbot-deploy-hook.sh production.env.example
   sudo install -d -m 0750 /opt/agentledger-demo/{bin,releases}
   sudo test ! -e "/opt/agentledger-demo/releases/$RELEASE"
   sudo tar --no-same-owner -xzf "agentledger-$RELEASE.tar.gz" -C /opt/agentledger-demo/releases
   sudo install -m 0644 deploy.sh smoke.sh check-compose.py /opt/agentledger-demo/bin/
   sudo install -m 0600 production.env.example /etc/agentledger-demo/production.env
   sudoedit /etc/agentledger-demo/production.env
   ```

   Complete the five entries below with the actual `FQDN` used for Certbot. Keep the rehearsal binding until the local checks pass.

   ```dotenv
   DEMO_HOST=demo.example.com
   DEMO_BIND_ADDRESS=127.0.0.1
   DEMO_HTTPS_PORT=8443
   DEMO_TLS_CERT=/etc/letsencrypt/live/demo.example.com/fullchain.pem
   DEMO_TLS_KEY=/etc/letsencrypt/live/demo.example.com/privkey.pem
   ```

4. Run the local check and loopback launch, then install and verify the certificate renewal hook. The deployment script checks the actual HTTPS connection using the system trust store and certificate hostname.

   ```bash
   sudo bash /opt/agentledger-demo/bin/deploy.sh check v1-demo
   sudo bash /opt/agentledger-demo/bin/deploy.sh apply v1-demo
   sudo install -m 0755 certbot-deploy-hook.sh /etc/letsencrypt/renewal-hooks/deploy/agentledger-demo
   sudo systemctl enable --now certbot.timer
   sudo certbot renew --dry-run
   sudo bash /opt/agentledger-demo/bin/deploy.sh renew-tls
   ```

5. Keep TCP 443 restricted to reviewers. Edit `production.env` and set `DEMO_BIND_ADDRESS=0.0.0.0` and `DEMO_HTTPS_PORT=443`, then run:

   ```bash
   sudo bash /opt/agentledger-demo/bin/deploy.sh apply v1-demo
   ```

   From an approved external workstation, run the following with the actual hostname and open the same URL in a browser. Confirm all five pages show synthetic/demo content where appropriate, and that the customer-support preview works without a workspace key. From outside the host, verify 443 and the expected private port restrictions. In the reviewer window confirm the 413 and 429 behavior and check that operator logs contain no submitted values.

   ```bash
   FQDN=demo.example.com
   bash ops/public-demo/smoke.sh "https://$FQDN"
   ```

6. Before broadening access, confirm these operational checks with an identified owner:

   | Check | Launch evidence |
   | --- | --- |
   | Trusted HTTPS and DNS | Correct IPv4 answer and trusted certificate chain for the demo name from an external machine. Certbot timer enabled, staging renewal passes and proxy reload is rehearsed. |
   | External health alert | Configure a five-minute HTTPS `/health` uptime check. Permit monitor access during staging using the provider's published probe ranges where practical. Use the monitor's test notification or an isolated failing check to confirm email delivery and escalation. |
   | Certificate expiry | Add an external daily job using the probe below. Route failure and missed-job alerts to the operator. Verify delivery. |
   | Resource and error alerts | Enable host CPU, memory and disk monitoring. As starting thresholds, alert at 80% sustained utilization and review repeated proxy 5xx, 429s and restarts. Verify notification routing and log rotation on the actual VM. |
   | Recovery | Rehearse rolling back from a second uniquely identified test release and rehearse disabling TCP 443. Time the procedure and record the result. |

   ```bash
   set -o pipefail
   FQDN=demo.example.com
   timeout 20 openssl s_client -verify_return_error -verify_hostname "$FQDN" \
     -connect "$FQDN:443" -servername "$FQDN" </dev/null 2>/dev/null |
     openssl x509 -noout -checkend 1209600
   ```

   The certificate job fails if TLS verification fails or fewer than 14 days remain. When the checks are signed off and launch is approved, broaden only TCP 443 to public IPv4. Leave SSH scoped to the operator CIDR. Run the external smoke again from a regular public network and confirm the uptime monitor reports healthy.

## Update, rollback and recover

Install each new reviewed release alongside the current one and run `deploy.sh check <release-id>` followed by `deploy.sh apply <release-id>`. The script verifies the saved image IDs and checks HTTPS before recording the active release. If a different release fails startup or the smoke check, the script attempts to restart the last working release. Keep at least two verified releases on disk and in private off-host storage.

```bash
sudo bash /opt/agentledger-demo/bin/deploy.sh rollback
```

For a first-release incident, close TCP 443 in the cloud firewall immediately. If an existing release fails after changing host config, restore the previous five settings in `production.env` and rerun `apply` with the current ID. To stop the initial stack entirely, use this command against the dedicated project and first release only:

```bash
RELEASE=v1-demo
DIR="/opt/agentledger-demo/releases/$RELEASE"
sudo env "DEMO_API_IMAGE=agentledger-public-api:$RELEASE" "DEMO_PROXY_IMAGE=agentledger-public-proxy:$RELEASE" \
  docker compose --project-name agentledger-public-v1 --env-file /etc/agentledger-demo/production.env \
  -f "$DIR/compose.public-demo.yaml" -f "$DIR/compose.production.yaml" stop
```

For host loss, create an equivalent VM, restore the reviewed archive and helper scripts, reissue the certificate and restore the five settings. Update DNS, repeat external checks and reopen TCP 443. Store DNS/TLS credentials separately in the operator's encrypted secret store or reissue them. No application database backup is needed for the demo. Existing private workspace backup and restore procedures remain independent of this release.

## Verification and remaining blockers

- **Local verification.** All 67 backend tests passed, including public-demo security regression coverage. All 8 frontend tests passed and the TypeScript/Vite production build completed. The backend suite emitted one existing Starlette TestClient deprecation warning.
- **Release packaging.** The build script produced both versioned Linux/amd64 images from digest-pinned bases. The 216,700,416-byte image archive and the five accompanying files passed SHA-256 verification. All four Bash scripts and 11 runbook command blocks passed syntax checks.
- **Loopback Docker verification.** The isolated production overlay started two healthy containers and no database. The rendered config guard accepted the reviewed config and rejected a non-demo mode. A Python HTTPS client verified the local certificate, dashboard shell, health response, the exact US$4,800 synthetic preview, and an unchanged synthetic portfolio after the preview. Seven private read and write attempts returned 404. The rehearsal observed HTTP 413 for an oversized preview and HTTP 429 during a preview burst. It also verified runtime CPU, memory and PID limits, rotated log configuration and the proxy rate-limit log. The Windows curl probe could not initialize its Schannel credentials. The Python client completed the trusted HTTPS checks. The Bash smoke script and the full release, renewal and rollback sequence still need a run on the Ubuntu host.
- **Pending before exposure.** Obtain launch and spend approval, provision the host and review images, confirm domain/DNS ownership, obtain the publicly trusted certificate, verify DNS/firewall/renewal from the target host, exercise the complete launch and rollback procedure, and confirm browser access and alert receipt externally. No external infrastructure was created. The estimate is a hosting budget. Actual traffic costs and production availability require observation after launch.
