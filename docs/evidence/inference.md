# Observed inference verification

Observed **2026-11-15T04:11:09.409601+00:00**. [The actual HTTP export](inference-live.json)
contains all 45 holdout predictions, probabilities, negative requests and structured logs.

| Item | Actual value |
| --- | --- |
| Image | `mlops-assignment3-inference:b869d2fa544c-d3af7c7bdc99` |
| Image ID | `sha256:7369df1ad77f2899d7723151b938e0b92d20fe792af5fb56aeb5d58ad4bd8a8a` |
| Application revision | `b869d2fa544ca8eed8fe1e020522673f61a2f3a8` |
| Platform / user | `linux/arm64` / `10001:10001` |
| MLflow run | `f1aa8c88b5d645418f17e18898805dba` |
| Model hash | `c5f8c425cde85bdaa4ba2fd7fc01eab0237fb3e0d8082a147041fae681507781` |
| Dataset Git revision | `ca3ed572fe61845c3781d11a8a59c4ecbf61f55e` |
| DVC MD5 | `c53cf26bbf3cda572dfcbfeee37b4b37` |

The reviewed image loads the real trusted model as a non-root user. Liveness,
readiness and version return 200. All 45 holdout predictions and probabilities
match an independent host load within 1e-12. The run/model/data identities agree.
Eight malformed or invalid inputs return 422; missing-model verification returns
liveness 200 and readiness/prediction 503. This verifies repeatability and serving,
not an independent test set or production approval.

The explicitly replaced assignment container is available at the observed
loopback URL `http://127.0.0.1:49723`. Ports may change on recreation. Source and
complete bundle provenance determine the image tag. No host model volume or
tracking connection is needed for inference.

[The Kubernetes export](kubernetes-live.json) verifies both replicas and real
Service routing. [Failure investigations](../failure-investigations.md) and
[five actual conversations](conversations/README.md) provide the final operational
assessment. Historical image permission failures were fixed before these successful
captures; the latest source validation-error redaction is now in the verified image.
