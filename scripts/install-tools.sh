#!/bin/sh
# Pinned Apple Silicon tools, verified before installation. No global writes.
set -eu
cd "$(dirname "$0")/.."
[ "$(uname -sm)" = 'Darwin arm64' ] || { echo 'This bootstrap supports Darwin arm64 only.' >&2; exit 1; }
mkdir -p .local/bin .local/downloads
fetch() {
  name=$1 url=$2 expected=$3
  curl --fail --silent --show-error --location --retry 2 --max-time 180 "$url" -o ".local/downloads/$name"
  actual=$(shasum -a 256 ".local/downloads/$name" | cut -d ' ' -f 1)
  [ "$actual" = "$expected" ] || { echo "Checksum mismatch: $name" >&2; exit 1; }
}
fetch uv.tar.gz https://github.com/astral-sh/uv/releases/download/0.9.9/uv-aarch64-apple-darwin.tar.gz 737e1c2c4f97577aa7764141846e27de915eebb3b2a0f467451089a64824d2f7
tar -xzf .local/downloads/uv.tar.gz -C .local/downloads
cp .local/downloads/uv-aarch64-apple-darwin/uv .local/bin/uv
fetch kind https://github.com/kubernetes-sigs/kind/releases/download/v0.30.0/kind-darwin-arm64 ceaf40df1d1551c481fb50e3deb5c3deecad5fd599df5469626b70ddf52a1518
cp .local/downloads/kind .local/bin/kind
fetch kubectl https://dl.k8s.io/release/v1.34.0/bin/darwin/arm64/kubectl d491f4c47c34856188d38e87a27866bd94a66a57b8db3093a82ae43baf3bb20d
cp .local/downloads/kubectl .local/bin/kubectl
chmod 755 .local/bin/uv .local/bin/kind .local/bin/kubectl
.local/bin/uv --version
.local/bin/kind version
.local/bin/kubectl version --client
