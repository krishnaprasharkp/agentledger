#!/usr/bin/env bash
# Run only on the dedicated demo host. "check" neither loads images nor starts containers.
set -euo pipefail
umask 077
scripts=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
state=${AGENTLEDGER_DEMO_ROOT:-/opt/agentledger-demo}
config=${AGENTLEDGER_DEMO_ENV:-/etc/agentledger-demo/production.env}
project=agentledger-public-v1
action=${1:-}
id=${2:-}
case "$action" in
    check|apply) [[ -n $id ]] || exit 2 ;;
    rollback|renew-tls) [[ -z $id ]] || exit 2 ;;
    *) echo "Usage: bash deploy.sh check|apply RELEASE_ID, or rollback|renew-tls" >&2; exit 2 ;;
esac
[[ -r $config && -d $state/releases ]] || { echo 'Missing host configuration or release directory.' >&2; exit 1; }

# Accept only the five documented settings. Treat all values as data, never shell code.
unset DEMO_HOST DEMO_BIND_ADDRESS DEMO_HTTPS_PORT DEMO_TLS_CERT DEMO_TLS_KEY
while IFS= read -r line || [[ -n $line ]]; do
    line=${line%$'\r'}
    case "$line" in ''|'#'*) continue ;; esac
    key=${line%%=*}
    value=${line#*=}
    case "$key" in
        DEMO_HOST|DEMO_BIND_ADDRESS|DEMO_HTTPS_PORT|DEMO_TLS_CERT|DEMO_TLS_KEY) ;;
        *) echo 'Unexpected environment setting.' >&2; exit 1 ;;
    esac
    [[ $line == *=* && -n $value && ! -v $key ]] || { echo 'Invalid or duplicate setting.' >&2; exit 1; }
    printf -v "$key" '%s' "$value"
    export "$key"
done < "$config"
[[ ${DEMO_HOST:-} =~ ^[a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)+$ &&
    ${DEMO_TLS_CERT:-} =~ ^/[a-zA-Z0-9/._-]+$ && ${DEMO_TLS_KEY:-} =~ ^/[a-zA-Z0-9/._-]+$ ]] || exit 1
case "${DEMO_BIND_ADDRESS:-}:${DEMO_HTTPS_PORT:-}" in
    0.0.0.0:443|127.0.0.1:8443) ;;
    *) echo 'Use the approved public binding or loopback rehearsal binding.' >&2; exit 1 ;;
esac
openssl x509 -in "$DEMO_TLS_CERT" -noout -checkhost "$DEMO_HOST" |
    grep -Fx "Hostname $DEMO_HOST does match certificate" >/dev/null
openssl x509 -in "$DEMO_TLS_CERT" -noout -checkend 86400 >/dev/null
cert_pub=$(openssl x509 -in "$DEMO_TLS_CERT" -pubkey -noout)
key_pub=$(openssl pkey -in "$DEMO_TLS_KEY" -passin pass: -pubout)
[[ -n $cert_pub && $cert_pub == "$key_pub" ]] || { echo 'TLS key and certificate do not match.' >&2; exit 1; }

current=''
previous=''
if [[ $action != check ]]; then
    exec 9>"$state/deploy.lock"
    flock -n 9 || { echo 'Another deployment operation is running.' >&2; exit 1; }
    if [[ -f $state/current ]]; then read -r current < "$state/current"; fi
    if [[ -f $state/previous ]]; then read -r previous < "$state/previous"; fi
fi
case "$action" in rollback) id=$previous ;; renew-tls) id=$current ;; esac
origin="https://$DEMO_HOST:$DEMO_HTTPS_PORT"
resolve="$DEMO_HOST:$DEMO_HTTPS_PORT:127.0.0.1"

configure() {
    local target="$1"
    [[ $target =~ ^[a-z0-9][a-z0-9._-]{0,47}$ ]] || { echo 'No valid release ID.' >&2; return 1; }
    release="$state/releases/$target"
    [[ -d $release && ! -L $release ]] || return 1
    (cd -- "$release" && sha256sum --check --status --strict SHA256SUMS) || {
        echo 'Release integrity check failed.' >&2; return 1;
    }
    DEMO_API_IMAGE="agentledger-public-api:$target"
    DEMO_PROXY_IMAGE="agentledger-public-proxy:$target"
    DEMO_NGINX_CONFIG="$release/nginx.public-demo.conf"
    export DEMO_API_IMAGE DEMO_PROXY_IMAGE DEMO_NGINX_CONFIG
    compose=(docker compose --project-name "$project" --env-file "$config"
        -f "$release/compose.public-demo.yaml" -f "$release/compose.production.yaml")
    "${compose[@]}" config --format json | python3 "$scripts/check-compose.py"
}

load_images() {
    docker load -i "$release/images.tar" >/dev/null || return 1
    local image expected api_seen=0 proxy_seen=0
    while IFS=$'\t' read -r image expected; do
        case "$image" in
            "$DEMO_API_IMAGE") ((++api_seen)) ;;
            "$DEMO_PROXY_IMAGE") ((++proxy_seen)) ;;
            *) return 1 ;;
        esac
        [[ $expected =~ ^sha256:[a-f0-9]{64}$ &&
            $(docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}}' "$image") == "$expected linux/amd64" ]] || return 1
    done < "$release/images.tsv"
    [[ $api_seen == 1 && $proxy_seen == 1 ]]
}

verify_origin() {
    # Docker can mark the proxy running before NGINX has opened its TLS listener.
    curl --fail --silent --show-error --noproxy '*' --resolve "$resolve" \
        --retry 5 --retry-delay 1 --retry-connrefused --retry-max-time 12 --max-time 4 \
        --output /dev/null "$origin/health" &&
        bash "$scripts/smoke.sh" "$origin" "$resolve"
}

launch() {
    configure "$1" && load_images &&
        "${compose[@]}" up -d --no-build --pull never --wait --wait-timeout 90 &&
        verify_origin
}

configure "$id"
if [[ $action == check ]]; then
    echo 'Release checksums, TLS files and Compose safety checks passed. No containers changed.'
    exit 0
fi
if [[ $action == renew-tls ]]; then
    # The proxy bind-mounts individual Certbot files. Recreate it to rebind the renewed files.
    load_images
    "${compose[@]}" up -d --no-deps --no-build --pull never --force-recreate proxy
    verify_origin
    exit 0
fi
if [[ -z $current ]]; then
    existing=$(docker ps -aq --filter "label=com.docker.compose.project=$project")
    [[ -z $existing ]] || { echo 'The deployment project is already in use without a release marker.' >&2; exit 1; }
fi
if ! launch "$id"; then
    echo 'Release failed to start or pass the HTTPS smoke check.' >&2
    if [[ -n $current && $id != "$current" ]]; then
        launch "$current" || echo 'Automatic recovery failed. Close the public firewall rule and investigate.' >&2
    elif [[ -z $current ]]; then
        "${compose[@]}" down
    fi
    exit 1
fi
if [[ -n $current && $current != "$id" ]]; then
    printf '%s\n' "$current" > "$state/previous.next"
    mv -f -- "$state/previous.next" "$state/previous"
fi
printf '%s\n' "$id" > "$state/current.next"
mv -f -- "$state/current.next" "$state/current"
echo "Active demo release: $id"
