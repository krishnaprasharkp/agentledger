#!/usr/bin/env bash
# Build a transferable release. This script starts no containers or public services.
set -euo pipefail
umask 077
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
id=${1:-}
out=${2:-}
[[ $id =~ ^[a-z0-9][a-z0-9._-]{0,47}$ && -n $out && -d $out ]] || {
    echo "Usage: bash prepare-release.sh RELEASE_ID EXISTING_OUTPUT_DIRECTORY" >&2
    exit 1
}
for spec in "${DEMO_NODE_BASE:-}" "${DEMO_PYTHON_BASE:-}" "${DEMO_NGINX_BASE:-}"; do
    [[ $spec =~ ^docker\.io/library/(node|python|nginx):[a-zA-Z0-9._-]+@sha256:[a-f0-9]{64}$ ]] || {
        echo "Set reviewed digest-pinned Node, Python and NGINX base image references." >&2
        exit 1
    }
done
[[ $DEMO_NODE_BASE == docker.io/library/node:* && $DEMO_PYTHON_BASE == docker.io/library/python:* &&
   $DEMO_NGINX_BASE == docker.io/library/nginx:* ]] || exit 1

release=$(cd -- "$out" && pwd)/$id
mkdir -- "$release"
api_image="agentledger-public-api:$id"
proxy_image="agentledger-public-proxy:$id"
docker buildx build --platform linux/amd64 --load --tag "$api_image" \
    --build-arg "NODE_BASE=$DEMO_NODE_BASE" --build-arg "PYTHON_BASE=$DEMO_PYTHON_BASE" \
    --file "$root/backend/Dockerfile" "$root"
docker pull --platform linux/amd64 "$DEMO_NGINX_BASE"
docker tag "$(docker image inspect --format '{{.Id}}' "$DEMO_NGINX_BASE")" "$proxy_image"
for file in compose.public-demo.yaml nginx.public-demo.conf; do
    cp -- "$root/backend/$file" "$release/$file"
done
cp -- "$root/ops/public-demo/compose.production.yaml" "$release/"
docker save --output "$release/images.tar" "$api_image" "$proxy_image"
printf '%s\t%s\n' "$api_image" "$(docker image inspect --format '{{.Id}}' "$api_image")" \
                 "$proxy_image" "$(docker image inspect --format '{{.Id}}' "$proxy_image")" > "$release/images.tsv"
printf '%s\n' "$DEMO_NODE_BASE" "$DEMO_PYTHON_BASE" "$DEMO_NGINX_BASE" > "$release/base-images.txt"
(
    cd -- "$release"
    sha256sum images.tar images.tsv base-images.txt compose.public-demo.yaml compose.production.yaml nginx.public-demo.conf > SHA256SUMS
)
printf 'Prepared private release directory: %s\n' "$release"
