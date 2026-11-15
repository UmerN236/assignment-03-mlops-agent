"""Actual cluster observations and routing, without altering any cluster resource."""

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from mlops_agent.kubernetes_tools import KubernetesTools
from mlops_agent.model_bundle import FEATURES, load_bundle, read_manifest
from mlops_agent.training import TrainingConfig, evaluate_classifier, prepare_split

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = "mlops-agent"
BASE = [
    str(ROOT / ".local/bin/kubectl"),
    "--context",
    "kind-mlops-assignment3",
    "--cache-dir",
    str(ROOT / ".local/cache/kubectl"),
    "--request-timeout=15s",
]
ADMIN = [*BASE, "--kubeconfig", str(ROOT / ".local/kubeconfig")]
READER = [*BASE, "--kubeconfig", str(ROOT / ".local/kubeconfig-agent")]


def command(args, *, data=None, timeout=30):
    return subprocess.run(
        args, input=data, capture_output=True, text=True, timeout=timeout, cwd=ROOT
    )


def main():
    tools = KubernetesTools(ROOT / ".local/kubeconfig-agent")
    results = []

    def call(name, args=None):
        result = tools.registry.call("kubernetes_" + name, args or {})
        assert result.status == "ok", f"Live tool {name} did not return observations"
        results.append(result.model_dump(mode="json"))
        return result.evidence

    workloads = call("workloads")
    assert not workloads["truncated"]
    (deployment,) = workloads["deployments"]
    assert deployment["name"] == "inference"
    assert deployment["generation"] == deployment["observed_generation"]
    assert deployment["desired_replicas"] == deployment["ready_replicas"] == 2
    assert deployment["available_replicas"] == deployment["updated_replicas"] == 2
    assert len(workloads["pods"]) == 2 and all(p["ready"] for p in workloads["pods"])
    services = call("services")
    assert not services["truncated"]
    (service,) = services["services"]
    assert service["type"] == "ClusterIP"
    endpoints = services["endpoints"]
    assert len(endpoints) == 2 and all(e["ready"] for e in endpoints)
    assert {e["pod"] for e in endpoints} == {p["name"] for p in workloads["pods"]}
    health = call("health")
    manifest = read_manifest(ROOT / "artifacts/inference")
    assert health["model"] == manifest.selection.model_dump(mode="json")
    content = (ROOT / "data/iris.csv").read_bytes()
    assert (
        hashlib.md5(content, usedforsecurity=False).hexdigest()
        == manifest.selection.dataset.dvc_md5
    )
    split = prepare_split(content, TrainingConfig())
    assert split.evaluation_id == manifest.selection.evaluation_id
    _, expected = evaluate_classifier(load_bundle(ROOT / "artifacts/inference", manifest), split)
    instances = [
        dict(zip(FEATURES, row.tolist(), strict=True)) for row in split.features[split.test_indices]
    ]
    targets = [
        {"name": "service-dns", "url": "http://inference.mlops-agent.svc.cluster.local:8000"},
        {"name": "service-cluster-ip", "url": f"http://{service['cluster_ip']}:8000"},
        *[{"name": e["pod"], "url": f"http://{e['addresses'][0]}:8000"} for e in endpoints],
    ]
    # Engineer-only exec in an already inspected assignment Pod. Agent RBAC
    # cannot exec. Exercise real DNS/kube-proxy routing and each replica directly.
    remote_code = """
import json,sys,urllib.request,urllib.error
request=json.load(sys.stdin)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
observations=[]
for target in request['targets']:
    def get(path):
        with opener.open(target['url']+path,timeout=8) as r:
            return {'status':r.status,'body':json.load(r)}
    version=get('/version')
    live=get('/livez')
    ready=get('/readyz')
    body=json.dumps({'instances':request['instances']}).encode()
    req=urllib.request.Request(target['url']+'/predict',data=body,
                               headers={'Content-Type':'application/json'})
    with opener.open(req,timeout=8) as r:
        prediction={'status':r.status,'body':json.load(r)}
    invalid=urllib.request.Request(target['url']+'/predict',data=b'{"instances":[]}',
                                   headers={'Content-Type':'application/json'})
    try:
        opener.open(invalid,timeout=8)
        raise AssertionError('Invalid input was accepted')
    except urllib.error.HTTPError as e:
        invalid_status=e.code
    observations.append({'target':target,'version':version,'livez':live,'readyz':ready,
                         'prediction':prediction,'invalid_status':invalid_status})
print(json.dumps(observations))
"""
    executed = command(
        [
            *ADMIN,
            "-n",
            NAMESPACE,
            "exec",
            "-i",
            workloads["pods"][0]["name"],
            "-c",
            "inference",
            "--",
            "python",
            "-c",
            remote_code,
        ],
        data=json.dumps({"targets": targets, "instances": instances}),
        timeout=90,
    )
    assert executed.returncode == 0, "In-cluster routing verification failed"
    routed = json.loads(executed.stdout)
    compact = []
    for observation in routed:
        assert observation["version"]["body"]["model"] == health["model"]
        assert observation["version"]["body"]["app_version"] == health["app_version"]
        assert observation["livez"]["status"] == observation["readyz"]["status"] == 200
        assert observation["prediction"]["status"] == 200 and observation["invalid_status"] == 422
        predictions = observation["prediction"]["body"]["predictions"]
        assert [p["class_id"] for p in predictions] == expected["predicted"]
        for p, scores in zip(predictions, expected["probabilities"], strict=True):
            assert all(abs(a - b) < 1e-12 for a, b in zip(p["probabilities"], scores, strict=True))
        compact.append(
            {
                "target": observation["target"],
                "version": observation["version"],
                "livez": observation["livez"],
                "readyz": observation["readyz"],
                "prediction_status": observation["prediction"]["status"],
                "matched_holdout_predictions": len(predictions),
                "probability_tolerance": 1e-12,
                "invalid_input_status": observation["invalid_status"],
            }
        )
    for pod in workloads["pods"]:
        call("diagnostics", {"pod": pod["name"]})
        logs = call("logs", {"pod": pod["name"], "tail_lines": 12})
        assert logs["entries"], "No actual structured Pod logs observed"
    rbac = []
    for verb, resource, namespace, allowed in [
        ("list", "pods", NAMESPACE, True),
        ("get", "pods/log", NAMESPACE, True),
        ("list", "deployments.apps", NAMESPACE, True),
        ("list", "pods", "default", False),
        ("get", "secrets", NAMESPACE, False),
        ("patch", "deployments.apps", NAMESPACE, False),
        ("delete", "pods", NAMESPACE, False),
        ("create", "pods/exec", NAMESPACE, False),
        ("create", "services/proxy", NAMESPACE, False),
        ("get", "nodes", NAMESPACE, False),
    ]:
        response = command([*READER, "-n", namespace, "auth", "can-i", verb, resource])
        answer = response.stdout.strip()
        assert answer == ("yes" if allowed else "no")
        rbac.append(
            {"verb": verb, "resource": resource, "namespace": namespace, "allowed": answer == "yes"}
        )
    # Direct server authorization check is dry-run as an additional safeguard.
    denied = command(
        [
            *READER,
            "-n",
            NAMESPACE,
            "patch",
            "deployment",
            "inference",
            "--type=merge",
            "--dry-run=server",
            "-p",
            '{"spec":{"replicas":3}}',
        ]
    )
    assert denied.returncode != 0 and "Forbidden" in denied.stderr
    invalid_scope = tools.registry.call("kubernetes_workloads", {"namespace": "default"})
    unauthorized = tools.registry.call(
        "kubernetes_patch",
        {
            "namespace": NAMESPACE,
            "resource": "deployment/inference",
            "replicas": 3,
        },
    )
    assert invalid_scope.status == "invalid_request" and not invalid_scope.evidence
    assert unauthorized.status == "unavailable" and not unauthorized.evidence
    call("workloads")  # Confirm denied action left desired and ready replicas at two.
    final = results[-1]["evidence"]["deployments"][0]
    assert final["desired_replicas"] == final["ready_replicas"] == 2
    export = {
        "observed_at": datetime.now(UTC).isoformat(),
        "cluster": "mlops-assignment3",
        "namespace": NAMESPACE,
        "tools": results,
        "in_cluster_routing": compact,
        "rbac": rbac,
        "server_dry_run_patch_denied": True,
        "invalid_scope": invalid_scope.model_dump(mode="json"),
        "unauthorized_write": unauthorized.model_dump(mode="json"),
        "limitations": [
            "Single-node local kind deployment; two replicas do not provide node redundancy.",
            "Only bounded log tails/event reasons exported; missing history remains unknown.",
            "Read-only tools provide no cluster mutation even with claimed confirmation.",
            "Expiring TokenRequest credential must be refreshed by an engineer after expiry.",
            "Direct tool export; conversations and failure investigations are separate exports.",
        ],
    }
    output = ROOT / "docs/evidence/kubernetes-live.json"
    output.write_text(json.dumps(export, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": "passed",
                "ready_replicas": final["ready_replicas"],
                "routed_targets": len(compact),
                "predictions_per_target": len(instances),
                "tool_observations": len(results),
                "rbac_checks": len(rbac),
            }
        )
    )


if __name__ == "__main__":
    main()
