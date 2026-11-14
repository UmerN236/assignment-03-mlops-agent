import json
import logging
import subprocess
from unittest.mock import Mock

import pytest

from mlops_agent.dvc_tools import DvcTools

SHA = "a" * 40
MD5 = "b" * 32
RUN = "c" * 32
METADATA = f"outs:\n- path: iris.csv\n  hash: md5\n  md5: {MD5}\n  size: 2757\n"


@pytest.fixture
def adapter(tmp_path, monkeypatch):
    def respond(argv, **kwargs):
        if "rev-parse" in argv:
            output = SHA + "\n"
        elif "show" in argv:
            output = METADATA
        elif "list" in argv:
            output = '[{"path":"iris.csv", "isout":true}]'
        else:
            output = "{}"
        return subprocess.CompletedProcess(argv, 0, output, "")

    runner = Mock(side_effect=respond)
    monkeypatch.setattr(subprocess, "run", runner)
    return DvcTools(tmp_path), runner


def test_registered_tools_have_individual_input_and_output_schemas(adapter):
    tools, _ = adapter
    assert len(tools.registry.tools) >= 3
    for definition in tools.registry.tools.values():
        schema = definition.schema()
        assert schema["parameters"]["additionalProperties"] is False
        assert "status" in schema["output_schema"]["properties"]
    result = tools.registry.call("dvc_get_dataset_version", {})
    assert result.status == "ok"
    assert result.evidence["dataset_git_revision"] == SHA
    assert result.evidence["dataset_dvc_md5"] == MD5
    assert result.evidence["workspace_md5"] is None
    assert result.evidence["workspace_matches_revision"] is False


@pytest.mark.parametrize("revision", ["--help", "HEAD; touch x", "../main", "HEAD~1", "x" * 40])
def test_revision_injection_is_rejected_before_execution(adapter, revision):
    tools, runner = adapter
    result = tools.registry.call("dvc_get_dataset_version", {"revision": revision})
    assert result.status == "invalid_request"
    assert result.evidence == {}
    runner.assert_not_called()


@pytest.mark.parametrize("path", ["../.env", "/etc/passwd", "data/other.csv", "data/../.env"])
def test_unapproved_paths_are_rejected(adapter, path):
    tools, runner = adapter
    assert (
        tools.registry.call("dvc_get_data_status", {"dataset_path": path}).status
        == "invalid_request"
    )
    runner.assert_not_called()


def test_extra_command_and_repo_parameters_are_rejected(adapter):
    tools, runner = adapter
    assert tools.registry.call("dvc_list_datasets", {"command": "push"}).status == "invalid_request"
    assert tools.registry.call("dvc_list_datasets", {"root": "/tmp"}).status == "invalid_request"
    with pytest.raises(ValueError, match="allowlisted"):
        tools._run("checkout", "HEAD")
    runner.assert_not_called()


def test_symlink_escape_is_rejected_before_subprocess(adapter, tmp_path):
    tools, runner = adapter
    (tmp_path / "data").symlink_to(tmp_path.parent, target_is_directory=True)
    assert tools.registry.call("dvc_get_data_status", {}).status == "invalid_request"
    runner.assert_not_called()


def test_subprocess_uses_exact_allowlist_bounded_timeout_and_no_secrets(adapter, monkeypatch):
    tools, runner = adapter
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-marker")
    result = tools.registry.call("dvc_get_data_status", {})
    assert result.evidence["clean"] is True
    argv = runner.call_args.args[0]
    assert argv == [tools.dvc, "status", "--json", "data/iris.csv.dvc"]
    options = runner.call_args.kwargs
    assert options["shell"] is False
    assert 0 < options["timeout"] <= 120
    assert "OPENROUTER_API_KEY" not in options["env"]


@pytest.mark.parametrize("failure", ["timeout", "missing", "failed", "malformed"])
def test_service_failures_never_invent_evidence(adapter, failure):
    tools, runner = adapter
    if failure == "timeout":
        runner.side_effect = subprocess.TimeoutExpired("dvc", 30, stderr="secret-marker")
    elif failure == "missing":
        runner.side_effect = FileNotFoundError("secret-marker")
    elif failure == "failed":
        runner.side_effect = None
        runner.return_value = subprocess.CompletedProcess([], 1, "", "secret-marker")
    else:
        runner.side_effect = None
        runner.return_value = subprocess.CompletedProcess([], 0, "not json", "")
    result = tools.registry.call("dvc_get_data_status", {})
    assert result.status in {"unavailable", "error"}
    assert result.evidence == {}
    assert "secret-marker" not in result.model_dump_json()


def test_status_reports_modified_data_and_comparison_resolves_commits(adapter):
    tools, runner = adapter
    runner.side_effect = None
    runner.return_value = subprocess.CompletedProcess([], 0, '{"iris.csv": "modified"}', "")
    assert tools.registry.call("dvc_get_data_status", {}).evidence["clean"] is False
    runner.side_effect = [
        subprocess.CompletedProcess([], 0, SHA, ""),
        subprocess.CompletedProcess([], 0, "d" * 40, ""),
        subprocess.CompletedProcess([], 0, '{"modified": [{"path":"data/iris.csv"}]}', ""),
    ]
    result = tools.registry.call(
        "dvc_compare_versions", {"old_revision": SHA, "new_revision": "d" * 40}
    )
    assert result.status == "ok"
    assert result.evidence["new_is_workspace"] is False
    assert result.evidence["changes"]["modified"]


def test_mlflow_lineage_is_resolved_against_recorded_git_hash(adapter):
    tools, _ = adapter
    missing = tools.registry.call("dvc_resolve_mlflow_run", {"run_id": RUN})
    assert missing.status == "unavailable" and missing.evidence == {}
    tools.run_lookup = Mock(
        return_value={
            "dataset_path": "data/iris.csv",
            "dataset_git_revision": SHA,
            "dataset_dvc_md5": MD5,
        }
    )
    result = tools.registry.call("dvc_resolve_mlflow_run", {"run_id": RUN})
    tools.run_lookup.assert_called_once_with(RUN)
    assert result.evidence["run_record_verified"] is True
    assert result.evidence["reference_matches"] is True
    tools.run_lookup.return_value["dataset_dvc_md5"] = "f" * 32
    assert (
        tools.registry.call("dvc_resolve_mlflow_run", {"run_id": RUN}).evidence["reference_matches"]
        is False
    )
    tools.run_lookup.return_value = {}
    invalid = tools.registry.call("dvc_resolve_mlflow_run", {"run_id": RUN})
    assert invalid.status == "error" and invalid.evidence == {}


def test_supplied_lineage_does_not_claim_to_have_queried_mlflow(adapter):
    tools, _ = adapter
    result = tools.registry.call(
        "dvc_resolve_run_reference",
        {
            "run_id": RUN,
            "dataset_git_revision": SHA,
            "dataset_dvc_md5": MD5,
        },
    )
    assert result.evidence["reference_matches"]
    assert result.evidence["run_record_verified"] is False


def test_recovery_is_plan_only_and_tool_logs_are_sanitized(adapter, caplog):
    tools, runner = adapter
    with caplog.at_level(logging.INFO):
        result = tools.registry.call("dvc_explain_reproduction", {}, request_id="test-correlation")
    assert result.evidence["executes_checkout"] is False
    assert not any("checkout" in call.args[0] for call in runner.call_args_list)
    record = caplog.records[-1]
    assert record.tool == result.tool and record.status == "ok"
    assert record.request_id == "test-correlation" and record.duration_ms >= 0
    assert record.getMessage() == "tool_result"


def test_unknown_tool_and_malformed_metadata_are_not_operational_facts(adapter):
    tools, runner = adapter
    unknown = tools.registry.call("dvc_push", {})
    assert unknown.status == "unavailable" and unknown.evidence == {}
    runner.assert_not_called()
    runner.side_effect = [
        subprocess.CompletedProcess([], 0, SHA, ""),
        subprocess.CompletedProcess([], 0, json.dumps({"outs": [{"path": "../.env"}]}), ""),
    ]
    invalid = tools.registry.call("dvc_get_dataset_version", {})
    assert invalid.status == "error" and invalid.evidence == {}
