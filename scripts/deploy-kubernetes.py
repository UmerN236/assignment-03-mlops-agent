#!/usr/bin/env python3
"""Engineer-only setup for the named assignment cluster; never an agent tool."""

import json
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = "kind-mlops-assignment3"
NAMESPACE = "mlops-agent"
ADMIN = [
    str(ROOT / ".local/bin/kubectl"),
    "--kubeconfig",
    str(ROOT / ".local/kubeconfig"),
    "--context",
    CONTEXT,
    "--cache-dir",
    str(ROOT / ".local/cache/kubectl"),
    "--request-timeout=15s",
]


def run(args, timeout=60):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise SystemExit("Assignment setup command failed; inspect target/configuration locally")
    return result.stdout


def main():
    namespace = json.loads(run([*ADMIN, "get", "namespace", NAMESPACE, "-o", "json"]))
    assert namespace["metadata"]["labels"]["app.kubernetes.io/part-of"] == "mlops-assignment3"
    manifests = [
        ROOT / "infra/kubernetes/application.yaml",
        ROOT / "infra/kubernetes/readonly.yaml",
    ]
    allowed = {
        ("ConfigMap", "inference-config"),
        ("ServiceAccount", "inference"),
        ("Deployment", "inference"),
        ("Service", "inference"),
        ("ServiceAccount", "agent-reader"),
        ("Role", "agent-reader"),
        ("RoleBinding", "agent-reader"),
    }
    for path in manifests:
        for doc in yaml.safe_load_all(path.read_text()):
            meta = doc["metadata"]
            assert meta["namespace"] == NAMESPACE and (doc["kind"], meta["name"]) in allowed
            existing = run(
                [
                    *ADMIN,
                    "-n",
                    NAMESPACE,
                    "get",
                    doc["kind"],
                    meta["name"],
                    "--ignore-not-found",
                    "-o",
                    "json",
                ]
            )
            if existing.strip():
                obj = json.loads(existing)
                assert (
                    obj["metadata"].get("labels", {}).get("app.kubernetes.io/part-of")
                    == "mlops-assignment3"
                ), "Refusing to replace an unowned resource"
    image = "mlops-assignment3-inference:c20e0106c52d"
    inspected = json.loads(run(["docker", "image", "inspect", image]))[0]
    evidence = json.loads((ROOT / "docs/evidence/inference-live.json").read_text())
    # Exact image identity established by the previous milestone, not a mutable latest tag.
    assert image == evidence["image_tag"] and inspected["Id"] == evidence["image_id"]
    nodes = run([str(ROOT / ".local/bin/kind"), "get", "nodes", "--name", "mlops-assignment3"])
    assert nodes.split() == ["mlops-assignment3-control-plane"]
    node = json.loads(run(["docker", "inspect", nodes.strip()]))[0]
    assert node["Config"]["Labels"]["io.x-k8s.kind.cluster"] == "mlops-assignment3"
    run(
        [
            str(ROOT / ".local/bin/kind"),
            "load",
            "docker-image",
            image,
            "--name",
            "mlops-assignment3",
        ],
        timeout=180,
    )
    for path in manifests:
        print(run([*ADMIN, "-n", NAMESPACE, "apply", "-f", str(path)]).strip())
    print(
        run(
            [
                *ADMIN,
                "-n",
                NAMESPACE,
                "rollout",
                "status",
                "deployment/inference",
                "--timeout=180s",
            ],
            timeout=195,
        ).strip()
    )
    # TokenRequest issues an expiring credential. Never print its response/token.
    token_request = json.loads(
        run(
            [
                *ADMIN,
                "-n",
                NAMESPACE,
                "create",
                "token",
                "agent-reader",
                "--duration=24h",
                "-o",
                "json",
            ]
        )
    )
    admin = json.loads(run([*ADMIN, "config", "view", "--minify", "--raw", "-o", "json"]))
    cluster = admin["clusters"][0]["cluster"]
    restricted = {
        "apiVersion": "v1",
        "kind": "Config",
        "current-context": CONTEXT,
        "clusters": [{"name": "mlops-assignment3", "cluster": cluster}],
        "contexts": [
            {
                "name": CONTEXT,
                "context": {
                    "cluster": "mlops-assignment3",
                    "namespace": NAMESPACE,
                    "user": "agent-reader",
                },
            }
        ],
        "users": [{"name": "agent-reader", "user": {"token": token_request["status"]["token"]}}],
    }
    destination = ROOT / ".local/kubeconfig-agent"
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        yaml.safe_dump(restricted, stream)
    destination.chmod(0o600)
    (ROOT / ".local/agent-credential.json").write_text(
        json.dumps(
            {
                "expires_at": token_request["status"]["expirationTimestamp"],
                "namespace": NAMESPACE,
                "service_account": "agent-reader",
            },
            indent=2,
        )
        + "\n"
    )
    print(
        "Restricted credential saved locally (0600); token expires: "
        + token_request["status"]["expirationTimestamp"]
    )


if __name__ == "__main__":
    main()
