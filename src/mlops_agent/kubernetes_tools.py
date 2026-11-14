"""Bounded, namespace-scoped Kubernetes reads with no mutation/exec operation."""

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import Field

from mlops_agent.tools import ToolDefinition, ToolFailure, ToolInput, ToolRegistry

NAMESPACE = "mlops-agent"
CONTEXT = "kind-mlops-assignment3"
LABEL = "app.kubernetes.io/name=inference"


class ScopeInput(ToolInput):
    namespace: Literal["mlops-agent"] = NAMESPACE


class PodInput(ScopeInput):
    pod: str = Field(pattern=r"^inference-[a-z0-9]{1,10}-[a-z0-9]{5}$")


class LogsInput(PodInput):
    tail_lines: int = Field(default=30, ge=1, le=100)
    previous: bool = False


def conditions(items) -> list[dict]:
    # Omit arbitrary exception/message text and object annotations/env values.
    return [{"type": x.type, "status": x.status, "reason": x.reason} for x in (items or [])]


def pod_summary(pod) -> dict:
    containers = []
    for item in pod.status.container_statuses or []:
        state = item.state
        kind = next((k for k in ("waiting", "running", "terminated") if getattr(state, k)), None)
        detail = getattr(state, kind) if kind else None
        containers.append(
            {
                "name": item.name,
                "ready": item.ready,
                "restart_count": item.restart_count,
                "image": item.image,
                "image_id": item.image_id,
                "state": kind,
                "reason": getattr(detail, "reason", None),
                "exit_code": getattr(detail, "exit_code", None),
                "last_termination_reason": getattr(item.last_state.terminated, "reason", None)
                if item.last_state
                else None,
            }
        )
    ready = any(c.type == "Ready" and c.status == "True" for c in pod.status.conditions or [])
    return {
        "name": pod.metadata.name,
        "uid": pod.metadata.uid,
        "phase": pod.status.phase,
        "ready": ready,
        "deleting": pod.metadata.deletion_timestamp is not None,
        "conditions": conditions(pod.status.conditions),
        "containers": containers,
    }


class ClusterReader:
    def __init__(self, core, apps, discovery, timeout: float = 5):
        self.core, self.apps, self.discovery = core, apps, discovery
        self.options = {"_request_timeout": (min(3, timeout), timeout)}

    def workloads(self, args: ScopeInput) -> dict:
        pods = self.core.list_namespaced_pod(
            NAMESPACE, label_selector=LABEL, limit=100, **self.options
        )
        deployments = self.apps.list_namespaced_deployment(
            NAMESPACE, label_selector=LABEL, limit=100, **self.options
        )
        return {
            "namespace": NAMESPACE,
            "pods": [pod_summary(p) for p in pods.items],
            "deployments": [
                {
                    "name": d.metadata.name,
                    "generation": d.metadata.generation,
                    "observed_generation": d.status.observed_generation,
                    "desired_replicas": d.spec.replicas,
                    "ready_replicas": d.status.ready_replicas or 0,
                    "available_replicas": d.status.available_replicas or 0,
                    "updated_replicas": d.status.updated_replicas or 0,
                    "conditions": conditions(d.status.conditions),
                    "containers": [
                        {
                            "name": c.name,
                            "image": c.image,
                            "requests": c.resources.requests if c.resources else None,
                            "limits": c.resources.limits if c.resources else None,
                            "readiness_path": c.readiness_probe.http_get.path
                            if c.readiness_probe and c.readiness_probe.http_get
                            else None,
                            "liveness_path": c.liveness_probe.http_get.path
                            if c.liveness_probe and c.liveness_probe.http_get
                            else None,
                        }
                        for c in d.spec.template.spec.containers
                    ],
                }
                for d in deployments.items
            ],
            "truncated": bool(pods.metadata._continue or deployments.metadata._continue),
        }

    def services(self, args: ScopeInput) -> dict:
        services = self.core.list_namespaced_service(
            NAMESPACE, label_selector=LABEL, limit=100, **self.options
        )
        slices = self.discovery.list_namespaced_endpoint_slice(
            NAMESPACE,
            label_selector="kubernetes.io/service-name=inference",
            limit=100,
            **self.options,
        )
        return {
            "namespace": NAMESPACE,
            "services": [
                {
                    "name": s.metadata.name,
                    "type": s.spec.type,
                    "cluster_ip": s.spec.cluster_ip,
                    "selector": s.spec.selector,
                    "ports": [{"port": p.port, "target_port": p.target_port} for p in s.spec.ports],
                }
                for s in services.items
            ],
            "endpoints": [
                {
                    "addresses": e.addresses,
                    "ready": e.conditions.ready,
                    "pod": e.target_ref.name if e.target_ref else None,
                }
                for s in slices.items
                for e in s.endpoints
            ],
            "truncated": bool(services.metadata._continue or slices.metadata._continue),
        }

    def owned_pod(self, name):
        pod = self.core.read_namespaced_pod(name, NAMESPACE, **self.options)
        labels = pod.metadata.labels or {}
        if (
            labels.get("app.kubernetes.io/name") != "inference"
            or labels.get("app.kubernetes.io/part-of") != "mlops-assignment3"
        ):
            raise ValueError("Unapproved Pod")
        return pod

    def diagnostics(self, args: PodInput) -> dict:
        pod = self.owned_pod(args.pod)
        events = self.core.list_namespaced_event(
            NAMESPACE,
            field_selector=f"involvedObject.uid={pod.metadata.uid}",
            limit=100,
            **self.options,
        )
        return {
            "namespace": NAMESPACE,
            "pod": pod_summary(pod),
            "events": [
                {
                    "type": e.type,
                    "reason": e.reason,
                    "count": e.count,
                    "first_timestamp": str(e.first_timestamp) if e.first_timestamp else None,
                    "last_timestamp": str(e.last_timestamp) if e.last_timestamp else None,
                    "component": e.source.component if e.source else None,
                }
                for e in events.items
            ],
            "event_messages_omitted": "Arbitrary text excluded; reason/count are observations",
            "truncated": bool(events.metadata._continue),
        }

    def logs(self, args: LogsInput) -> dict:
        self.owned_pod(args.pod)
        raw = self.core.read_namespaced_pod_log(
            args.pod,
            NAMESPACE,
            container="inference",
            tail_lines=args.tail_lines,
            previous=args.previous,
            follow=False,
            limit_bytes=16384,
            **self.options,
        )
        # Only export the application's known structured fields. Raw logs may
        # contain credentials, injected instructions or arbitrary server text.
        entries = []
        for line in raw.splitlines():
            try:
                entry = json.loads(line)
                tool = entry.get("tool_name", "")
                if tool not in {
                    "inference.load_model",
                    "inference.liveness",
                    "inference.readiness",
                    "inference.version",
                    "inference.prediction",
                    "inference.unknown",
                }:
                    continue
                entries.append(
                    {
                        "tool_name": tool,
                        "status": entry["status"]
                        if entry.get("status") in {"ok", "error", "unavailable"}
                        else "unknown",
                        "http_status": entry.get("http_status")
                        if type(entry.get("http_status")) is int
                        else None,
                        "duration_ms": entry.get("duration_ms")
                        if type(entry.get("duration_ms")) in {int, float}
                        else None,
                        "request_id": entry.get("request_id")
                        if isinstance(entry.get("request_id"), str)
                        and re.fullmatch(
                            r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", entry["request_id"]
                        )
                        else None,
                    }
                )
            except (ValueError, AttributeError, TypeError):
                continue
        return {
            "namespace": NAMESPACE,
            "pod": args.pod,
            "previous": args.previous,
            "entries": entries,
            "bounded_tail": True,
            "raw_text_omitted": True,
            "untrusted_observations": True,
        }

    def health(self, args: ScopeInput) -> dict:
        responses = {}
        for path in ("livez", "readyz", "version"):
            # The generated SDK declares a string return and converts decoded
            # JSON dicts to Python repr. Read bounded HTTP bytes instead.
            response = self.core.connect_get_namespaced_service_proxy_with_path(
                "inference:http", NAMESPACE, path, _preload_content=False, **self.options
            )
            try:
                raw = response.read(65537)
                if len(raw) > 65536:
                    raise ValueError("Oversized health response")
                responses[path] = json.loads(raw)
            finally:
                response.close()
                response.release_conn()
        # Validate the public response rather than trusting arbitrary service text.
        version = responses["version"]
        from mlops_agent.model_bundle import ModelSelection

        model = ModelSelection.model_validate(version["model"]).model_dump(mode="json")
        app_sha = version["app_version"]
        if len(app_sha) != 40 or any(c not in "0123456789abcdef" for c in app_sha):
            raise ValueError("Invalid deployed version")
        if (
            responses["livez"] != {"status": "alive"}
            or responses["readyz"] != {"status": "ready", "model_run_id": model["run_id"]}
            or version["model_ready"] is not True
        ):
            raise ToolFailure("Inference health response inconsistent")
        return {
            "namespace": NAMESPACE,
            "service": "inference",
            "transport": "GET service proxy",
            "liveness": responses["livez"],
            "readiness": responses["readyz"],
            "app_version": app_sha,
            "model": model,
            "scope": "Service sampled one or more backends; use workloads for all replica states",
        }


OPERATIONS = {
    "workloads": ScopeInput,
    "services": ScopeInput,
    "diagnostics": PodInput,
    "logs": LogsInput,
    "health": ScopeInput,
}


class KubernetesTools:
    def __init__(
        self,
        kubeconfig: Path = Path(".local/kubeconfig-agent"),
        timeout: float = 30,
        transport: Callable[[str, dict], dict] | None = None,
    ):
        if not 1 <= timeout <= 120:
            raise ValueError("Timeout must be bounded")
        self.kubeconfig, self.timeout = kubeconfig.resolve(), timeout
        self.transport = transport or self._worker
        descriptions = {
            "workloads": "Read inference Pods, Deployments, conditions, images and restart counts",
            "services": "Read inference Service and ready EndpointSlice backends",
            "diagnostics": "Read one approved Pod's status and relevant event reasons/counts",
            "logs": "Read a bounded sanitized structured inference log tail",
            "health": "GET live health and deployed application/model/data version through Service",
        }
        self.registry = ToolRegistry(
            [
                ToolDefinition(
                    f"kubernetes_{operation}",
                    description,
                    OPERATIONS[operation],
                    lambda args, op=operation: self.transport(op, args.model_dump()),
                )
                for operation, description in descriptions.items()
            ]
        )

    def _worker(self, operation, args):
        root = Path(__file__).resolve().parents[2]
        try:
            result = subprocess.run(
                [sys.executable, "-m", "mlops_agent.kubernetes_tools", "--worker"],
                input=json.dumps(
                    {
                        "operation": operation,
                        "arguments": args,
                        "kubeconfig": str(self.kubeconfig),
                        "timeout": self.timeout,
                    }
                ),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=root,
                shell=False,
                env={
                    "PATH": os.defpath,
                    "PYTHONPATH": str(root / "src"),
                    "XDG_CACHE_HOME": str(root / ".local/cache"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )
        except subprocess.TimeoutExpired:
            raise ToolFailure("Kubernetes operation timed out", "unavailable") from None
        except OSError:
            raise ToolFailure("Kubernetes worker unavailable", "unavailable") from None
        if result.returncode:
            raise ToolFailure(
                "Kubernetes unavailable or access denied; no observations returned", "unavailable"
            )
        try:
            response = json.loads(result.stdout)
            if not isinstance(response, dict):
                raise ValueError
            return response
        except ValueError:
            raise ToolFailure("Invalid Kubernetes worker evidence") from None


def restricted_client(path: Path):
    """Accept only the generated token credential; never execute kubeconfig plugins."""
    import yaml
    from kubernetes import client, config

    document = yaml.safe_load(path.read_text())
    if (
        document["current-context"] != CONTEXT
        or len(document["users"]) != 1
        or document["users"][0]["name"] != "agent-reader"
        or set(document["users"][0]["user"]) != {"token"}
        or len(document["contexts"]) != 1
        or document["contexts"][0]["name"] != CONTEXT
        or document["contexts"][0]["context"]
        != {"cluster": "mlops-assignment3", "namespace": NAMESPACE, "user": "agent-reader"}
    ):
        raise ValueError("Only the restricted agent credential is accepted")
    configuration = client.Configuration()
    config.load_kube_config_from_dict(
        document, context=CONTEXT, client_configuration=configuration, persist_config=False
    )
    configuration.retries = 0
    return client.ApiClient(configuration)


def worker_main():
    from kubernetes import client

    try:
        request = json.load(sys.stdin)
        operation = request["operation"]
        args = OPERATIONS[operation].model_validate(request["arguments"])
        with restricted_client(Path(request["kubeconfig"])) as api:
            reader = ClusterReader(
                client.CoreV1Api(api),
                client.AppsV1Api(api),
                client.DiscoveryV1Api(api),
                min(5, request["timeout"]),
            )
            print(json.dumps(getattr(reader, operation)(args), allow_nan=False))
    except Exception:
        raise SystemExit(1) from None


if __name__ == "__main__" and sys.argv[1:] == ["--worker"]:
    worker_main()
