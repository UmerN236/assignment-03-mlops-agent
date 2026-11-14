# Observed Kubernetes deployment

[Actual structured export](kubernetes-live.json) records the observation timestamp
and request IDs. The engineer verifier used actual Kubernetes APIs and HTTP
responses, with the restricted agent account for all tool observations.

- Deployment `mlops-agent/inference`: two desired, updated, available and Ready
  replicas; generation observed by the controller; both Pods Running with zero
  restarts at capture. Pod conditions, image IDs, probe paths and resource bounds
  are in the workload responses.
- ClusterIP `10.96.207.167:8000`, two Ready EndpointSlice backends. Actual in-cluster
  requests reached the Service DNS, ClusterIP and each replica IP. All four targets
  returned live/ready/version 200, matched all 45 holdout class predictions and
  probabilities within 1e-12, and returned 422 for an empty batch.
- Application SHA `c20e0106c52d69cd2f28573cf6405d7880ccb353`; packaged candidate run
  `f1aa8c88b5d645418f17e18898805dba`, model
  `m-be27d8728a7f4331a812c37b663e8098`, model SHA-256
  `c5f8c425cde85bdaa4ba2fd7fc01eab0237fb3e0d8082a147041fae681507781`.
  `/version` on every target matched the trusted bundle, training code SHA,
  evaluation cohort and dataset reference. This is deployment verification of the
  same holdout evaluation, not new independent model validation.
- Both Pods supplied actual bounded structured logs and UID-related event reasons
  and counts. Arbitrary raw log/event text is omitted. A healthy snapshot does not
  imply all historical states were healthy.
- Ten authorization probes verified allowed namespace reads and denied other
  namespace reads, secrets, nodes, deployment patches, Pod deletes, exec and POST
  proxy. An actual server patch dry-run was Forbidden; replicas remained two.
  Tool namespace overrides and unregistered mutation requests returned empty
  evidence with invalid/unavailable statuses.

During verification, the generated Python SDK's declared string proxy response
converted decoded JSON into Python dictionary representation. The health tool
now reads bounded raw HTTP bytes before JSON/schema validation. The live health
check and a mocked response regression case pass. This implementation repair is
not one of the later deliberately injected failures.

Services are left running for review. The expiring token remains local; refresh
with engineer setup after its recorded local expiry. Single-node kind and two
replicas are not evidence of production readiness. No retraining or promotion
was initiated. LLM conversations and the two controlled investigations remain
pending.
