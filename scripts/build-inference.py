"""Build a dedicated image only when the recorded Git SHA identifies clean code."""

import argparse
import json
import os
import subprocess
from pathlib import Path

from mlops_agent.model_bundle import read_manifest

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--timeout-seconds", type=int, default=2400)
args = parser.parse_args()
if not 600 <= args.timeout_seconds <= 3600:
    parser.error("Build timeout must be between 600 and 3600 seconds")
# Keep Buildx activity/state inside the writable workspace; retain the existing
# Docker connection and credential helper without reading credential contents.
os.environ["BUILDX_CONFIG"] = str(root / ".local/docker-buildx")
status = subprocess.run(
    ["git", "status", "--porcelain", "--", "src", "infra/inference", ".dockerignore"],
    cwd=root,
    capture_output=True,
    text=True,
    check=True,
    timeout=10,
)
if status.stdout.strip():
    raise SystemExit("Commit code and metadata before building a versioned image")
revision = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=root,
    capture_output=True,
    text=True,
    check=True,
    timeout=10,
).stdout.strip()
selection = read_manifest(root / "artifacts/inference").selection
# Source and model are separate versioned inputs. One source revision can serve
# different explicitly selected artifacts without overwriting the same image tag.
image = f"mlops-assignment3-inference:{revision[:12]}-{selection.model_sha256[:12]}"
subprocess.run(
    [
        "docker",
        "build",
        "--build-arg",
        f"APP_VERSION={revision}",
        "-f",
        "infra/inference/Dockerfile",
        "-t",
        image,
        ".",
    ],
    cwd=root,
    check=True,
    # Cold scientific wheels can be slow on the observed network. Still impose
    # a hard deadline; subsequent builds reuse Docker's completed dependency layer.
    timeout=args.timeout_seconds,
)
image_id = subprocess.run(
    ["docker", "image", "inspect", "--format", "{{.Id}}", image],
    capture_output=True,
    text=True,
    check=True,
    timeout=20,
).stdout.strip()
(root / ".local").mkdir(exist_ok=True)
(root / ".local/inference-image.json").write_text(
    json.dumps(
        {
            "image_tag": image,
            "image_id": image_id,
            "code_revision": revision,
            "model_run_id": selection.run_id,
        },
        indent=2,
    )
    + "\n"
)
print(json.dumps({"image_tag": image, "image_id": image_id}))
