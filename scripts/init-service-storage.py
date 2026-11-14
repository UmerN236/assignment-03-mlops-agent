"""Container-only initialization of dedicated service volumes, preserving state."""

import os
import shutil
from pathlib import Path

uid = int(os.environ["LOCAL_UID"])
for target, previous in (
    (Path("/opt/airflow"), Path("/previous-airflow")),
    (Path("/mlflow"), Path("/previous-mlflow")),
):
    marker = target / ".storage-initialized"
    if not marker.exists():
        # Preserve bootstrap state when migrating away from macOS bind storage.
        for source in previous.iterdir():
            destination = target / source.name
            if destination.exists():
                continue
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
        marker.touch(mode=0o600)
    for path in [target, *target.rglob("*")]:
        os.chown(path, uid, 0)
    target.chmod(0o770)
print("Dedicated service volumes initialized; existing state preserved.")
