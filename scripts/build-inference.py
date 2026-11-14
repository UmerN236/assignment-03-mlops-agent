"""Build a dedicated image only when the recorded Git SHA identifies clean code."""

import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
status = subprocess.run(
    ["git", "status", "--porcelain"],
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
subprocess.run(
    [
        "docker",
        "build",
        "--build-arg",
        f"APP_VERSION={revision}",
        "-f",
        "infra/inference/Dockerfile",
        "-t",
        f"mlops-assignment3-inference:{revision[:12]}",
        ".",
    ],
    cwd=root,
    check=True,
    timeout=900,
)
