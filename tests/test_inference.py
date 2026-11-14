"""Real local sklearn serialization; no tracking server or credentials in CI."""

import json
import logging

import cloudpickle
import mlflow.sklearn
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sklearn.ensemble import RandomForestClassifier

from mlops_agent.inference import create_app
from mlops_agent.model_bundle import BundleManifest, ModelSelection, file_sha256, load_bundle

ROW = {"sepal_length": 5.0, "sepal_width": 3.5, "petal_length": 1.4, "petal_width": 0.2}


@pytest.mark.parametrize("nested", [False, True])
def test_validation_never_echoes_arbitrary_input_keys(tmp_path, caplog, nested):
    secret = "private-credential-as-extra-key"
    body = (
        {"instances": [{**ROW, secret: "ignored"}]}
        if nested
        else {"instances": [ROW], secret: "ignored"}
    )
    with TestClient(create_app(tmp_path)) as client:
        response = client.post("/predict", json=body)
    assert response.status_code == 422
    assert secret not in response.text + caplog.text


@pytest.fixture
def bundle(tmp_path):
    model = RandomForestClassifier(n_estimators=3, max_depth=2, random_state=42)
    model.fit([[5, 3.5, 1.4, 0.2], [6, 3, 4, 1.5], [7, 3, 6, 2]], [0, 1, 2])
    path = tmp_path / "model"
    mlflow.sklearn.save_model(model, str(path), pip_requirements=["scikit-learn==1.7.2"])
    # save_model has no tracking run. Bind the fixture to explicit test lineage.
    import yaml

    metadata = yaml.safe_load((path / "MLmodel").read_text())
    metadata.update(run_id="1" * 32, model_id="m-" + "2" * 32)
    (path / "MLmodel").write_text(yaml.safe_dump(metadata))
    manifest = BundleManifest(
        selection=ModelSelection(
            run_id="1" * 32,
            model_id="m-" + "2" * 32,
            model_sha256=file_sha256(path / "model.pkl"),
            training_code_revision="3" * 40,
            dataset={"path": "data/iris.csv", "git_revision": "4" * 40, "dvc_md5": "5" * 32},
            evaluation_id="6" * 64,
        ),
        files={name: file_sha256(path / name) for name in ("MLmodel", "model.pkl")},
    )
    (path / "manifest.json").write_text(manifest.model_dump_json())
    return path, manifest, model


def test_real_prediction_and_provenance(bundle, caplog):
    path, manifest, original = bundle
    caplog.set_level(logging.INFO, logger="mlops_agent.inference")
    with TestClient(create_app(path, "a" * 40)) as client:
        assert client.get("/livez").status_code == 200
        assert client.get("/readyz").json()["model_run_id"] == manifest.selection.run_id
        response = client.post("/predict", json={"instances": [ROW, ROW]})
        assert response.status_code == 200
        assert response.json()["predictions"][0]["class_id"] == int(
            original.predict(np.array([list(ROW.values())]))[0]
        )
        assert response.json()["predictions"][0]["probabilities"] == pytest.approx(
            original.predict_proba(np.array([list(ROW.values())]))[0]
        )
        assert response.json()["app_version"] == "a" * 40
        assert response.headers["X-Request-ID"]
        version = client.get("/version").json()
        assert version["model"] == manifest.selection.model_dump(mode="json")
        assert version["model_ready"] is True
        assert client.post("/agent", json={}).status_code == 404
    record = next(json.loads(r.message) for r in caplog.records if '"tool_name"' in r.message)
    assert record.keys() >= {"tool_name", "request_id", "status", "duration_ms"}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"instances": []},
        {"instances": [ROW] * 101},
        {"instances": [{**ROW, "petal_width": -1}]},
        {"instances": [{**ROW, "petal_width": 20}]},
        {"instances": [{**ROW, "petal_width": True}]},
        {"instances": [{**ROW, "petal_width": "secret-input"}]},
        {"instances": [{**ROW, "petal_width": None}]},
        {"instances": [{"sepal_length": 5.0}]},
        {"instances": [{**ROW, "model_uri": "secret-input"}]},
        {"instances": [[5.0, 3.5, 1.4, 0.2]]},
        {"instances": [ROW], "model_uri": "secret-input"},
    ],
)
def test_invalid_inputs_rejected_without_echoing_values(tmp_path, body):
    with TestClient(create_app(tmp_path)) as client:
        response = client.post("/predict", json=body)
        assert response.status_code == 422
        assert "secret-input" not in response.text


@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "-Infinity", "null", "garbage"])
def test_nonfinite_and_malformed_json_safe_errors(tmp_path, invalid):
    body = json.dumps({"instances": [ROW]}).replace(
        '"petal_width": 0.2', f'"petal_width": {invalid}'
    )
    with TestClient(create_app(tmp_path)) as client:
        assert (
            client.post(
                "/predict", content=body, headers={"Content-Type": "application/json"}
            ).status_code
            == 422
        )


def test_missing_model_liveness_is_independent(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/livez").status_code == 200
        assert client.get("/readyz").status_code == 503
        assert client.post("/predict", json={"instances": [ROW]}).status_code == 503
        assert client.get("/version").json()["model"] is None
        assert str(tmp_path) not in client.get("/readyz").text


def test_empty_bundle_environment_uses_local_default(bundle, tmp_path, monkeypatch):
    path, _, _ = bundle
    destination = tmp_path / "artifacts/inference"
    destination.parent.mkdir()
    path.rename(destination)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MODEL_BUNDLE_PATH", "")
    with TestClient(create_app()) as client:
        assert client.get("/readyz").status_code == 200


def test_corruption_rejected_before_deserialization(bundle, monkeypatch):
    path, manifest, _ = bundle
    (path / "model.pkl").write_bytes(b"corrupt")
    monkeypatch.setattr(cloudpickle, "load", lambda *_: pytest.fail("Must not deserialize"))
    with pytest.raises(ValueError, match="integrity"):
        load_bundle(path, manifest)
    with TestClient(create_app(path)) as client:
        assert client.get("/readyz").status_code == 503
        assert client.get("/version").json()["model_ready"] is False


def test_symlink_model_is_not_loaded(bundle):
    path, manifest, _ = bundle
    (path / "model.pkl").rename(path / "external.pkl")
    (path / "model.pkl").symlink_to(path / "external.pkl")
    with pytest.raises(ValueError, match="integrity"):
        load_bundle(path, manifest)


def test_mismatched_lineage_is_not_loaded(bundle):
    path, manifest, _ = bundle
    manifest.selection.run_id = "0" * 32
    with pytest.raises(ValueError, match="provenance"):
        load_bundle(path, manifest)


def test_invalid_model_output_removes_readiness(bundle, monkeypatch):
    path, _, _ = bundle
    with TestClient(create_app(path)) as client:
        monkeypatch.setattr(
            client.app.state.model, "predict_proba", lambda x: np.full((len(x), 3), float("nan"))
        )
        assert client.post("/predict", json={"instances": [ROW]}).status_code == 503
        assert client.get("/readyz").status_code == 503
        assert client.get("/livez").status_code == 200


def test_bundle_cannot_expand_file_allowlist(bundle):
    _, manifest, _ = bundle
    data = manifest.model_dump()
    data["files"]["../outside"] = "a" * 64
    with pytest.raises(ValueError):
        BundleManifest.model_validate(data)
