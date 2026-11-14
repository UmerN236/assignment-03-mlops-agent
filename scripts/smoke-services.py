"""Read-only, bounded bootstrap checks. Emits only allowlisted observations."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
from mlflow import MlflowClient

from mlops_agent.config import load_settings

ROOT = Path(__file__).resolve().parents[1]


def check_mlflow(settings):
    with httpx.Client(timeout=settings.tool_timeout_seconds) as client:
        response = client.get(settings.mlflow_tracking_uri + "/health")
        response.raise_for_status()
    # Real supported API, not UI scraping. No runs are created by this check.
    experiments = MlflowClient(tracking_uri=settings.mlflow_tracking_uri).search_experiments()
    return {"status": "ok", "health_http": response.status_code, "experiments": len(experiments)}


def check_airflow(settings):
    with httpx.Client(timeout=settings.tool_timeout_seconds) as client:
        health = client.get(settings.airflow_base_url + "/api/v2/monitor/health")
        health.raise_for_status()
        unauthenticated = client.get(settings.airflow_base_url + "/api/v2/dags")
        if unauthenticated.status_code not in (401, 403):
            raise ValueError("Public API failed to reject unauthenticated access")
        if settings.airflow_token:
            token = settings.airflow_token.get_secret_value()
        else:
            password = (
                settings.airflow_password.get_secret_value() if settings.airflow_password else None
            )
            if password is None:
                password_file = (
                    ROOT / ".local/runtime/airflow/simple_auth_manager_passwords.json.generated"
                )
                password = json.loads(password_file.read_text())[settings.airflow_username]
            auth = client.post(
                settings.airflow_base_url + "/auth/token",
                json={"username": settings.airflow_username, "password": password},
            )
            auth.raise_for_status()
            token = auth.json()["access_token"]
        dags = client.get(
            settings.airflow_base_url + "/api/v2/dags",
            headers={"Authorization": f"Bearer {token}"},
        )
        dags.raise_for_status()
        observed = health.json()
        components = {
            name: observed.get(name, {}).get("status", "unknown")
            for name in ("metadatabase", "scheduler", "dag_processor", "triggerer")
        }
        return {
            "status": "ok" if all(v == "healthy" for v in components.values()) else "unhealthy",
            "unauthenticated_http": unauthenticated.status_code,
            "authenticated_http": dags.status_code,
            "dags": dags.json()["total_entries"],
            "components": components,
        }


def check_cluster(settings):
    prefix = [
        str(ROOT / ".local/bin/kubectl"),
        "--cache-dir",
        str(ROOT / ".local/cache/kubectl"),
        "--kubeconfig",
        str(settings.kubeconfig),
        "--context",
        settings.kubernetes_context,
        "--request-timeout=10s",
    ]

    def read(args):
        result = subprocess.run(
            prefix + args + ["-o", "json"],
            capture_output=True,
            text=True,
            timeout=settings.tool_timeout_seconds,
            check=True,
        )
        return json.loads(result.stdout)

    nodes = read(["get", "nodes"])
    namespace = read(["get", "namespace", settings.kubernetes_namespace])
    ready = [
        {
            "name": node["metadata"]["name"],
            "kubelet_version": node["status"]["nodeInfo"]["kubeletVersion"],
            "ready": any(
                c["type"] == "Ready" and c["status"] == "True" for c in node["status"]["conditions"]
            ),
        }
        for node in nodes["items"]
    ]
    return {
        "status": "ok" if ready and all(n["ready"] for n in ready) else "unhealthy",
        "nodes": ready,
        "namespace_phase": namespace["status"]["phase"],
    }


def main():
    settings = load_settings()
    # Also bound MlflowClient's HTTP retries/timeouts (its defaults are longer).
    import os

    os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"] = str(int(settings.tool_timeout_seconds))
    os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"] = "0"
    result = {"observed_at": datetime.now(UTC).isoformat(), "checks": {}}
    for name, check in (
        ("mlflow", check_mlflow),
        ("airflow", check_airflow),
        ("kubernetes", check_cluster),
    ):
        try:
            result["checks"][name] = check(settings)
        except Exception as error:
            # Raw HTTP bodies, exception strings and subprocess output may contain secrets.
            result["checks"][name] = {"status": "unavailable", "error_type": type(error).__name__}
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if all(c["status"] == "ok" for c in result["checks"].values()) else 1)


if __name__ == "__main__":
    main()
