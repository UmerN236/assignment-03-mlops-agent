"""Engineer-only build/start of the named assignment Airflow, preserving storage."""

import json
import os
import subprocess
from pathlib import Path

from mlops_agent.dataset import DATASET
from mlops_agent.training import training_lineage

ROOT = Path(__file__).resolve().parents[1]


def command(argv, timeout=30):
    return subprocess.run(
        argv, cwd=ROOT, check=True, capture_output=True, text=True, timeout=timeout
    )


def main():
    lineage = training_lineage(ROOT)  # Requires clean committed source and DVC hash match.
    revision = lineage["code_git_revision"]
    # Inspect ownership before any container operation. Never touch other projects.
    owned = json.loads(
        command(
            [
                "docker",
                "inspect",
                "mlops-assignment3-airflow",
                "--format",
                "{{json .Config.Labels}}",
            ]
        ).stdout
    )
    if owned.get("com.docker.compose.project") != "mlops-assignment3":
        raise SystemExit("Unexpected Airflow container ownership")
    target = ROOT / "artifacts/airflow-input"
    target.mkdir(parents=True, exist_ok=True)
    (target / "iris.csv").write_bytes((ROOT / DATASET).read_bytes())
    (target / "lineage.json").write_text(json.dumps(lineage, sort_keys=True))
    # Container UID can read input, never any credential or the host source tree.
    target.chmod(0o755)
    for path in target.iterdir():
        path.chmod(0o644)
    os.environ["BUILDX_CONFIG"] = str(ROOT / ".local/docker-buildx")
    image = f"mlops-assignment3-airflow:{revision[:12]}"
    subprocess.run(
        [
            "docker",
            "build",
            "--build-arg",
            f"APP_VERSION={revision}",
            "-f",
            "infra/airflow/Dockerfile",
            "-t",
            image,
            ".",
        ],
        cwd=ROOT,
        check=True,
        timeout=2400,
    )
    os.environ["LOCAL_UID"] = str(os.getuid())
    os.environ["AIRFLOW_IMAGE"] = image
    command(
        [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-p",
            "mlops-assignment3",
            "-f",
            "infra/compose.yaml",
            "up",
            "-d",
            "--no-deps",
            "airflow",
        ],
        timeout=120,
    )
    (ROOT / ".local/airflow-image.mk").write_text(f"AIRFLOW_IMAGE := {image}\n")
    print(
        json.dumps(
            {
                "image": image,
                "code_revision": revision,
                "dataset_dvc_md5": lineage["dataset_dvc_md5"],
                "note": "Service starting; run verify-airflow-dag after health is ready",
            }
        )
    )


if __name__ == "__main__":
    main()
