"""Regenerate this revision, verify metadata before populating cache and local remote."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import yaml

from mlops_agent.dataset import DATASET, dataset_bytes, prepare_dataset

root = Path(__file__).resolve().parents[1]
metadata = yaml.safe_load((root / f"{DATASET}.dvc").read_text())["outs"]
expected = hashlib.md5(dataset_bytes(), usedforsecurity=False).hexdigest()
if len(metadata) != 1 or metadata[0].get("md5") != expected:
    raise SystemExit("This revision requires a different recipe; use its documented data source")
prepare_dataset(root)
environment = dict(
    os.environ,
    DVC_NO_ANALYTICS="true",
    DVC_SITE_CACHE_DIR=str(root / ".local/cache/dvc"),
    DVC_GLOBAL_CONFIG_DIR=str(root / ".local/config/dvc"),
    DVC_SYSTEM_CONFIG_DIR=str(root / ".local/config/dvc-system"),
)
for arguments in (["commit", f"{DATASET}.dvc"], ["push", f"{DATASET}.dvc"]):
    subprocess.run(
        [str(Path(sys.executable).parent / "dvc"), *arguments],
        cwd=root,
        env=environment,
        check=True,
        timeout=60,
    )
