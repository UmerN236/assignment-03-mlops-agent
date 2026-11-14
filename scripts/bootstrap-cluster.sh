#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export KUBECONFIG="$PWD/.local/kubeconfig"
KIND="$PWD/.local/bin/kind"
KUBECTL="$PWD/.local/bin/kubectl"
clusters=$("$KIND" get clusters)
if ! printf '%s\n' "$clusters" | grep -qx mlops-assignment3; then
  # kind creates only the named assignment container, never changes other clusters.
  "$KIND" create cluster --name mlops-assignment3 --config infra/kind/cluster.yaml --wait 180s
fi
"$KIND" export kubeconfig --name mlops-assignment3 --kubeconfig "$KUBECONFIG"
chmod 600 "$KUBECONFIG"
"$KUBECTL" --cache-dir .local/cache/kubectl --context kind-mlops-assignment3 get nodes
"$KUBECTL" --cache-dir .local/cache/kubectl --context kind-mlops-assignment3 apply -f infra/kind/namespace.yaml
"$KUBECTL" --cache-dir .local/cache/kubectl --context kind-mlops-assignment3 -n mlops-agent get pods
