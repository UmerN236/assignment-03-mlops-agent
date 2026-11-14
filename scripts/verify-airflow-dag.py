"""Authorized engineer smoke/failure/recovery runs, through Airflow 3 public API.

Not an agent tool. Creates four bounded runs of only assignment_training. Export
allowlisted facts/structured logs, never HTTP auth, arbitrary logs or credentials.
"""

import hashlib
import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import mlflow
from mlflow import MlflowClient

from mlops_agent.config import load_settings
from mlops_agent.kubernetes_tools import KubernetesTools
from mlops_agent.pipeline import DAG_ID, STAGES

ROOT = Path(__file__).resolve().parents[1]


def container_read(key):
    # No exec of caller-controlled commands/paths; only this workflow's JSON files.
    script = (
        "import json,pathlib; p=pathlib.Path('/opt/airflow/training')/" + repr(key) + "; "
        "print(json.dumps({n:json.loads((p/n).read_text()) if (p/n).exists() else None "
        "for n in ['evaluation.json','gate.json','approved.json']}))"
    )
    result = subprocess.run(
        ["docker", "exec", "mlops-assignment3-airflow", "python", "-c", script],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    return json.loads(result.stdout)


def safe_log_entries(content):
    selected = []
    for entry in content:
        event = entry.get("event", "") if isinstance(entry, dict) else entry
        if not isinstance(event, str):
            continue
        try:
            value = json.loads(event)
        except (json.JSONDecodeError, TypeError):
            continue
        if (
            isinstance(value, dict)
            and value.get("tool") in {"airflow_" + s for s in STAGES}
            and value.get("status") in {"ok", "error"}
            and isinstance(value.get("duration_ms"), (int, float))
            and re.fullmatch(r"engineering__[A-Za-z0-9_]+", str(value.get("request_id", "")))
        ):
            selected.append({k: value[k] for k in ("tool", "status", "duration_ms", "request_id")})
    return selected


def main():
    settings = load_settings()
    if settings.airflow_base_url != "http://127.0.0.1:8080":
        raise ValueError("Engineering verifier only targets dedicated local Airflow")
    labels = subprocess.run(
        ["docker", "inspect", "mlops-assignment3-airflow", "--format", "{{json .Config.Labels}}"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert json.loads(labels.stdout)["com.docker.compose.project"] == "mlops-assignment3"
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"] = "15"
    os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"] = "0"
    registry = MlflowClient()
    versions_before = [
        v.version for v in registry.search_model_versions("name = 'assignment-iris'")
    ]
    # Read current deployed identity independently; never infer it from old evidence.
    kube = KubernetesTools(settings.kubernetes_readonly_kubeconfig)
    baseline = kube.registry.call("kubernetes_health", {})
    baseline_data = baseline.model_dump(mode="json")
    assert baseline_data["status"] == "ok", "Live cluster identity unavailable"
    evidence = {
        "observed_at": datetime.now(UTC).isoformat(),
        "dag_id": DAG_ID,
        "registry_versions_before": versions_before,
        "runs": [],
        "cluster_before": baseline_data,
    }
    client = httpx.Client(base_url=settings.airflow_base_url, timeout=20, trust_env=False)
    unauthenticated = client.get("/api/v2/dags")
    assert unauthenticated.status_code in {401, 403}
    if settings.airflow_token:
        token = settings.airflow_token.get_secret_value()
    else:
        password = (
            settings.airflow_password.get_secret_value()
            if settings.airflow_password
            else json.loads(
                (
                    ROOT / ".local/runtime/airflow/simple_auth_manager_passwords.json.generated"
                ).read_text()
            )[settings.airflow_username]
        )
        response = client.post(
            "/auth/token", json={"username": settings.airflow_username, "password": password}
        )
        response.raise_for_status()
        token = response.json()["access_token"]
    client.headers["Authorization"] = "Bearer " + token
    client.headers["Accept"] = "application/json"

    def api(method, path, **kwargs):
        response = client.request(method, "/api/v2" + path, **kwargs)
        response.raise_for_status()
        return response.json()

    # Verify actual DAG graph under the installed Airflow SDK, not source-text mocks.
    graph_script = (
        "import json,runpy; d=runpy.run_path('/opt/project/dags/training_pipeline.py')"
        "['training_pipeline'](); print(json.dumps({t.task_id:{'downstream':sorted("
        "t.downstream_task_ids),'retries':t.retries,'trigger_rule':str(t.trigger_rule),"
        "'execution_timeout_seconds':t.execution_timeout.total_seconds()} for t in d.tasks}))"
    )
    graph_result = subprocess.run(
        ["docker", "exec", "mlops-assignment3-airflow", "python", "-c", graph_script],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    graph = json.loads(graph_result.stdout.splitlines()[-1])
    assert set(graph) == set(STAGES)
    for index, stage in enumerate(STAGES):
        assert graph[stage]["retries"] == 1
        assert graph[stage]["trigger_rule"] == "all_success"
        assert graph[stage]["downstream"] == list(STAGES[index + 1 : index + 2])
    evidence["graph"] = graph
    evidence["unauthenticated_http"] = unauthenticated.status_code
    api("PATCH", f"/dags/{DAG_ID}", json={"is_paused": False})
    observed_dag = api("GET", f"/dags/{DAG_ID}/details")
    evidence["dag"] = {
        k: observed_dag.get(k)
        for k in ("dag_id", "is_paused", "max_active_runs", "fileloc", "schedule_interval")
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    scenarios = [
        ("smoke", {}, "success", None),
        (
            "validation_failure",
            {"input_variant": "malformed_validation_fixture"},
            "failed",
            "validation",
        ),
        ("gate_failure", {"training": {"C": 0.0001}}, "failed", "quality_gate"),
        ("recovery", {}, "success", None),
    ]
    for scenario, conf, expected, failed_task in scenarios:
        run_id = f"engineering__{stamp}_{scenario}"
        api(
            "POST",
            f"/dags/{DAG_ID}/dagRuns",
            json={"dag_run_id": run_id, "logical_date": None, "conf": conf},
        )
        print(
            json.dumps({"scenario": scenario, "dag_run_id": run_id, "status": "triggered"}),
            flush=True,
        )
        deadline = time.monotonic() + 600
        while True:
            observed = api("GET", f"/dags/{DAG_ID}/dagRuns/{run_id}")
            if observed["state"] in {"success", "failed"}:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Airflow run did not terminate within 600 seconds")
            time.sleep(3)
        tasks = api("GET", f"/dags/{DAG_ID}/dagRuns/{run_id}/taskInstances")["task_instances"]
        task_rows = []
        for task in tasks:
            row = {
                k: task[k]
                for k in (
                    "task_id",
                    "state",
                    "try_number",
                    "max_tries",
                    "start_date",
                    "end_date",
                    "duration",
                )
            }
            row["logs"] = []
            for attempt in range(1, task["try_number"] + 1):
                response = api(
                    "GET",
                    f"/dags/{DAG_ID}/dagRuns/{run_id}/taskInstances/"
                    f"{task['task_id']}/logs/{attempt}",
                    params={"full_content": True},
                )
                row["logs"].append(
                    {
                        "attempt": attempt,
                        "http_status": 200,
                        "source_entries": len(response["content"]),
                        "structured_events": safe_log_entries(response["content"]),
                    }
                )
            task_rows.append(row)
        persisted = container_read(hashlib.sha256(run_id.encode()).hexdigest())
        result = {
            "scenario": scenario,
            "dag_run_id": run_id,
            "conf": conf,
            "state": observed["state"],
            "tasks": task_rows,
            "artifacts": persisted,
        }
        evidence["runs"].append(result)
        # Preserve actual observations even if an acceptance assertion fails.
        (ROOT / ".local/airflow-dag-observations.json").write_text(json.dumps(evidence, indent=2))
        assert observed["state"] == expected, f"Unexpected state for {scenario}"
        assert {t["task_id"] for t in tasks} == set(STAGES)
        if failed_task:
            states = {t["task_id"]: t["state"] for t in tasks}
            assert states[failed_task] == "failed"
            for downstream in STAGES[STAGES.index(failed_task) + 1 :]:
                assert states[downstream] == "upstream_failed"
            failed = next(t for t in tasks if t["task_id"] == failed_task)
            assert failed["try_number"] == 2  # Observed retry, not just configured.
            assert persisted["approved.json"] is None
        else:
            assert all(t["state"] == "success" for t in tasks)
            assert persisted["approved.json"]["candidate_approved"]
            assert not persisted["approved.json"]["production_promoted"]
        evaluation = persisted["evaluation.json"]
        if evaluation:
            run = registry.get_run(evaluation["run_id"])
            result["mlflow"] = {
                "run_id": run.info.run_id,
                "status": run.info.status,
                "metrics": run.data.metrics,
                "parameters": run.data.params,
                "tags": {k: v for k, v in run.data.tags.items() if k.startswith("assignment.")},
            }
            assert run.data.tags["assignment.candidate_approved"] == (
                "false" if failed_task else "true"
            )
            # Load the HTTP-proxied MLflow model from inside the actual worker.
            script = (
                "import mlflow,mlflow.sklearn,json; "
                "mlflow.set_tracking_uri('http://mlflow:5000'); "
                f"m=mlflow.sklearn.load_model({evaluation['model_uri']!r}); "
                "print(json.dumps({'loaded':True,'prediction':m.predict("
                "[[5.,3.5,1.4,.2]]).tolist()}))"
            )
            loaded = subprocess.run(
                [
                    "docker",
                    "exec",
                    "mlops-assignment3-airflow",
                    "/opt/training/bin/python",
                    "-c",
                    script,
                ],
                capture_output=True,
                text=True,
                timeout=90,
                check=True,
            )
            result["container_artifact_reload"] = json.loads(loaded.stdout.splitlines()[-1])
        print(
            json.dumps(
                {
                    "scenario": scenario,
                    "state": observed["state"],
                    "tasks": {t["task_id"]: t["state"] for t in tasks},
                }
            ),
            flush=True,
        )
    final_health = kube.registry.call("kubernetes_health", {}).model_dump(mode="json")
    evidence["cluster_after"] = final_health
    assert final_health["status"] == "ok"
    assert final_health["evidence"] == baseline_data["evidence"]
    versions_after = [v.version for v in registry.search_model_versions("name = 'assignment-iris'")]
    evidence["registry_versions_after"] = versions_after
    assert versions_after == versions_before
    evidence["finished_at"] = datetime.now(UTC).isoformat()
    target = ROOT / "docs/evidence/airflow-dag-live.json"
    target.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": "ok", "evidence": str(target.relative_to(ROOT))}))
    client.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # No auth/request bodies, headers, HTTP error text or remote logs.
        print(json.dumps({"status": "error", "error_type": type(error).__name__}))
        raise SystemExit(1) from None
