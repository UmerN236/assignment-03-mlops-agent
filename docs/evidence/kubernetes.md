# Observed Kubernetes deployment

Captured **2026-11-15T04:11:24.566675+00:00** using real APIs and restricted agent credentials.
[The complete export](kubernetes-live.json) contains request IDs and exact responses.

- Two desired, updated, available and Ready inference replicas in `mlops-agent`.
- ClusterIP Service and two Ready EndpointSlice backends; actual Service DNS,
  ClusterIP and both Pod IPs each matched all 45 holdout predictions/probabilities.
- Application revision `b869d2fa544ca8eed8fe1e020522673f61a2f3a8`; model run
  `f1aa8c88b5d645418f17e18898805dba`. Every tested backend reported matching model/data provenance.
- Readiness/liveness probes, CPU/memory requests/limits, ConfigMap, non-root UID,
  read-only root filesystem and dropped capabilities are verified.
- Bounded Pod logs, UID-scoped events, restart counts and health are observed;
  ten RBAC probes deny unrelated scope, secrets, modifications, exec and POST proxy.
  A real server-side patch dry-run was Forbidden; desired replicas stayed two.
- Read-only tools reject namespace overrides and unregistered mutation requests.
  No administrator fallback is used. The token stays local and expires after its
  recorded duration; engineering setup can refresh it.

The wrong-readiness-path exercise is independently captured with successful
restoration in [the failure investigation](../failure-investigations.md). The final
healthy export above follows the reviewed image update. LLM requests and factual
references are in [the conversation index](conversations/README.md). Two replicas
on a single local kind node do not establish production/node-level availability.
