"""Observe the real built image over HTTP; leave the healthy service for review."""

import argparse
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from mlops_agent.model_bundle import load_bundle, read_manifest
from mlops_agent.training import TrainingConfig, evaluate_classifier, prepare_split

ROOT = Path(__file__).resolve().parents[1]
SERVICE = "mlops-assignment3-inference"


def docker(*args, check=True):
    return subprocess.run(
        ["docker", *args], check=check, capture_output=True, text=True, timeout=30
    )


def inspect_container(name):
    result = docker("inspect", "--format", "{{json .}}", name, check=False)
    if result.returncode:
        return None
    data = json.loads(result.stdout)
    assert data["Name"] == f"/{name}"
    assert data["Config"]["Labels"].get("assignment.project") == "mlops-assignment3"
    return data


def start(image, name, *, missing=False):
    existing = inspect_container(name)
    if existing:
        assert existing["Config"]["Image"] == image and existing["State"]["Running"]
        return existing
    args = [
        "run",
        "-d",
        "--name",
        name,
        "--label",
        "assignment.project=mlops-assignment3",
        "--network",
        "bridge",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        "512m",
        "--cpus",
        "1",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "-p",
        "127.0.0.1::8000",
    ]
    if missing:
        args.extend(["-e", "MODEL_BUNDLE_PATH=/app/missing-model"])
    docker(*args, image)
    return inspect_container(name)


def url(container):
    port = container["NetworkSettings"]["Ports"]["8000/tcp"][0]
    assert port["HostIp"] == "127.0.0.1"
    return f"http://127.0.0.1:{port['HostPort']}"


def await_live(client):
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline:
        try:
            if client.get("/livez").status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.5)
    raise RuntimeError("Inference liveness did not respond before timeout")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    if not args.image.startswith("mlops-assignment3-inference:"):
        raise ValueError("Only assignment inference images may be verified")
    image = json.loads(docker("image", "inspect", "--format", "{{json .}}", args.image).stdout)
    app_version = image["Config"]["Labels"]["org.opencontainers.image.revision"]
    manifest = read_manifest(ROOT / "artifacts/inference")
    selection = manifest.selection
    model = load_bundle(ROOT / "artifacts/inference", manifest)
    content = (ROOT / selection.dataset.path).read_bytes()
    assert hashlib.md5(content, usedforsecurity=False).hexdigest() == selection.dataset.dvc_md5
    data = prepare_split(content, TrainingConfig())
    assert data.evaluation_id == selection.evaluation_id
    metrics, evaluation = evaluate_classifier(model, data)
    features = ("sepal_length", "sepal_width", "petal_length", "petal_width")
    rows = [
        dict(zip(features, row.tolist(), strict=True)) for row in data.features[data.test_indices]
    ]
    container = start(args.image, SERVICE)
    observations = []
    with httpx.Client(base_url=url(container), timeout=10, trust_env=False) as client:
        await_live(client)
        for route in ("/livez", "/readyz", "/version"):
            response = client.get(route)
            assert response.status_code == 200
            observations.append(
                {"route": route, "status": response.status_code, "body": response.json()}
            )
        version = observations[-1]["body"]
        assert version["model"] == selection.model_dump(mode="json")
        assert version["app_version"] == app_version and version["model_ready"]
        response = client.post("/predict", json={"instances": rows})
        assert response.status_code == 200
        predictions = response.json()["predictions"]
        assert [p["class_id"] for p in predictions] == evaluation["predicted"]
        for prediction, expected in zip(predictions, evaluation["probabilities"], strict=True):
            assert all(
                abs(a - b) < 1e-12
                for a, b in zip(prediction["probabilities"], expected, strict=True)
            )
        observations.append({"route": "/predict", "status": 200, "body": response.json()})
        invalid = {
            "empty_batch": {"instances": []},
            "missing_feature": {"instances": [{"sepal_length": 5}]},
            "string_value": {"instances": [{**rows[0], "petal_width": "invalid"}]},
            "boolean_value": {"instances": [{**rows[0], "petal_width": True}]},
            "negative_value": {"instances": [{**rows[0], "petal_width": -1}]},
            "oversized_batch": {"instances": rows * 3},
            "extra_field": {"instances": rows, "model_uri": "untrusted"},
        }
        for name, body in invalid.items():
            response = client.post("/predict", json=body)
            assert response.status_code == 422
            observations.append({"case": name, "status": 422})
        response = client.post(
            "/predict",
            content='{"instances":[{"sepal_length":NaN}]}',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
        observations.append({"case": "nonfinite_json", "status": 422})
    failure_name = f"{SERVICE}-missing-{uuid4().hex[:8]}"
    try:
        failed = start(args.image, failure_name, missing=True)
        with httpx.Client(base_url=url(failed), timeout=10, trust_env=False) as client:
            await_live(client)
            states = {
                "livez": client.get("/livez").status_code,
                "readyz": client.get("/readyz").status_code,
                "predict": client.post("/predict", json={"instances": rows[:1]}).status_code,
                "version": client.get("/version").json(),
            }
            assert states["livez"] == 200 and states["readyz"] == states["predict"] == 503
            assert states["version"]["model_ready"] is False and states["version"]["model"] is None
            observations.append({"case": "missing_model", "observed": states})
    finally:
        if inspect_container(failure_name):
            docker("rm", "-f", failure_name)
    # Read only our dedicated container's logs, retaining only structured allowlisted fields.
    result = docker("logs", SERVICE)
    logs = []
    for line in (result.stdout + result.stderr).splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if set(record) >= {"tool_name", "status", "duration_ms", "request_id"}:
            logs.append(record)
    assert logs
    export = {
        "observed_at": datetime.now(UTC).isoformat(),
        "image_tag": args.image,
        "image_id": image["Id"],
        "platform": f"{image['Os']}/{image['Architecture']}",
        "container": SERVICE,
        "review_url": url(container),
        "user": image["Config"]["User"],
        "model_selection": selection.model_dump(mode="json"),
        "holdout_predictions_matched": len(predictions),
        "artifact_reload_metrics": metrics,
        "observations": observations,
        "structured_log_sample": logs[-5:],
        "limitations": [
            "Local Docker verification; Kubernetes deployment is a later milestone.",
            "Candidate selection is explicit; no production promotion or drift claim.",
        ],
    }
    output = ROOT / "docs/evidence/inference-live.json"
    output.write_text(json.dumps(export, indent=2) + "\n")
    print(
        json.dumps(
            {"status": "passed", "review_url": url(container), "predictions": len(predictions)}
        )
    )


if __name__ == "__main__":
    main()
