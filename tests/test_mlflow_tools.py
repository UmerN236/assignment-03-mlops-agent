import copy
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mlflow.entities import Experiment, FileInfo, Metric, Param, Run, RunData, RunInfo, RunTag

from mlops_agent.mlflow_tools import (
    ClientReader,
    ComparisonInput,
    MlflowTools,
    RegistryInput,
    RunInput,
    RunsInput,
    SelectionInput,
    rank_runs,
)
from mlops_agent.tools import ToolFailure


@pytest.mark.parametrize("operation", ["lineage", "details"])
def test_mismatched_run_cannot_supply_lineage_or_artifacts(operation):
    client = Mock()
    client.get_run.return_value = actual_entity(run_record(2))
    with pytest.raises(ToolFailure, match="identity"):
        getattr(ClientReader(client), operation)(RunInput(run_id=run_record(1)["run_id"]))
    client.list_artifacts.assert_not_called()
    client.get_logged_model.assert_not_called()


@pytest.mark.parametrize("field", ["model_id", "source_run_id"])
def test_mismatched_logged_model_cannot_be_attached_to_run(field):
    client = Mock()
    record = run_record()
    client.get_run.return_value = actual_entity(record)
    client.list_artifacts.return_value = []
    model = {
        "model_id": record["model_id"],
        "source_run_id": record["run_id"],
        "model_uri": "models:/" + record["model_id"],
    }
    model[field] = "m-" + "b" * 32 if field == "model_id" else "b" * 32
    client.get_logged_model.return_value = SimpleNamespace(**model)
    with pytest.raises(ToolFailure, match="identity"):
        ClientReader(client).details(RunInput(run_id=record["run_id"]))
    client.list_logged_model_artifacts.assert_not_called()


def run_record(number=1, f1=0.8, loss=0.2):
    return {
        "run_id": f"{number:032x}",
        "experiment_id": str(number % 2 + 1),
        "status": "FINISHED",
        "start_time_ms": number,
        "end_time_ms": number + 1,
        "metrics": {"f1_macro": f1, "log_loss": loss},
        "model_id": "m-" + "a" * 32,
        "parameters": {
            "dataset_path": "data/iris.csv",
            "dataset_git_revision": "a" * 40,
            "code_git_revision": "b" * 40,
            "dataset_dvc_md5": "c" * 32,
            "split_seed": "42",
            "split_sha256": "d" * 64,
            "evaluation_id": "e" * 64,
            "evaluation_policy": "test-policy",
        },
    }


def actual_entity(record):
    return Run(
        RunInfo(
            record["run_id"],
            record["experiment_id"],
            "test",
            record["status"],
            record["start_time_ms"],
            record["end_time_ms"],
            "active",
        ),
        RunData(
            metrics=[Metric(k, v, 0, 0) for k, v in record["metrics"].items()],
            params=[Param(k, v) for k, v in record["parameters"].items()],
            tags=[RunTag("assignment.model_id", record["model_id"])] if record["model_id"] else [],
        ),
    )


def test_metric_direction_and_deterministic_tie_breaking():
    records = [run_record(1, 0.95, 0.3), run_record(2, 0.85, 0.1), run_record(3, 0.95, 0.2)]
    best = rank_runs(records, SelectionInput(experiment_ids=["1"], direction="maximize"))
    assert best["selected_run"]["run_id"] == records[2]["run_id"]
    minimum = rank_runs(
        records, SelectionInput(experiment_ids=["1"], metric="log_loss", direction="minimize")
    )
    assert minimum["selected_run"]["run_id"] == records[1]["run_id"]
    assert any("production" in caveat for caveat in best["caveats"])


@pytest.mark.parametrize(
    "field", ["evaluation_id", "dataset_dvc_md5", "split_sha256", "evaluation_policy"]
)
def test_incompatible_evaluation_never_returns_a_global_winner(field):
    first, second = run_record(), run_record(2, 0.99)
    second["parameters"][field] = "different"
    evidence = rank_runs(
        [first, second], SelectionInput(experiment_ids=["1"], direction="maximize")
    )
    assert not evidence["comparable"] and evidence["selected_run"] is None
    assert evidence["ranking"] == []


def test_requested_cohort_and_ineligible_runs_are_explained():
    records = [run_record(n) for n in range(1, 6)]
    records[1]["status"] = "FAILED"
    records[2]["metrics"]["f1_macro"] = float("nan")
    del records[3]["parameters"]["dataset_dvc_md5"]
    records[4]["parameters"]["evaluation_id"] = "f" * 64
    evidence = rank_runs(
        records, SelectionInput(experiment_ids=["1"], direction="maximize", evaluation_id="e" * 64)
    )
    assert evidence["selected_run"]["run_id"] == records[0]["run_id"]
    assert {item["reason"] for item in evidence["excluded"]} == {
        "run_not_finished",
        "missing_or_nonfinite_metric",
        "missing_evaluation_lineage",
        "different_requested_evaluation",
    }
    assert (
        rank_runs([], SelectionInput(experiment_ids=["1"], direction="maximize"))["selected_run"]
        is None
    )


def test_unlogged_model_is_not_an_eligible_candidate():
    record = run_record()
    record["model_id"] = None
    evidence = rank_runs([record], SelectionInput(experiment_ids=["1"], direction="maximize"))
    assert evidence["selected_run"] is None
    assert evidence["excluded"][0]["reason"] == "missing_model_reference"


def test_supported_client_queries_and_artifact_model_metadata():
    client = Mock()
    record = run_record()
    client.get_run.return_value = actual_entity(record)
    client.list_artifacts.return_value = [FileInfo("evaluation.json", False, 100)]
    client.get_logged_model.return_value = SimpleNamespace(
        model_id=record["model_id"],
        model_uri=f"models:/{record['model_id']}",
        source_run_id=record["run_id"],
    )
    client.list_logged_model_artifacts.return_value = [FileInfo("model.pkl", False, 200)]
    reader = ClientReader(client)
    details = reader.details(RunInput(run_id=record["run_id"]))
    assert details["metrics"] == record["metrics"]
    assert details["artifacts"][0]["path"] == "evaluation.json"
    assert details["logged_model"]["artifacts"][0]["path"] == "model.pkl"
    client.search_runs.return_value = [actual_entity(record)]
    runs = reader.runs(RunsInput(experiment_ids=["1"], limit=5))
    assert len(runs["runs"]) == 1 and not runs["has_more"]
    query = client.search_runs.call_args.kwargs
    assert query["max_results"] == 5 and query["order_by"] == ["attributes.start_time DESC"]
    assert (
        "assignment.training" in query["filter_string"]
        and "start_time >=" in query["filter_string"]
    )


def test_two_experiments_and_absent_registry_are_honest():
    client = Mock()
    client.search_runs.return_value = [actual_entity(run_record(n)) for n in range(1, 6)]
    reader = ClientReader(client)
    comparison = reader.comparison(ComparisonInput(experiment_ids=["1", "2"], direction="maximize"))
    assert sum(item["recent_run_count"] for item in comparison["experiments"]) == 5
    client.search_model_versions.return_value = []
    result = reader.registry(RegistryInput())
    assert result["versions"] == [] and "No versions" in result["note"]


@pytest.mark.parametrize(
    "name,args",
    [
        ("mlflow_list_runs", {"experiment_ids": ["1 OR secret"], "limit": 5}),
        ("mlflow_get_run", {"run_id": "../../.env"}),
        ("mlflow_select_best", {"experiment_ids": ["1"], "direction": "sideways"}),
        ("mlflow_select_best", {"experiment_ids": ["1"], "direction": "maximize", "limit": 1000}),
        ("mlflow_compare_experiments", {"experiment_ids": ["1", "1"], "direction": "maximize"}),
        ("mlflow_model_versions", {"model_name": "unrelated"}),
    ],
)
def test_invalid_requests_never_reach_client(name, args):
    transport = Mock()
    result = MlflowTools("http://127.0.0.1:5000", transport=transport).registry.call(name, args)
    assert result.status == "invalid_request"
    transport.assert_not_called()


@pytest.mark.parametrize("failure", ["timeout", "exit", "oserror", "invalid_json"])
def test_worker_failures_return_no_invented_facts_or_secrets(monkeypatch, caplog, failure):
    def execute(*args, **kwargs):
        assert kwargs["timeout"] == 3
        assert kwargs["shell"] is False
        assert "OPENROUTER_API_KEY" not in kwargs["env"]
        assert kwargs["env"]["MLFLOW_HTTP_REQUEST_MAX_RETRIES"] == "0"
        if failure == "timeout":
            raise subprocess.TimeoutExpired("secret", 3)
        if failure == "oserror":
            raise OSError("secret")
        return SimpleNamespace(
            returncode=1 if failure == "exit" else 0, stdout="secret", stderr="secret"
        )

    monkeypatch.setattr("mlops_agent.mlflow_tools.subprocess.run", execute)
    with caplog.at_level("INFO"):
        result = MlflowTools("http://127.0.0.1:5000", timeout=3).registry.call(
            "mlflow_list_experiments", {}, request_id="test-request"
        )
    assert result.status in {"unavailable", "error"} and result.evidence == {}
    assert "secret" not in result.model_dump_json() + caplog.text
    assert caplog.records[-1].request_id == "test-request"
    assert caplog.records[-1].duration_ms >= 0


def test_all_seven_registered_calls_validate_and_use_their_operation():
    calls = []

    def transport(operation, args):
        calls.append(operation)
        return {"observed": True}

    registry = MlflowTools("http://127.0.0.1:5000", transport=transport).registry
    args = {
        "mlflow_list_experiments": {},
        "mlflow_list_runs": {"experiment_ids": ["1"]},
        "mlflow_get_run": {"run_id": "a" * 32},
        "mlflow_select_best": {"experiment_ids": ["1"], "direction": "maximize"},
        "mlflow_compare_runs": {"experiment_ids": ["1"], "direction": "minimize"},
        "mlflow_compare_experiments": {"experiment_ids": ["1", "2"], "direction": "maximize"},
        "mlflow_model_versions": {},
    }
    for name, arguments in args.items():
        assert registry.call(name, arguments).status == "ok"
        assert registry.tools[name].schema()["output_schema"]
    assert calls == [
        "experiments",
        "runs",
        "details",
        "selection",
        "selection",
        "comparison",
        "registry",
    ]


def test_bounded_worker_success_and_dvc_lookup(monkeypatch):
    response = {"parameters": run_record()["parameters"]}
    monkeypatch.setattr(
        "mlops_agent.mlflow_tools.subprocess.run",
        lambda *args, **kw: SimpleNamespace(returncode=0, stdout=json.dumps(response)),
    )
    tools = MlflowTools("http://127.0.0.1:5000")
    assert tools.run_params("a" * 32) == response["parameters"]


def test_dvc_run_lookup_does_not_depend_on_model_artifact_storage():
    client = Mock()
    client.get_run.return_value = actual_entity(run_record())
    client.list_artifacts.side_effect = RuntimeError("storage unavailable")
    reader = ClientReader(client)

    def transport(op, args):
        return getattr(reader, op)(RunInput.model_validate(args))

    tools = MlflowTools("http://127.0.0.1:5000", transport=transport)
    assert tools.run_params(run_record()["run_id"])["dataset_dvc_md5"] == "c" * 32
    client.list_artifacts.assert_not_called()
    client.list_logged_model_artifacts.assert_not_called()


def test_experiment_listing_uses_supported_client_and_exposes_pagination():
    class Page(list):
        token = "next-page"

    client = Mock()
    client.search_experiments.return_value = Page(
        [Experiment("1", "assignment-iris", "mlflow-artifacts:/1", "active")]
    )
    reader = ClientReader(client)
    from mlops_agent.mlflow_tools import ExperimentsInput

    result = reader.experiments(ExperimentsInput())
    assert result["has_more"] and result["experiments"][0]["experiment_id"] == "1"


def test_registry_present_and_missing_model_metadata():
    client = Mock()
    record = copy.deepcopy(run_record())
    record["model_id"] = None
    client.get_run.return_value = actual_entity(record)
    client.list_artifacts.return_value = []
    assert ClientReader(client).details(RunInput(run_id=record["run_id"]))["logged_model"] is None
    client.search_model_versions.return_value = [
        SimpleNamespace(
            version="1",
            run_id=record["run_id"],
            status="READY",
            source="models:/m-example",
            aliases=[],
        )
    ]
    assert ClientReader(client).registry(RegistryInput())["versions"][0]["status"] == "READY"


def test_worker_artifact_resolution_uses_configured_fluent_uri(monkeypatch, capsys):
    """Regression: MLflow 3.6 artifact factories also consult fluent configuration."""
    import io
    import sys

    import mlflow

    from mlops_agent.mlflow_tools import worker_main

    original_tracking, original_registry = mlflow.get_tracking_uri(), mlflow.get_registry_uri()
    uri = "http://127.0.0.1:5011"
    client = Mock()
    client.get_run.return_value = actual_entity(run_record())
    client.list_artifacts.return_value = []
    client.get_logged_model.return_value = SimpleNamespace(
        model_id=run_record()["model_id"],
        model_uri="models:/" + run_record()["model_id"],
        source_run_id=run_record()["run_id"],
    )

    def artifacts(*args):
        assert mlflow.get_tracking_uri() == uri
        assert mlflow.get_registry_uri() == uri
        return [FileInfo("model.pkl", False, 100)]

    client.list_logged_model_artifacts.side_effect = artifacts
    monkeypatch.setattr(mlflow, "MlflowClient", lambda **kwargs: client)
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "uri": uri,
                    "operation": "details",
                    "arguments": {"run_id": run_record()["run_id"]},
                }
            )
        ),
    )
    try:
        worker_main()
        result = json.loads(capsys.readouterr().out)
        assert result["logged_model"]["artifacts"][0]["path"] == "model.pkl"
    finally:
        mlflow.set_tracking_uri(original_tracking)
        mlflow.set_registry_uri(original_registry)
