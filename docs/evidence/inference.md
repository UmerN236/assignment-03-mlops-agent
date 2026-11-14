# Observed inference image verification

Observed on 14 November 2026 at 11:12:49 UTC. The
[machine-readable export](inference-live.json) contains actual HTTP responses,
all 45 predictions, exact model/data lineage and structured request logs.

| Item | Observed value |
| --- | --- |
| Image | `mlops-assignment3-inference:c20e0106c52d` |
| Image ID | `sha256:c3d340652266361752a16347e5e8779d143c734f6aff46ea7ffa2bc21ea523ae` |
| Application Git SHA | `c20e0106c52d69cd2f28573cf6405d7880ccb353` |
| Platform / user | `linux/arm64` / `10001:10001` |
| MLflow run | `f1aa8c88b5d645418f17e18898805dba` |
| Logged model | `m-be27d8728a7f4331a812c37b663e8098` |
| Dataset | `data/iris.csv` at `ca3ed572fe61845c3781d11a8a59c4ecbf61f55e` |
| DVC MD5 | `c53cf26bbf3cda572dfcbfeee37b4b37` |
| Model SHA-256 | `c5f8c425cde85bdaa4ba2fd7fc01eab0237fb3e0d8082a147041fae681507781` |

`make inference-image` retrieved the selected model over the MLflow HTTP artifact
API, validated its lineage/integrity, reused the hash-locked dependency layer,
and loaded the artifact inside the image as the non-root serving user.
`make verify-inference` then ran that image with a read-only filesystem, dropped
capabilities, resource bounds and a loopback-only port. No host artifact volume
or MLflow network access was supplied to the serving container.

The healthy container returned 200 for `/livez`, `/readyz`, `/version` and
`/predict`. All 45 stratified holdout class predictions matched an independent
load of the same artifact; every class probability matched within 1e-12.
Recomputed accuracy was 0.9111111111111111, macro F1 0.9107142857142857 and log
loss 0.2077641840906652. These reproduce the candidate evaluation, not a new test set.
Version metadata matched the full application SHA and selected run/model/data
reference exactly.

Eight live negative requests returned 422: empty batch, missing feature, string,
boolean, negative measurement, oversized batch, extra field and nonfinite JSON.
A separate container configured with a missing bundle returned liveness 200,
readiness/prediction 503, `model_ready: false` and null model metadata. Only that
temporary negative-test container was removed. The healthy labeled container
`mlops-assignment3-inference` remains available; its observed review URL was
`http://127.0.0.1:62185` (the host port may change on recreation).

An initial real image failed with a source-file `PermissionError`: Docker had
preserved restrictive host modes while serving as UID 10001. Commit `c20e010`
normalizes read/traverse permissions and adds the non-root build smoke check.
The corrected build and complete HTTP verification passed. This repair and the
missing-model test do not replace the later required Airflow validation and
Kubernetes readiness-probe failure investigations.

Ruff lint/format and 107 pytest cases passed locally, including 25 inference
cases with actual sklearn serialization. The service smoke check also observed
MLflow HTTP 200, authenticated Airflow API 200 with healthy components, and the
dedicated kind node Ready. Kubernetes deployment, workflow execution, integrated
agent conversations and production promotion remain pending.
