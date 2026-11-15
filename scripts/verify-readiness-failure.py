"""Bounded engineer-authorized readiness failure, read-only diagnosis, recovery.

This is not an agent mutation tool. It touches only the labeled assignment
Deployment and restores its original strategy and probe even when diagnosis fails.
"""

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from mlops_agent.agent import Agent, ChatRequest, configure_logging
from mlops_agent.config import load_settings
from mlops_agent.kubernetes_tools import KubernetesTools

ROOT = Path(__file__).resolve().parents[1]
BASE = [
    str(ROOT / ".local/bin/kubectl"),
    "--kubeconfig",
    str(ROOT / ".local/kubeconfig"),
    "--context",
    "kind-mlops-assignment3",
    "-n",
    "mlops-agent",
    "--request-timeout=15s",
]


def command(arguments, timeout=30):
    result = subprocess.run(BASE + arguments, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Assignment readiness exercise command failed")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm", required=True, choices=["inject readiness failure in mlops-agent"]
    )
    args = parser.parse_args()
    assert args.confirm
    original = json.loads(command(["get", "deployment", "inference", "-o", "json"]))
    assert original["metadata"]["labels"]["app.kubernetes.io/part-of"] == "mlops-assignment3"
    assert original["spec"]["replicas"] == original["status"]["readyReplicas"] == 2
    container = original["spec"]["template"]["spec"]["containers"][0]
    restore = {
        "spec": {
            "strategy": original["spec"]["strategy"],
            "template": {
                "spec": {
                    "containers": [
                        {"name": "inference", "readinessProbe": container["readinessProbe"]}
                    ]
                }
            },
        }
    }
    failed_patch = {
        "spec": {
            "strategy": {"type": "Recreate", "rollingUpdate": None},
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "inference",
                            "readinessProbe": {
                                "httpGet": {"path": "/injected-readiness-failure", "port": "http"}
                            },
                        }
                    ]
                }
            },
        }
    }
    tools = KubernetesTools(load_settings().kubernetes_readonly_kubeconfig)
    export = {
        "observed_at": datetime.now(UTC).isoformat(),
        "namespace": "mlops-agent",
        "engineering_confirmation": args.confirm,
        "before": [],
        "during": [],
        "after": [],
    }

    def observe(phase, name, arguments=None):
        result = tools.registry.call("kubernetes_" + name, arguments or {})
        export[phase].append(result.model_dump(mode="json"))
        return result

    observe("before", "workloads")
    observe("before", "health")
    try:
        command(
            ["patch", "deployment", "inference", "--type=strategic", "-p", json.dumps(failed_patch)]
        )
        deadline = time.monotonic() + 100
        while time.monotonic() < deadline:
            pods = json.loads(
                command(["get", "pods", "-l", "app.kubernetes.io/name=inference", "-o", "json"])
            )["items"]
            active = [p for p in pods if not p["metadata"].get("deletionTimestamp")]
            if len(active) == 2 and all(
                p["status"].get("phase") == "Running"
                and not any(
                    c["type"] == "Ready" and c["status"] == "True"
                    for c in p["status"].get("conditions", [])
                )
                for p in active
            ):
                break
            time.sleep(2)
        else:
            raise RuntimeError("Controlled unready state did not occur within deadline")
        time.sleep(8)  # Allow the failed probe and EndpointSlice controller to observe the state.
        observe("during", "workloads")
        services = observe("during", "services")
        assert services.status == "ok"
        assert not any(e["ready"] for e in services.evidence["endpoints"])
        observe("during", "health")  # Unavailable is the expected truthful observation.
        for pod in active:
            observe("during", "diagnostics", {"pod": pod["metadata"]["name"]})
            observe("during", "logs", {"pod": pod["metadata"]["name"], "tail_lines": 30})
        request = ChatRequest(
            message=(
                "Diagnose why inference has no ready backends. Inspect workload readiness probes, "
                "Service endpoint readiness, Pod events and logs. Cite the probe paths and "
                "failed status. Do not repeat successful calls; submit_answer after the evidence. "
                "For submit_answer cite whole successful evidence objects using pointer empty "
                "string and their returned result_index; avoid speculative subfield pointers. "
                "Use only investigate_unavailable_services as a recommendation code. "
                "Do not mutate the cluster or infer model degradation from a readiness failure."
            )
        )
        result = Agent(load_settings()).run(request)
        export["agent_request"] = request.model_dump(mode="json")
        export["agent_diagnosis"] = result.model_dump(mode="json")
    finally:
        command(["patch", "deployment", "inference", "--type=strategic", "-p", json.dumps(restore)])
        command(["rollout", "status", "deployment/inference", "--timeout=180s"], timeout=195)
        workloads = observe("after", "workloads")
        health = observe("after", "health")
        export["recovered"] = (
            workloads.status == health.status == "ok"
            and workloads.evidence["deployments"][0]["ready_replicas"] == 2
        )
        path = ROOT / "docs/evidence/readiness-failure-live.json"
        path.write_text(json.dumps(export, indent=2) + "\n")
        print(
            json.dumps({"recovered": export["recovered"], "evidence": str(path.relative_to(ROOT))})
        )
    assert export["recovered"]


if __name__ == "__main__":
    configure_logging()
    main()
