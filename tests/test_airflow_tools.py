"""No live services: auth, API contracts, failures, policy and worker boundary."""

import json
import logging
import subprocess
from types import SimpleNamespace

import httpx
import pytest

from mlops_agent.airflow_tools import (
    DAG_ID,
    AirflowAPI,
    AirflowTools,
    DiagnosticsInput,
    ListInput,
    RunInput,
    StatusInput,
    TriggerInput,
)
from mlops_agent.config import Settings
from mlops_agent.tools import ToolFailure

RUN = "agent__test_run"
CONFIRM = {"dag_run_id": RUN, "confirmation": "trigger assignment_training"}
SECRET = "private-credential-sentinel"


def run(state="success", **kwargs):
    return {
        "dag_id": DAG_ID,
        "dag_run_id": RUN,
        "state": state,
        "logical_date": None,
        "start_date": "2026-11-14T12:00:00Z",
        "end_date": None,
        "duration": 1.2,
        "conf": {"secret": SECRET},
        **kwargs,
    }


def task(state="failed", task_id="validation", **kwargs):
    return {
        "dag_id": DAG_ID,
        "dag_run_id": RUN,
        "task_id": task_id,
        "state": state,
        "try_number": 2,
        "max_tries": 1,
        "map_index": -1,
        "start_date": None,
        "end_date": None,
        "duration": None,
        "rendered_fields": {"secret": SECRET},
        **kwargs,
    }


def config(**kwargs):
    return {
        "base_url": "http://test",
        "token": "test-token",
        "password": None,
        "username": "admin",
        "password_file": "/missing",
        "timeout": 30,
        "allow_trigger": False,
        **kwargs,
    }


def api(handler, **kwargs):
    client = httpx.Client(
        base_url="http://test",
        transport=httpx.MockTransport(handler),
        headers={"Accept": "application/json"},
    )
    return AirflowAPI(client, config(**kwargs))


def response(value, code=200):
    return httpx.Response(code, json=value)


def test_six_individual_schemas_and_safe_default():
    tools = AirflowTools(
        Settings(_env_file=None), transport=lambda *_: pytest.fail("HTTP executed")
    )
    assert len(tools.registry.tools) == 6
    for definition in tools.registry.tools.values():
        assert definition.schema()["parameters"]["additionalProperties"] is False
        assert definition.schema()["output_schema"]["required"]
    result = tools.registry.call("airflow_trigger_training", CONFIRM)
    assert result.status == "invalid_request" and not result.evidence


@pytest.mark.parametrize(
    "operation,args",
    [
        ("list_dags", {"dag_id": "unrelated"}),
        ("get_run", {"dag_run_id": "../secret"}),
        ("get_run", {"dag_run_id": ".."}),
        ("get_run", {"dag_run_id": RUN, "wait_seconds": 61}),
        ("list_runs", {"limit": True}),
        ("list_runs", {"limit": 51}),
        ("trigger_training", {"dag_run_id": RUN}),
        ("trigger_training", {**CONFIRM, "confirmation": "yes"}),
        ("trigger_training", {**CONFIRM, "dag_id": "other"}),
        ("trigger_training", {**CONFIRM, "conf": {"input_variant": "corrupt"}}),
        ("get_task_diagnostics", {"dag_run_id": RUN, "task_id": "../task"}),
        ("get_task_diagnostics", {"dag_run_id": RUN, "task_id": "validation", "try_number": 11}),
    ],
)
def test_invalid_inputs_never_execute_transport(operation, args):
    tools = AirflowTools(
        Settings(_env_file=None),
        allow_trigger=True,
        transport=lambda *_: pytest.fail("Transport executed"),
    )
    result = tools.registry.call("airflow_" + operation, args)
    assert result.status == "invalid_request" and result.evidence == {}


def test_password_exchange_and_bearer_header():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/auth/token":
            assert json.loads(request.content) == {"username": "admin", "password": SECRET}
            return response({"access_token": "issued.jwt.token"})
        assert request.headers["Authorization"] == "Bearer issued.jwt.token"
        return response(
            {
                "dags": [{"dag_id": DAG_ID, "is_paused": False, "has_import_errors": False}],
                "total_entries": 1,
            }
        )

    reader = api(handler, token=None, password=SECRET)
    facts = reader.list_dags(ListInput())
    reader.list_dags(ListInput())
    assert calls.count("/auth/token") == 1
    assert facts["dags"][0]["dag_id"] == DAG_ID
    assert SECRET not in json.dumps(facts)


def test_explicit_token_never_reads_password_file(tmp_path):
    reader = api(
        lambda request: response({"dags": [], "total_entries": 0}),
        password_file=str(tmp_path / "missing"),
    )
    assert reader.list_dags(ListInput())["dags"] == []


def test_local_generated_credential_without_env_write(tmp_path):
    path = tmp_path / "generated.json"
    path.write_text(json.dumps({"admin": SECRET}))

    def handler(request):
        if request.url.path == "/auth/token":
            assert json.loads(request.content)["password"] == SECRET
            return response({"access_token": "issued.jwt"})
        return response({"dags": [], "total_entries": 0})

    reader = api(handler, base_url="http://127.0.0.1:8080", token=None, password_file=str(path))
    assert reader.list_dags(ListInput())["dags"] == []
    assert path.read_text() == json.dumps({"admin": SECRET})


@pytest.mark.parametrize("local", [False, True])
def test_missing_credentials_are_unavailable_without_http(local):
    reader = api(
        lambda *_: pytest.fail("HTTP executed"),
        token=None,
        base_url="http://127.0.0.1:8080" if local else "https://remote.example",
    )
    with pytest.raises(ToolFailure, match="credential"):
        reader.list_dags(ListInput())


@pytest.mark.parametrize("code", [401, 403, 404, 422, 429, 500])
def test_http_errors_hide_remote_body(code):
    reader = api(lambda _: response({"detail": SECRET}, code))
    with pytest.raises(ToolFailure) as exc:
        reader.list_dags(ListInput())
    assert SECRET not in str(exc.value)
    if code in {401, 403}:
        assert "credentials rejected" in str(exc.value)


def test_authentication_error_never_falls_back_or_exports_credentials():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return response({"detail": SECRET}, 401)

    reader = api(handler, token=None, password=SECRET)
    with pytest.raises(ToolFailure, match="credentials rejected"):
        reader.list_dags(ListInput())
    assert calls == ["/auth/token"]


def test_bounded_get_retry_and_filtered_dags():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return response({}, 503)
        return response(
            {
                "dags": [
                    {"dag_id": "unrelated", "is_paused": False, "has_import_errors": False},
                    {"dag_id": DAG_ID, "is_paused": True, "has_import_errors": False},
                ],
                "total_entries": 3,
            }
        )

    facts = api(handler).list_dags(ListInput())
    assert len(calls) == 2 and facts["truncated"]
    assert [d["dag_id"] for d in facts["dags"]] == [DAG_ID]


@pytest.mark.parametrize("code", [503, 409])
def test_post_is_never_retried(code):
    calls = []

    def handler(request):
        calls.append(request)
        return response({}, code)

    reader = api(handler, allow_trigger=True)
    with pytest.raises(ToolFailure, match="[Qq]uery"):
        reader.trigger_training(TriggerInput(**CONFIRM))
    assert len(calls) == 1


def test_explicit_trigger_returns_actual_server_identity_and_canonical_conf():
    def handler(request):
        assert request.method == "POST"
        assert json.loads(request.content) == {"dag_run_id": RUN, "logical_date": None, "conf": {}}
        assert request.url.path == f"/api/v2/dags/{DAG_ID}/dagRuns"
        return response(run("queued"))

    facts = api(handler, allow_trigger=True).trigger_training(TriggerInput(**CONFIRM))
    assert facts["run"]["dag_run_id"] == RUN and facts["run"]["state"] == "queued"
    assert not facts["automatically_promotes_or_deploys"]
    assert SECRET not in json.dumps(facts)


def test_direct_trigger_requires_trusted_authorization():
    with pytest.raises(ValueError):
        api(lambda _: pytest.fail("HTTP executed")).trigger_training(TriggerInput(**CONFIRM))


@pytest.mark.parametrize("raw", [[], {"dags": [], "total_entries": "0"}, {"dags": []}])
def test_invalid_json_shapes_are_service_failures(raw):
    with pytest.raises(ToolFailure, match="invalid"):
        api(lambda _: response(raw)).list_dags(ListInput())


def test_invalid_json_and_oversized_response():
    for raw in [b"not json", b"x" * (1024 * 1024 + 1)]:
        with pytest.raises(ToolFailure):
            api(lambda _, raw=raw: httpx.Response(200, content=raw)).list_dags(ListInput())


def test_service_timeout_never_becomes_an_observation():
    def handler(request):
        raise httpx.ReadTimeout(SECRET, request=request)

    with pytest.raises(ToolFailure, match="timed out") as exc:
        api(handler).list_dags(ListInput())
    assert SECRET not in str(exc.value)


def test_recent_runs_order_and_truncation():
    def handler(request):
        assert request.url.params["order_by"] == "-run_after"
        assert request.url.params["limit"] == "1"
        return response({"dag_runs": [run()], "total_entries": 10})

    facts = api(handler).list_runs(ListInput(limit=1))
    assert facts["truncated"] and len(facts["dag_runs"]) == 1


def test_status_uses_actual_states_and_separates_failed_from_blocked():
    def handler(request):
        if request.url.path.endswith("taskInstances"):
            return response(
                {
                    "task_instances": [
                        task(),
                        task("upstream_failed", "training"),
                        task("up_for_retry", "quality_gate"),
                    ],
                    "total_entries": 3,
                }
            )
        return response(run("failed"))

    reader = api(handler)
    facts = reader.get_run(StatusInput(dag_run_id=RUN))
    assert facts["terminal"] and facts["run"]["state"] == "failed"
    facts = reader.get_failed_tasks(RunInput(dag_run_id=RUN))
    assert facts["failed_tasks"][0]["task_id"] == "validation"
    assert facts["blocked_tasks"][0]["task_id"] == "training"
    assert facts["retrying_tasks"][0]["task_id"] == "quality_gate"
    assert SECRET not in json.dumps(facts)


def test_bounded_polling_retains_nonterminal_observation(monkeypatch):
    ticks = iter([0, 0, 2])
    monkeypatch.setattr("mlops_agent.airflow_tools.time.monotonic", lambda: next(ticks))
    sleeps = []
    monkeypatch.setattr("mlops_agent.airflow_tools.time.sleep", sleeps.append)

    def handler(request):
        if request.url.path.endswith("taskInstances"):
            return response({"task_instances": [], "total_entries": 0})
        return response(run("running"))

    facts = api(handler).get_run(StatusInput(dag_run_id=RUN, wait_seconds=1))
    assert facts["polling_timed_out"] and not facts["terminal"]
    assert facts["run"]["state"] == "running" and facts["poll_attempts"] == 2
    assert sleeps == [1]


def test_polling_budget_rejected_before_transport():
    tools = AirflowTools(
        Settings(_env_file=None, tool_timeout_seconds=5),
        transport=lambda *_: pytest.fail("HTTP executed"),
    )
    result = tools.registry.call("airflow_get_run", {"dag_run_id": RUN, "wait_seconds": 1})
    assert result.status == "invalid_request"


@pytest.mark.parametrize("kind", ["run", "task"])
def test_identity_mismatch_never_fabricates_correlated_evidence(kind):
    def handler(request):
        if kind == "task":
            return response({"task_instances": [task(dag_run_id="other")], "total_entries": 1})
        return response(run(dag_run_id="other"))

    reader = api(handler)
    with pytest.raises(ToolFailure, match="identity"):
        (reader.run if kind == "run" else reader.tasks)(RunInput(dag_run_id=RUN))


def test_task_diagnostics_preserves_attempt_and_filters_arbitrary_logs():
    valid = {
        "tool": "airflow_validation",
        "status": "error",
        "duration_ms": 2.5,
        "request_id": RUN,
        "private": SECRET,
    }

    def handler(request):
        if "/logs/" in request.url.path:
            assert request.url.params["full_content"] == "false"
            return response(
                {
                    "content": [
                        {"event": SECRET},
                        {"event": json.dumps(valid)},
                        {"event": json.dumps({**valid, "request_id": SECRET})},
                        {"event": json.dumps({**valid, "tool": SECRET})},
                        {"event": json.dumps({**valid, "duration_ms": float("nan")})},
                    ],
                    "continuation_token": "secret-continuation",
                }
            )
        return response(task())

    facts = api(handler).get_task_diagnostics(
        DiagnosticsInput(dag_run_id=RUN, task_id="validation", try_number=2)
    )
    assert facts["task"]["try_number"] == 2 and facts["task"]["max_tries"] == 1
    assert facts["structured_events"] == [{k: v for k, v in valid.items() if k != "private"}]
    assert not facts["logs_complete"] and facts["raw_logs_omitted"]
    assert SECRET not in json.dumps(facts) and "secret-continuation" not in json.dumps(facts)


def test_missing_logs_preserves_observed_task_but_marks_logs_unknown():
    reader = api(lambda r: response({}, 404) if "/logs/" in r.url.path else response(task()))
    facts = reader.get_task_diagnostics(DiagnosticsInput(dag_run_id=RUN, task_id="validation"))
    assert facts["task"]["state"] == "failed"
    assert facts["log_status"] == "unavailable" and facts["structured_events"] == []


def test_unexecuted_attempt_rejected():
    reader = api(lambda _: response(task(try_number=0)))
    with pytest.raises(ValueError):
        reader.get_task_diagnostics(DiagnosticsInput(dag_run_id=RUN, task_id="validation"))


def test_hard_worker_timeout_no_env_secrets_or_argv_secrets(monkeypatch, caplog):
    def fake_run(command, **kwargs):
        assert SECRET not in str(command)
        assert SECRET not in str(kwargs["env"])
        assert "OPENROUTER_API_KEY" not in kwargs["env"]
        assert kwargs["shell"] is False and kwargs["timeout"] == 2
        assert json.loads(kwargs["input"])["config"]["token"] == SECRET
        raise subprocess.TimeoutExpired(command, 2, output=SECRET, stderr=SECRET)

    monkeypatch.setattr(subprocess, "run", fake_run)
    tools = AirflowTools(Settings(_env_file=None, airflow_token=SECRET, tool_timeout_seconds=2))
    with caplog.at_level(logging.INFO):
        result = tools.registry.call("airflow_list_dags", {}, "request-test")
    assert result.status == "unavailable" and not result.evidence
    assert SECRET not in result.model_dump_json() + caplog.text
    record = caplog.records[-1]
    assert (record.tool, record.status, record.request_id) == (
        "airflow_list_dags",
        "unavailable",
        "request-test",
    )
    assert record.duration_ms >= 0


@pytest.mark.parametrize(
    "stdout,code",
    [
        ("not json", 0),
        ("[]", 0),
        ('{"status":"ok","evidence":[]}', 0),
        ('{"status":"ok","evidence":{}}', 1),
        ('{"status":"unavailable","error":"Airflow credentials rejected"}', 0),
    ],
)
def test_worker_protocol_failures_preserve_unknowns(monkeypatch, stdout, code):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout=stdout, stderr=SECRET, returncode=code),
    )
    result = AirflowTools(Settings(_env_file=None)).registry.call("airflow_list_runs", {})
    assert result.status == "unavailable" and result.evidence == {}
    assert SECRET not in result.model_dump_json()


def test_negative_api_duration_is_preserved_and_flagged():
    reader = api(
        lambda r: response({"task_instances": [task(duration=-55.828)], "total_entries": 1})
        if r.url.path.endswith("taskInstances")
        else response(run())
    )
    facts = reader.get_run(StatusInput(dag_run_id=RUN))
    assert facts["tasks"][0]["duration"] == -55.828
    assert facts["tasks"][0]["negative_duration_reported"]
    assert not facts["run"]["negative_duration_reported"]
