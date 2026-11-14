"""Authenticated Airflow 3 operations; bounded worker, approved DAG, explicit writes.

Only selected response fields and known structured stage events leave the worker.
Tokens/passwords travel over stdin, never argv, inherited env, evidence or logs.
"""

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, computed_field

from mlops_agent.config import Settings
from mlops_agent.tools import ToolDefinition, ToolFailure, ToolInput, ToolRegistry

DAG_ID = "assignment_training"
STAGES = (
    "validation",
    "preprocessing",
    "training",
    "evaluation",
    "quality_gate",
    "approve_candidate",
)
RunID = Annotated[
    str, Field(min_length=1, max_length=250, pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.:+-]*$")
]
TaskID = Literal[
    "validation", "preprocessing", "training", "evaluation", "quality_gate", "approve_candidate"
]
RunState = Literal["queued", "running", "success", "failed"]
TaskState = Literal[
    "removed",
    "scheduled",
    "queued",
    "running",
    "success",
    "restarting",
    "failed",
    "up_for_retry",
    "up_for_reschedule",
    "upstream_failed",
    "skipped",
    "deferred",
]
MAX_RESPONSE_BYTES = 1024 * 1024


class DagInput(ToolInput):
    dag_id: Literal["assignment_training"] = DAG_ID


class ListInput(DagInput):
    limit: int = Field(default=10, ge=1, le=50)


class RunInput(DagInput):
    dag_run_id: RunID


class StatusInput(RunInput):
    wait_seconds: int = Field(default=0, ge=0, le=60)


class TriggerInput(DagInput):
    dag_run_id: str = Field(pattern=r"^agent__[A-Za-z0-9_]{1,100}$")
    confirmation: Literal["trigger assignment_training"]


class DiagnosticsInput(RunInput):
    task_id: TaskID
    try_number: int = Field(default=1, ge=1, le=10)


class Observation(BaseModel):
    # Airflow adds fields between releases. Validate/export only this projection.
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)


class TimedObservation(Observation):
    start_date: datetime | None
    end_date: datetime | None
    duration: float | None = Field(allow_inf_nan=False)

    @computed_field
    @property
    def negative_duration_reported(self) -> bool:
        # The live 3.1.3 API can report negative durations. Preserve the observed
        # number, flag the inconsistency, and do not infer a cause or clamp it.
        return self.duration is not None and self.duration < 0


class RunObservation(TimedObservation):
    dag_id: Literal["assignment_training"]
    dag_run_id: RunID
    state: RunState
    logical_date: datetime | None


class TaskObservation(TimedObservation):
    dag_id: Literal["assignment_training"]
    dag_run_id: RunID
    task_id: TaskID
    state: TaskState | None
    try_number: int = Field(ge=0)
    max_tries: int = Field(ge=0)
    map_index: Literal[-1]


class DagObservation(Observation):
    dag_id: str = Field(min_length=1, max_length=250)
    is_paused: bool
    has_import_errors: bool


class DagCollection(Observation):
    dags: list[DagObservation] = Field(max_length=50)
    total_entries: int = Field(ge=0)


class RunCollection(Observation):
    dag_runs: list[RunObservation] = Field(max_length=50)
    total_entries: int = Field(ge=0)


class TaskCollection(Observation):
    task_instances: list[TaskObservation] = Field(max_length=100)
    total_entries: int = Field(ge=0)


class LogObservation(Observation):
    content: list[dict | str] = Field(max_length=10000)
    continuation_token: str | None = None


def project(model, raw):
    try:
        # JSON mode allows ISO datetimes while keeping numbers/bools strictly typed.
        return model.model_validate_json(json.dumps(raw))
    except (ValidationError, ValueError, TypeError):
        raise ToolFailure("Airflow returned an invalid response schema", "unavailable") from None


def structured_events(content, run_id, task_id):
    selected = []
    for entry in content:
        event = entry.get("event") if isinstance(entry, dict) else entry
        try:
            value = json.loads(event) if isinstance(event, str) else None
        except ValueError:
            continue
        if not isinstance(value, dict):
            continue
        duration = value.get("duration_ms")
        if (
            value.get("tool") == "airflow_" + task_id
            and value.get("status") in {"ok", "error"}
            and type(duration) in {float, int}
            and math.isfinite(duration)
            and 0 <= duration <= 600000
            and value.get("request_id") in {run_id, hashlib.sha256(run_id.encode()).hexdigest()}
        ):
            selected.append({k: value[k] for k in ("tool", "status", "duration_ms", "request_id")})
    return selected[-100:]


class AirflowAPI:
    """One operation per client. No redirect, ambient proxy, automatic POST retry."""

    def __init__(self, client: httpx.Client, config: dict):
        self.client, self.config = client, config
        self.authenticated = False

    def request(self, method, path, **kwargs):
        for attempt in range(2 if method == "GET" else 1):
            try:
                with self.client.stream(method, path, **kwargs) as response:
                    code = response.status_code
                    if code in {502, 503, 504} and method == "GET" and attempt == 0:
                        continue
                    if code in {401, 403}:
                        raise ToolFailure(
                            "Airflow credentials rejected or access denied", "unavailable"
                        )
                    if code == 429:
                        raise ToolFailure(
                            "Airflow quota/rate limit reached; retry later", "unavailable"
                        )
                    if code == 404:
                        raise ToolFailure("Airflow resource or logs not found", "unavailable")
                    if code == 409:
                        raise ToolFailure(
                            "Run ID already exists; query it. Trigger was not retried"
                        )
                    if code >= 500:
                        raise ToolFailure(
                            "Airflow service failed; trigger outcome may be unknown. "
                            "Query supplied run ID"
                            if method == "POST" and path.startswith("/api/v2/")
                            else "Airflow service failed; no observations available",
                            "unavailable",
                        )
                    if not 200 <= code < 300:
                        raise ToolFailure("Airflow rejected the request; no response body exported")
                    payload = bytearray()
                    for chunk in response.iter_bytes():
                        payload.extend(chunk)
                        if len(payload) > MAX_RESPONSE_BYTES:
                            raise ToolFailure("Airflow response exceeded size limit", "unavailable")
                    value = json.loads(payload)
                    if not isinstance(value, dict):
                        raise ValueError
                    return value
            except (httpx.TimeoutException, httpx.TransportError):
                raise ToolFailure(
                    "Airflow request failed; trigger outcome may be unknown. "
                    "Query supplied run ID before any retry"
                    if method == "POST" and path.startswith("/api/v2/")
                    else "Airflow request timed out or connection failed",
                    "unavailable",
                ) from None
            except (ValueError, UnicodeError):
                raise ToolFailure("Airflow returned invalid JSON", "unavailable") from None

    def authenticate(self):
        if self.authenticated:
            return
        token = self.config.get("token")
        if not token:
            password = self.config.get("password")
            if not password and self.config["base_url"] == "http://127.0.0.1:8080":
                try:
                    path = Path(self.config["password_file"])
                    if path.stat().st_size > 16384:
                        raise ValueError
                    password = json.loads(path.read_text())[self.config["username"]]
                    if not isinstance(password, str) or not password:
                        raise ValueError
                except (OSError, ValueError, KeyError, TypeError):
                    raise ToolFailure(
                        "Airflow local credential unavailable", "unavailable"
                    ) from None
            if not password:
                raise ToolFailure("Missing Airflow credentials", "unavailable")
            response = self.request(
                "POST",
                "/auth/token",
                json={"username": self.config["username"], "password": password},
            )
            token = response.get("access_token")
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,16384}", token):
            raise ToolFailure("Invalid Airflow access token", "unavailable")
        self.client.headers["Authorization"] = "Bearer " + token
        self.authenticated = True

    def api(self, method, path, **kwargs):
        self.authenticate()
        return self.request(method, "/api/v2" + path, **kwargs)

    @staticmethod
    def run_path(args):
        return f"/dags/{DAG_ID}/dagRuns/{quote(args.dag_run_id, safe='')}"

    def run(self, args):
        observed = project(RunObservation, self.api("GET", self.run_path(args)))
        if observed.dag_run_id != args.dag_run_id:
            raise ToolFailure("Airflow returned a mismatched run identity", "unavailable")
        return observed

    def tasks(self, args):
        collection = project(
            TaskCollection,
            self.api("GET", self.run_path(args) + "/taskInstances", params={"limit": 100}),
        )
        if any(t.dag_run_id != args.dag_run_id for t in collection.task_instances):
            raise ToolFailure("Airflow returned mismatched task identity", "unavailable")
        if len({t.task_id for t in collection.task_instances}) != len(collection.task_instances):
            raise ToolFailure("Airflow returned duplicate task identity", "unavailable")
        return collection

    def list_dags(self, args):
        observed = project(
            DagCollection,
            self.api("GET", "/dags", params={"limit": args.limit, "dag_id_pattern": DAG_ID}),
        )
        return {
            "dags": [d.model_dump(mode="json") for d in observed.dags if d.dag_id == DAG_ID],
            "api_total_entries": observed.total_entries,
            "truncated": observed.total_entries > len(observed.dags),
            "scope": "Only assignment_training is exported; other DAGs are omitted",
        }

    def list_runs(self, args):
        observed = project(
            RunCollection,
            self.api(
                "GET",
                f"/dags/{DAG_ID}/dagRuns",
                params={"limit": args.limit, "order_by": "-run_after"},
            ),
        )
        return {
            **observed.model_dump(mode="json"),
            "truncated": observed.total_entries > len(observed.dag_runs),
        }

    def get_run(self, args):
        if args.wait_seconds > max(0, self.config["timeout"] - 5):
            raise ValueError("Polling must fit the configured operation budget")
        deadline = time.monotonic() + args.wait_seconds
        polls = 0
        while True:
            observed = self.run(args)
            polls += 1
            terminal = observed.state in {"success", "failed"}
            remaining = deadline - time.monotonic()
            if terminal or remaining <= 0:
                break
            time.sleep(min(2, remaining))
        tasks = self.tasks(args)
        return {
            "run": observed.model_dump(mode="json"),
            "tasks": [t.model_dump(mode="json") for t in tasks.task_instances],
            "tasks_truncated": tasks.total_entries > len(tasks.task_instances),
            "terminal": terminal,
            "poll_attempts": polls,
            "polling_timed_out": bool(args.wait_seconds and not terminal),
        }

    def trigger_training(self, args):
        if not self.config.get("allow_trigger"):
            raise ValueError("Trigger requires trusted caller authorization")
        # Revalidate even for direct calls outside the registry. Canonical data and
        # fixed quality policy only; no arbitrary conf, paths, backfill or unpause.
        args = TriggerInput.model_validate(args.model_dump())
        observed = project(
            RunObservation,
            self.api(
                "POST",
                f"/dags/{DAG_ID}/dagRuns",
                json={"dag_run_id": args.dag_run_id, "logical_date": None, "conf": {}},
            ),
        )
        if observed.dag_run_id != args.dag_run_id:
            raise ToolFailure("Airflow trigger returned mismatched run ID; inspect before retry")
        return {"run": observed.model_dump(mode="json"), "automatically_promotes_or_deploys": False}

    def get_failed_tasks(self, args):
        run = self.run(args)
        tasks = self.tasks(args)
        rows = [t.model_dump(mode="json") for t in tasks.task_instances]
        return {
            "run": run.model_dump(mode="json"),
            "failed_tasks": [t for t in rows if t["state"] == "failed"],
            "blocked_tasks": [t for t in rows if t["state"] == "upstream_failed"],
            "retrying_tasks": [t for t in rows if t["state"] == "up_for_retry"],
            "truncated": tasks.total_entries > len(rows),
            "interpretation": "States are observations; an empty list is not proof of run success",
        }

    def get_task_diagnostics(self, args):
        path = self.run_path(args) + f"/taskInstances/{args.task_id}"
        task = project(TaskObservation, self.api("GET", path))
        if task.dag_run_id != args.dag_run_id or task.task_id != args.task_id:
            raise ToolFailure("Airflow returned mismatched task identity", "unavailable")
        if args.try_number > task.try_number:
            raise ValueError("Requested attempt has not executed")
        result = {"task": task.model_dump(mode="json"), "log_attempt": args.try_number}
        try:
            logs = project(
                LogObservation,
                self.api(
                    "GET",
                    path + f"/logs/{args.try_number}",
                    params={"full_content": False, "map_index": -1},
                ),
            )
        except ToolFailure as exc:
            # Preserve real task facts when logs expired or log backend is down.
            return {
                **result,
                "log_status": "unavailable",
                "log_error": str(exc),
                "structured_events": [],
                "logs_complete": False,
            }
        return {
            **result,
            "log_status": "ok",
            "source_entries": len(logs.content),
            "structured_events": structured_events(logs.content, args.dag_run_id, args.task_id),
            "logs_complete": not bool(logs.continuation_token),
            "raw_logs_omitted": True,
            "diagnostic_limit": "Known stage events only; inspect Airflow UI for full logs",
        }


OPERATIONS = {
    "list_dags": (ListInput, "List the approved DAG, pause and import-error states"),
    "list_runs": (ListInput, "Read recent approved-DAG runs ordered by run_after descending"),
    "get_run": (StatusInput, "Read actual run/task states with optional bounded polling"),
    "trigger_training": (
        TriggerInput,
        "Explicitly trigger canonical training; requires host authorization",
    ),
    "get_failed_tasks": (RunInput, "Identify failed, upstream-blocked and retrying tasks"),
    "get_task_diagnostics": (
        DiagnosticsInput,
        "Read execution timing, attempts and sanitized log events",
    ),
}


class AirflowTools:
    def __init__(self, settings: Settings, *, allow_trigger: bool = False, transport=None):
        self.settings, self.allow_trigger = settings, allow_trigger
        self.transport = transport or self._worker
        self.registry = ToolRegistry(
            [
                ToolDefinition(
                    "airflow_" + op,
                    description,
                    model,
                    lambda args, op=op: self._dispatch(op, args),
                )
                for op, (model, description) in OPERATIONS.items()
            ]
        )

    def _dispatch(self, operation, args):
        if operation == "trigger_training" and not self.allow_trigger:
            raise ValueError("Trigger requires explicit trusted authorization")
        if operation == "get_run" and args.wait_seconds > max(
            0, self.settings.tool_timeout_seconds - 5
        ):
            raise ValueError("Polling exceeds operation budget")
        return self.transport(operation, args.model_dump())

    def _worker(self, operation, arguments):
        settings = self.settings
        root = Path(__file__).resolve().parents[2]
        config = {
            "base_url": settings.airflow_base_url,
            "username": settings.airflow_username,
            "password": settings.airflow_password.get_secret_value()
            if settings.airflow_password
            else None,
            "token": settings.airflow_token.get_secret_value() if settings.airflow_token else None,
            "password_file": str(settings.airflow_password_file.resolve()),
            "timeout": settings.tool_timeout_seconds,
            "allow_trigger": self.allow_trigger,
        }
        try:
            result = subprocess.run(
                [sys.executable, "-m", "mlops_agent.airflow_tools", "--worker"],
                input=json.dumps(
                    {"operation": operation, "arguments": arguments, "config": config}
                ),
                capture_output=True,
                text=True,
                timeout=settings.tool_timeout_seconds,
                cwd=root,
                shell=False,
                env={
                    "PATH": os.defpath,
                    "PYTHONPATH": str(root / "src"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )
        except subprocess.TimeoutExpired:
            raise ToolFailure(
                "Airflow deadline exceeded; query supplied run ID before retrying a trigger",
                "unavailable",
            ) from None
        except OSError:
            raise ToolFailure("Airflow worker unavailable", "unavailable") from None
        try:
            response = json.loads(result.stdout)
            if result.returncode or not isinstance(response, dict):
                raise ValueError
            if response.get("status") in {"unavailable", "error"}:
                raise ToolFailure(response["error"], response["status"])
            if response.get("status") != "ok" or not isinstance(response.get("evidence"), dict):
                raise ValueError
            return response["evidence"]
        except (ValueError, KeyError, TypeError):
            raise ToolFailure("Invalid Airflow worker response", "unavailable") from None


def worker_main():
    try:
        request = json.load(sys.stdin)
        operation, config = request["operation"], request["config"]
        args = OPERATIONS[operation][0].model_validate(request["arguments"])
        with httpx.Client(
            base_url=config["base_url"],
            timeout=min(10, config["timeout"]),
            follow_redirects=False,
            trust_env=False,
            headers={"Accept": "application/json"},
        ) as client:
            evidence = getattr(AirflowAPI(client, config), operation)(args)
        response = {"status": "ok", "evidence": evidence}
    except ToolFailure as exc:
        response = {"status": exc.status, "error": str(exc)}
    except Exception:
        response = {
            "status": "unavailable",
            "error": "Airflow worker failed; no observations available",
        }
    print(json.dumps(response, allow_nan=False))


if __name__ == "__main__" and sys.argv[1:] == ["--worker"]:
    worker_main()
