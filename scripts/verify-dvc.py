"""Live historical restore and independent data bootstrap, only in isolated clones.

Reuses the current frozen Python runtime; copies no .env, runtime state or cache.
Leaves clones under .local for review and exports compact, sanitized observations.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from mlops_agent.dataset import DATASET
from mlops_agent.dvc_tools import DvcTools

root = Path(__file__).resolve().parents[1]
git = shutil.which("git") or "git"
dvc = str(Path(sys.executable).parent / "dvc")
environment = {"PATH": os.defpath, "DVC_NO_ANALYTICS": "true", "UV_NATIVE_TLS": "true"}


def command(cwd: Path, argv: list[str]) -> str:
    if not cwd.resolve().is_relative_to(root):
        raise ValueError("Verification writes must remain inside the assignment workspace")
    env = dict(
        environment,
        DVC_SITE_CACHE_DIR=str(cwd / ".local/cache/dvc"),
        DVC_GLOBAL_CONFIG_DIR=str(cwd / ".local/config/dvc"),
        DVC_SYSTEM_CONFIG_DIR=str(cwd / ".local/config/dvc-system"),
        PYTHONPATH=str(cwd / "src"),
    )
    result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError(f"Verification command failed: {Path(argv[0]).name} {argv[1]}")
    return result.stdout.strip()


revision = command(root, [git, "log", "-1", "--format=%H", "--", f"{DATASET}.dvc"])
if not re.fullmatch(r"[a-f0-9]{40}", revision):
    raise SystemExit("No committed dataset revision")
base = root / ".local" / f"dvc-verification-{uuid4().hex[:8]}"
base.mkdir(parents=True)
observations = []


def observe(adapter: DvcTools, name: str, args: dict) -> dict:
    result = adapter.registry.call(name, args)
    if result.status != "ok":
        raise RuntimeError(f"Live tool did not succeed: {name}: {result.error}")
    observations.append(result.model_dump(mode="json"))
    return result.evidence


tools = DvcTools(root)
version = observe(tools, "dvc_get_dataset_version", {"revision": revision})
assert version["workspace_matches_revision"]
observe(tools, "dvc_list_datasets", {"revision": revision})
assert observe(tools, "dvc_get_data_status", {})["clean"]
observe(tools, "dvc_explain_reproduction", {"revision": revision})
parent = command(root, [git, "rev-parse", f"{revision}^"])
added = observe(
    tools,
    "dvc_compare_versions",
    {
        "old_revision": parent,
        "new_revision": revision,
    },
)
assert added["changes"].get("added") or added["changes"].get("modified")


def clone(name: str) -> Path:
    target = base / name
    command(root, [git, "clone", "--no-hardlinks", "--local", str(root), str(target)])
    command(target, [git, "checkout", "--detach", revision])
    assert not (target / DATASET).exists()
    assert not (target / ".dvc/cache").exists()
    assert not (target / ".local/dvc-remote").exists()
    return target


restoration = clone("historical-restore")
command(
    restoration,
    [dvc, "remote", "modify", "--local", "local", "url", str(root / ".local/dvc-remote")],
)
pull_output = command(restoration, [dvc, "pull", f"{DATASET}.dvc"])
isolated = DvcTools(restoration)
assert observe(isolated, "dvc_get_dataset_version", {"revision": revision})[
    "workspace_matches_revision"
]
target = restoration / DATASET
# Remove the DVC-linked file before introducing isolated bad bytes; preserve cache.
target.unlink()
target.write_bytes(b"isolated changed dataset\n")
assert not observe(isolated, "dvc_get_data_status", {})["clean"]
changed = observe(isolated, "dvc_compare_versions", {"old_revision": revision})
assert changed["changes"].get("modified")
target.unlink()
checkout_output = command(restoration, [dvc, "checkout", f"{DATASET}.dvc"])
restored = observe(isolated, "dvc_get_dataset_version", {"revision": revision})
assert restored["workspace_matches_revision"]
assert observe(isolated, "dvc_get_data_status", {})["clean"]

bootstrap = clone("independent-bootstrap")
bootstrap_output = command(bootstrap, [sys.executable, "scripts/bootstrap-data.py"])
assert (
    hashlib.md5((bootstrap / DATASET).read_bytes(), usedforsecurity=False).hexdigest()
    == (version["dataset_dvc_md5"])
)
assert observe(DvcTools(bootstrap), "dvc_get_data_status", {})["clean"]
assert (
    bootstrap
    / ".local/dvc-remote/files/md5"
    / version["dataset_dvc_md5"][:2]
    / version["dataset_dvc_md5"][2:]
).is_file()
export = {
    "observed_at": datetime.now(UTC).isoformat(),
    "dataset_revision": revision,
    "dvc_version": command(root, [dvc, "--version"]),
    "content_md5": version["dataset_dvc_md5"],
    "size_bytes": version["size_bytes"],
    "isolated_clones": str(base.relative_to(root)),
    "historical_pull_stdout": pull_output,
    "historical_checkout_stdout": checkout_output,
    "independent_bootstrap_stdout": bootstrap_output,
    "runtime": "Reused frozen Python runtime; both clones started with no data, cache or remote",
    "mlflow_lineage_live": "Pending real training runs and MLflow adapter wiring",
    "observations": observations,
}
parser = argparse.ArgumentParser()
parser.add_argument("--output", default="docs/evidence/dvc-bootstrap.json")
output = root / parser.parse_args().output
if output.parent.resolve() != (root / "docs/evidence").resolve() or output.suffix != ".json":
    raise SystemExit("Evidence output must be a JSON file inside docs/evidence")
output.write_text(json.dumps(export, indent=2) + "\n")
print(
    json.dumps(
        {
            "evidence": str(output.relative_to(root)),
            "checks": "passed",
            "dataset_revision": revision,
            "content_md5": version["dataset_dvc_md5"],
        }
    )
)
