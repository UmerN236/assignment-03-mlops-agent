# Kubernetes deployment and diagnostic tools

The inference workload runs only in kind `mlops-assignment3`, context
`kind-mlops-assignment3`, namespace `mlops-agent`. This local single-node cluster
is a demonstration environment. Two replicas provide process redundancy, not
node or production availability guarantees.

## Engineer setup

```sh
make cluster
# Requires the previously verified inference image and artifacts/inference bundle.
make deploy-kubernetes
make verify-kubernetes
```

`deploy-kubernetes.py` checks the existing namespace/target node ownership,
inspects each named resource before writes, verifies the Docker image identity
against the inference evidence, loads it into this named kind cluster, applies
only the application and read-only RBAC manifests, and waits for rollout. It
refuses to overwrite existing objects without assignment ownership labels.
The namespace manifest is `infra/kind/namespace.yaml`. The application manifest
has two replicas, rolling updates with zero unavailable replicas, a ClusterIP,
startup/liveness/readiness probes, ConfigMap, CPU/memory requests and limits,
non-root UID 10001, read-only root filesystem and dropped capabilities.
The serving account has no role and mounts no token.

For optional host review, run the following engineer command and visit
`http://127.0.0.1:18000/readyz` or `/docs` while it remains open:

```sh
.local/bin/kubectl --kubeconfig .local/kubeconfig --context kind-mlops-assignment3 -n mlops-agent port-forward --address=127.0.0.1 service/inference 18000:8000
```

The current application manifest deliberately references the already verified
image `mlops-assignment3-inference:c20e0106c52d`, with `imagePullPolicy: Never`.
The deploy script verifies its exact Docker image ID before import. A fresh
machine must build/package a selected trusted model first and deliberately update
both the manifest and verification reference for its new image; an unverified
replacement tag cannot pass setup. Kubernetes reports the imported containerd
manifest digest as imageID, while Docker reports the image configuration digest;
these are different identifiers. The `/version` route verifies actual application
SHA and full packaged model/data provenance on every tested backend.

Setup writes an expiring TokenRequest credential to ignored
`.local/kubeconfig-agent`, permissions 0600. Expiry metadata is stored locally in
`.local/agent-credential.json`; no token enters source/evidence. Rerun engineer
setup to refresh an expired credential. Tools never fall back to the admin
`.local/kubeconfig`. `KUBERNETES_READONLY_KUBECONFIG` can select another generated
restricted credential without changing the user's `.env`.

## Individually callable tools

```sh
PYTHONPATH=src .venv/bin/python scripts/kubernetes-tool.py workloads
PYTHONPATH=src .venv/bin/python scripts/kubernetes-tool.py services
PYTHONPATH=src .venv/bin/python scripts/kubernetes-tool.py health
# Substitute an observed Pod name, not this placeholder.
PYTHONPATH=src .venv/bin/python scripts/kubernetes-tool.py diagnostics --arguments '{"pod":"inference-HASH-SUFFIX"}'
PYTHONPATH=src .venv/bin/python scripts/kubernetes-tool.py logs --arguments '{"pod":"inference-HASH-SUFFIX","tail_lines":12}'
```

| Tool | Observations |
| --- | --- |
| `kubernetes_workloads` | Pods, readiness, conditions, restarts/termination reasons, actual image IDs; Deployment generation, desired/updated/available/Ready replicas, probes and resource bounds |
| `kubernetes_services` | ClusterIP, selectors/ports, EndpointSlice addresses, readiness and Pod targets |
| `kubernetes_diagnostics` | Approved Pod status and UID-scoped event reasons, counts, sources and timestamps |
| `kubernetes_logs` | Bounded structured log tail, optional previous container; only known application fields |
| `kubernetes_health` | GET `/livez`, `/readyz`, `/version` through the inference Service proxy; validated application/model/data identity |

Inputs forbid extra fields and namespace/context overrides. Logs are capped at
100 lines/16 KiB, list results at 100 items with explicit truncation, and service
health responses at 64 KiB. SDK requests have connection/read timeouts and zero
retries; a separate worker enforces the total tool timeout (default 30 seconds).
Only token kubeconfigs are accepted: no admin identity, exec plugin or auth
provider. The worker receives no provider credentials. Service/API/auth failures
produce `unavailable` and empty evidence. No operational facts are invented.

Event messages and arbitrary raw logs are omitted to avoid exposing secrets or
remote instructions. Logs retain known tool name/status, HTTP code, duration and
UUID request ID. A previous log request can be unavailable if no previous
container exists. Event retention and bounded tails limit historical diagnosis;
an empty event list does not prove there was never a failure. Service health
samples backends; workload state and direct replica verification establish the
observed two-replica state.

## Permissions and write policy

The `agent-reader` Role allows namespace reads of Pods/logs, Services, events,
Deployments and EndpointSlices, plus GET proxy for `inference:http`. It grants no
secrets, nodes, cross-namespace access, exec, port-forward or resource mutations.
All five registered tools are read-only. Mutation tool names and mutation fields
are rejected, including requests containing a claimed confirmation. No agent
write operation is implemented in this stage; confirmation cannot grant RBAC
permissions. Any future mutator must require a fresh explicit confirmation bound
to exact action/resource/namespace and separately provisioned credentials.
Engineer setup uses its explicit dedicated admin credential outside agent tools.
The verifier's inspected-Pod exec is an engineer-only network check; the agent
cannot use it.

## Validation and limits

`make verify-kubernetes` captures actual tool envelopes, two Ready replicas,
logs/events/restarts, model identity, ten RBAC probes and a forbidden server
patch dry-run. From an inspected application Pod it reaches Service DNS,
ClusterIP and each Pod IP, tests live/ready/version, matches all 45 holdout
predictions/probabilities to an independent local artifact reload, and checks
invalid input receives 422. It writes [sanitized evidence](evidence/kubernetes-live.json).
Ordinary pytest/CI mocks Kubernetes and needs no live credential.

The controlled readiness-probe investigation and complete five-conversation
demonstration remain pending. Isolated malformed training-input failure/recovery
and the Airflow workflow are recorded in [workflow evidence](evidence/airflow-dag.md);
the integrated LLM assessment is in [agent evidence](evidence/agent.md). Current
health is a point-in-time observation, not a quality gate or retraining signal.

References checked for setup: [Kubernetes RBAC](https://kubernetes.io/docs/reference/access-authn-authz/rbac/),
[probe behavior](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/),
and [TokenRequest service-account credentials](https://kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/).
The supported Python client is pinned to 34.1.0 for the observed Kubernetes 1.34 node.
