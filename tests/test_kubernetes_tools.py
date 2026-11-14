"""No live cluster needed: scope, safe reads, failure and authorization boundaries."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
import yaml
from kubernetes import client

from mlops_agent.kubernetes_tools import (
    NAMESPACE,
    ClusterReader,
    KubernetesTools,
    LogsInput,
    PodInput,
    ScopeInput,
    pod_summary,
    restricted_client,
)

POD = "inference-5c65b94fc7-abcde"


@pytest.mark.parametrize(
    "duration", [float("nan"), float("inf"), -1, 10**400, True, None, "secret"]
)
def test_malformed_log_numeric_fields_do_not_discard_valid_entries(duration):
    core = Mock()
    core.read_namespaced_pod.return_value = pod()
    core.read_namespaced_pod_log.return_value = json.dumps(
        {
            "tool_name": "inference.readiness",
            "status": "ok",
            "duration_ms": duration,
            "http_status": 999,
        }
    )
    result = ClusterReader(core, Mock(), Mock()).logs(LogsInput(pod=POD))
    assert len(result["entries"]) == 1
    assert result["entries"][0]["duration_ms"] is None
    assert result["entries"][0]["http_status"] is None
    json.dumps(result, allow_nan=False)


def test_pod_with_absent_container_state_still_exposes_actual_readiness():
    observed = pod(False)
    observed.status.container_statuses[0].state = None
    summary = pod_summary(observed)
    assert summary["ready"] is False
    assert summary["containers"][0]["state"] is None
    assert summary["containers"][0]["restart_count"] == 0


def pod(ready=True, restarts=0, reason=None):
    return client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=POD,
            uid="pod-uid",
            labels={
                "app.kubernetes.io/name": "inference",
                "app.kubernetes.io/part-of": "mlops-assignment3",
            },
        ),
        status=client.V1PodStatus(
            phase="Running",
            conditions=[client.V1PodCondition(type="Ready", status="True" if ready else "False")],
            container_statuses=[
                client.V1ContainerStatus(
                    name="inference",
                    image="assignment:test",
                    image_id="sha256:real-image",
                    ready=ready,
                    restart_count=restarts,
                    state=client.V1ContainerState(
                        waiting=client.V1ContainerStateWaiting(reason=reason)
                    )
                    if reason
                    else client.V1ContainerState(running=client.V1ContainerStateRunning()),
                )
            ],
        ),
    )


def test_five_individually_callable_schemas_and_dispatch():
    transport = Mock(return_value={"observed": True})
    registry = KubernetesTools(transport=transport).registry
    assert len(registry.tools) == 5
    for name, definition in registry.tools.items():
        args = {"pod": POD} if name.endswith(("logs", "diagnostics")) else {}
        assert definition.schema()["parameters"]["additionalProperties"] is False
        result = registry.call(name, args, request_id="request-1")
        assert result.status == "ok" and result.evidence == {"observed": True}
        assert result.request_id == "request-1" and result.duration_ms >= 0
    assert transport.call_count == 5


@pytest.mark.parametrize(
    "args",
    [
        {"namespace": "default"},
        {"namespace": "kube-system"},
        {"context": "other"},
        {"action": "patch"},
        {"command": ["delete", "pods"]},
        {"namespace": None},
    ],
)
def test_invalid_scope_or_write_arguments_never_reach_transport(args):
    transport = Mock()
    result = KubernetesTools(transport=transport).registry.call("kubernetes_workloads", args)
    assert result.status == "invalid_request" and not result.evidence
    transport.assert_not_called()


@pytest.mark.parametrize("name", ["kubernetes_patch", "kubernetes_restart", "kubernetes_exec"])
@pytest.mark.parametrize(
    "confirmation",
    [None, {"action": "restart", "resource": "deployment/inference", "namespace": NAMESPACE}],
)
def test_mutations_unavailable_even_with_claimed_confirmation(name, confirmation):
    transport = Mock()
    result = KubernetesTools(transport=transport).registry.call(
        name,
        {
            "namespace": NAMESPACE,
            "confirmation": confirmation,
        },
    )
    assert result.status == "unavailable" and not result.evidence
    transport.assert_not_called()


@pytest.mark.parametrize(
    "args",
    [
        {"pod": "unrelated-12345-abcde"},
        {"pod": "../inference"},
        {"pod": POD, "tail_lines": 101},
        {"pod": POD, "follow": True},
        {"pod": POD, "container": "other"},
        {"pod": POD, "previous": "true"},
    ],
)
def test_invalid_log_requests_are_rejected(args):
    result = KubernetesTools(transport=Mock()).registry.call("kubernetes_logs", args)
    assert result.status == "invalid_request" and not result.evidence


def test_unhealthy_pod_and_restarts_reported_without_claiming_ready():
    summary = pod_summary(pod(False, 3, "CrashLoopBackOff"))
    assert summary["ready"] is False
    assert summary["containers"][0]["restart_count"] == 3
    assert summary["containers"][0]["reason"] == "CrashLoopBackOff"


def test_relevant_events_are_uid_scoped_and_arbitrary_message_omitted():
    core = Mock()
    core.read_namespaced_pod.return_value = pod(False)
    core.list_namespaced_event.return_value = NS(
        items=[
            client.CoreV1Event(
                metadata=client.V1ObjectMeta(),
                involved_object=client.V1ObjectReference(uid="pod-uid"),
                reason="Unhealthy",
                type="Warning",
                count=2,
                message="private-sentinel",
            )
        ],
        metadata=NS(_continue=None),
    )
    result = ClusterReader(core, Mock(), Mock()).diagnostics(PodInput(pod=POD))
    assert result["events"][0]["reason"] == "Unhealthy"
    assert "private-sentinel" not in str(result)
    assert (
        core.list_namespaced_event.call_args.kwargs["field_selector"]
        == "involvedObject.uid=pod-uid"
    )
    assert core.list_namespaced_event.call_args.args == (NAMESPACE,)


def test_logs_bounded_and_sanitized():
    core = Mock()
    core.read_namespaced_pod.return_value = pod()
    core.read_namespaced_pod_log.return_value = "\n".join(
        [
            "password=private-sentinel",
            json.dumps(
                {
                    "tool_name": "inference.readiness",
                    "status": "ok",
                    "http_status": 200,
                    "duration_ms": 1.2,
                    "request_id": "a" * 36,
                    "token": "private-sentinel",
                }
            ),
            json.dumps({"tool_name": "execute private-sentinel", "status": "ok"}),
        ]
    )
    result = ClusterReader(core, Mock(), Mock()).logs(LogsInput(pod=POD))
    assert len(result["entries"]) == 1 and "private-sentinel" not in str(result)
    options = core.read_namespaced_pod_log.call_args.kwargs
    assert options["follow"] is False and options["limit_bytes"] == 16384
    assert options["container"] == "inference" and options["tail_lines"] == 30


def test_correct_name_but_unowned_pod_rejected_before_logs():
    core = Mock()
    wrong = pod()
    wrong.metadata.labels = {}
    core.read_namespaced_pod.return_value = wrong
    registry = KubernetesTools(
        transport=lambda op, args: ClusterReader(core, Mock(), Mock()).logs(LogsInput(**args))
    ).registry
    assert registry.call("kubernetes_logs", {"pod": POD}).status == "invalid_request"
    core.read_namespaced_pod_log.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.TimeoutExpired("worker", 1),
        OSError("private-sentinel"),
    ],
)
def test_timeout_and_missing_worker_return_no_invented_facts(monkeypatch, failure):
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=failure))
    result = KubernetesTools(timeout=1).registry.call("kubernetes_workloads", {})
    assert result.status == "unavailable" and result.evidence == {}
    assert "private-sentinel" not in result.model_dump_json()


def test_denied_api_response_is_sanitized(monkeypatch):
    runner = Mock(return_value=NS(returncode=1, stdout="", stderr="token=private-sentinel"))
    monkeypatch.setattr(subprocess, "run", runner)
    result = KubernetesTools().registry.call("kubernetes_health", {})
    assert result.status == "unavailable" and not result.evidence
    assert "private-sentinel" not in result.model_dump_json()
    assert runner.call_args.kwargs["shell"] is False
    assert "OPENROUTER_API_KEY" not in runner.call_args.kwargs["env"]
    assert "HOME" not in runner.call_args.kwargs["env"]
    assert runner.call_args.kwargs["env"]["XDG_CACHE_HOME"].endswith("/.local/cache")
    assert runner.call_args.kwargs["timeout"] == 30


@pytest.mark.parametrize("output", ["not-json private-sentinel", "[]"])
def test_invalid_worker_output_is_not_evidence(monkeypatch, output):
    monkeypatch.setattr(subprocess, "run", Mock(return_value=NS(returncode=0, stdout=output)))
    result = KubernetesTools().registry.call("kubernetes_health", {})
    assert result.status == "error" and result.evidence == {}


def test_admin_or_exec_credential_is_refused_before_loading(tmp_path):
    path = tmp_path / "config"
    path.write_text(
        yaml.safe_dump(
            {
                "current-context": "kind-mlops-assignment3",
                "users": [{"name": "admin", "user": {"exec": {"command": "private-sentinel"}}}],
            }
        )
    )
    with pytest.raises(ValueError, match="restricted"):
        restricted_client(path)


def test_missing_restricted_credential_does_not_fallback_to_admin(tmp_path):
    result = KubernetesTools(tmp_path / "absent").registry.call("kubernetes_workloads", {})
    assert result.status == "unavailable" and not result.evidence


def test_namespace_argument_is_not_used_to_select_runtime_scope():
    core = Mock()
    core.list_namespaced_pod.return_value = NS(items=[], metadata=NS(_continue=None))
    apps = Mock()
    apps.list_namespaced_deployment.return_value = NS(items=[], metadata=NS(_continue=None))
    result = ClusterReader(core, apps, Mock()).workloads(ScopeInput())
    assert result["pods"] == [] and not result["truncated"]
    assert core.list_namespaced_pod.call_args.args == (NAMESPACE,)
    assert (
        core.list_namespaced_pod.call_args.kwargs["label_selector"]
        == "app.kubernetes.io/name=inference"
    )


def test_manifests_have_required_runtime_and_readonly_policy():
    root = Path(__file__).resolve().parents[1]
    documents = list(yaml.safe_load_all((root / "infra/kubernetes/application.yaml").read_text()))
    deployment = next(x for x in documents if x["kind"] == "Deployment")
    assert deployment["spec"]["replicas"] >= 2
    template = deployment["spec"]["template"]["spec"]
    container = template["containers"][0]
    assert not template["automountServiceAccountToken"]
    assert container["readinessProbe"]["httpGet"]["path"] == "/readyz"
    assert container["livenessProbe"]["httpGet"]["path"] == "/livez"
    assert set(container["resources"]) == {"requests", "limits"}
    assert any(x["kind"] == "ConfigMap" for x in documents)
    service = next(x for x in documents if x["kind"] == "Service")
    assert service["spec"]["type"] == "ClusterIP"
    rbac = list(yaml.safe_load_all((root / "infra/kubernetes/readonly.yaml").read_text()))
    role = next(x for x in rbac if x["kind"] == "Role")
    assert all(set(rule["verbs"]) <= {"get", "list"} for rule in role["rules"])
    assert all(
        "secrets" not in rule["resources"] and "pods/exec" not in rule["resources"]
        for rule in role["rules"]
    )
    assert all(d["metadata"]["namespace"] == NAMESPACE for d in documents + rbac)


def health_responses():
    from mlops_agent.model_bundle import ModelSelection

    model = ModelSelection(
        run_id="1" * 32,
        model_id="m-" + "2" * 32,
        model_sha256="3" * 64,
        training_code_revision="4" * 40,
        dataset={"path": "data/iris.csv", "git_revision": "5" * 40, "dvc_md5": "6" * 32},
        evaluation_id="7" * 64,
    ).model_dump(mode="json")
    return [
        {"status": "alive"},
        {"status": "ready", "model_run_id": model["run_id"]},
        {"app_version": "a" * 40, "model_ready": True, "model": model},
    ]


def test_service_proxy_reads_raw_bounded_json_and_checks_model_version():
    core = Mock()
    responses = [Mock() for _ in range(3)]
    for response, body in zip(responses, health_responses(), strict=True):
        response.read.return_value = json.dumps(body).encode()
    core.connect_get_namespaced_service_proxy_with_path.side_effect = responses
    result = ClusterReader(core, Mock(), Mock()).health(ScopeInput())
    assert result["app_version"] == "a" * 40
    assert result["model"]["run_id"] == "1" * 32
    calls = core.connect_get_namespaced_service_proxy_with_path.call_args_list
    assert [c.args for c in calls] == [
        ("inference:http", NAMESPACE, path) for path in ("livez", "readyz", "version")
    ]
    assert all(c.kwargs["_preload_content"] is False for c in calls)
    for response in responses:
        response.read.assert_called_once_with(65537)
        response.close.assert_called_once()
        response.release_conn.assert_called_once()


@pytest.mark.parametrize("failure", ["oversized", "mismatched_run", "unready", "bad_model"])
def test_invalid_service_health_never_becomes_ready_evidence(failure):
    core = Mock()
    bodies = health_responses()
    if failure == "mismatched_run":
        bodies[1]["model_run_id"] = "0" * 32
    if failure == "unready":
        bodies[2]["model_ready"] = False
    if failure == "bad_model":
        bodies[2]["model"]["run_id"] = "private-sentinel"
    responses = [Mock() for _ in range(3)]
    for response, body in zip(responses, bodies, strict=True):
        response.read.return_value = (
            b"x" * 65537 if failure == "oversized" else json.dumps(body).encode()
        )
    core.connect_get_namespaced_service_proxy_with_path.side_effect = responses
    registry = KubernetesTools(
        transport=lambda op, args: ClusterReader(core, Mock(), Mock()).health(ScopeInput(**args))
    ).registry
    result = registry.call("kubernetes_health", {})
    assert result.status in {"error", "invalid_request"} and result.evidence == {}
    assert "private-sentinel" not in result.model_dump_json()
