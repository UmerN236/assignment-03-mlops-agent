"""Explicit assignment-only live trigger and reads using the actual tool registry.

Exports only adapter results. Does not rebuild/unpause the DAG, change deployment,
read provider keys into requests, or fabricate diagnostic outcomes.
"""

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from mlops_agent.airflow_tools import DAG_ID, STAGES, AirflowTools
from mlops_agent.config import load_settings

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "docs/evidence/airflow-tools-live.json"
LOCAL = ROOT / ".local/airflow-tools-observations.json"


def main(resume=False):
    settings = load_settings()
    if settings.airflow_base_url != "http://127.0.0.1:8080":
        raise ValueError("Verifier targets only dedicated loopback Airflow")
    inspected = subprocess.run(
        [
            "docker",
            "inspect",
            "mlops-assignment3-airflow",
            "--format",
            '{{index .Config.Labels "com.docker.compose.project"}}',
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert inspected.stdout.strip() == "mlops-assignment3"
    with httpx.Client(base_url=settings.airflow_base_url, timeout=10, trust_env=False) as client:
        unauthenticated = client.get("/api/v2/dags")
        assert unauthenticated.status_code in {401, 403}
        schema_response = client.get("/openapi.json")
        schema_response.raise_for_status()
        schema = schema_response.json()
    required = [
        "/api/v2/dags",
        "/api/v2/dags/{dag_id}/dagRuns",
        "/api/v2/dags/{dag_id}/dagRuns/{dag_run_id}",
        "/api/v2/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances",
        "/api/v2/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances/{task_id}",
        "/api/v2/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances/{task_id}/logs/{try_number}",
    ]
    assert all(path in schema["paths"] for path in required)
    tools = AirflowTools(settings, allow_trigger=True)
    evidence = {
        "observed_at": datetime.now(UTC).isoformat(),
        "dag_id": DAG_ID,
        "unauthenticated_http": unauthenticated.status_code,
        "installed_api_paths_verified": required,
        "authorization": "Explicit engineer invocation of the bounded assignment verifier",
        "observations": [],
    }
    resumed_run_id = None
    if resume:
        previous = json.loads(LOCAL.read_text())
        triggers = [
            o["result"]
            for o in previous["observations"]
            if o["result"]["tool"] == "airflow_trigger_training" and o["result"]["status"] == "ok"
        ]
        assert len(triggers) == 1, "Resume requires exactly one previously observed trigger"
        resumed_run_id = triggers[0]["evidence"]["run"]["dag_run_id"]
        evidence = previous
        evidence["verification_repair"] = (
            "Initial schema rejected a negative API task duration. Preserve and flag the "
            "reported value; resume the same observed run without another trigger."
        )
    request_id = "airflow_tools_" + uuid4().hex

    def call(name, args, expected="ok", registry=tools.registry):
        result = registry.call("airflow_" + name, args, request_id)
        evidence["observations"].append(
            {"arguments": args, "result": result.model_dump(mode="json")}
        )
        LOCAL.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n")
        assert result.status == expected, "Tool acceptance failed: " + name
        return result.evidence

    dag = call("list_dags", {})
    assert len(dag["dags"]) == 1 and not dag["dags"][0]["is_paused"]
    assert not dag["dags"][0]["has_import_errors"]
    recent = call("list_runs", {"limit": 50})
    # Select prior deliberately failed validation/gate runs from fresh API results,
    # never treat historical test failures as live production degradation.
    failed_runs = [r for r in recent["dag_runs"] if r["state"] == "failed"]
    assert failed_runs, "A prior controlled failure is required for diagnosis verification"
    for historical in failed_runs:
        run_id = historical["dag_run_id"]
        failure = call("get_failed_tasks", {"dag_run_id": run_id})
        assert failure["failed_tasks"] and not failure["truncated"]
        for task in failure["failed_tasks"]:
            diagnostic = call(
                "get_task_diagnostics",
                {
                    "dag_run_id": run_id,
                    "task_id": task["task_id"],
                    "try_number": task["try_number"],
                },
            )
            assert diagnostic["log_status"] == "ok" and diagnostic["structured_events"]
            assert any(e["status"] == "error" for e in diagnostic["structured_events"])
    if resumed_run_id:
        run_id = resumed_run_id
    else:
        run_id = "agent__" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S_") + uuid4().hex[:8]
        args = {"dag_run_id": run_id, "confirmation": "trigger assignment_training"}
        # Prove denials through the real registry before the one authorized write.
        call("trigger_training", args, "invalid_request", AirflowTools(settings).registry)
        call("trigger_training", {**args, "dag_id": "unapproved"}, "invalid_request")
        triggered = call("trigger_training", args)
        assert triggered["run"]["dag_run_id"] == run_id
        print(
            json.dumps({"triggered_run_id": run_id, "state": triggered["run"]["state"]}), flush=True
        )
    deadline = time.monotonic() + 180
    while True:
        observed = call("get_run", {"dag_run_id": run_id})
        if observed["terminal"]:
            break
        assert time.monotonic() < deadline, "Run remains nonterminal; observations preserved"
        time.sleep(3)
    assert observed["run"]["state"] == "success"
    assert not observed["tasks_truncated"]
    assert {t["task_id"] for t in observed["tasks"]} == set(STAGES)
    assert all(t["state"] == "success" for t in observed["tasks"])
    diagnosis = call(
        "get_task_diagnostics",
        {
            "dag_run_id": run_id,
            "task_id": "validation",
            "try_number": 1,
        },
    )
    assert diagnosis["log_status"] == "ok" and diagnosis["structured_events"]
    assert not call("get_failed_tasks", {"dag_run_id": run_id})["failed_tasks"]
    evidence["verified_trigger_run_id"] = run_id
    evidence["finished_at"] = datetime.now(UTC).isoformat()
    TARGET.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": "ok", "run_id": run_id, "evidence": str(TARGET.relative_to(ROOT))}))


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument(
            "--resume",
            action="store_true",
            help="Resume the one actual trigger in local observations; no new write",
        )
        main(parser.parse_args().resume)
    except Exception as error:
        print(json.dumps({"status": "error", "error_type": type(error).__name__}))
        raise SystemExit(1) from None
