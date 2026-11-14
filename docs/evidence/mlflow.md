# MLflow live milestone evidence

Observed: 2026-11-14T08:13:54.435839+00:00. MLflow 3.6.0. All 14 exported tool calls returned `ok`.

Training code and dataset Git reference: `ca3ed572fe61845c3781d11a8a59c4ecbf61f55e`.
Dataset v2 DVC MD5: `c53cf26bbf3cda572dfcbfeee37b4b37`.
Evaluation cohort: `5f079144dd19531869301418fd8af5092ea35c6bd2439b53c87ec084f7f79dcb`.

All five FINISHED runs used the same 105/45 stratified split, seed 42. Metrics below are retrieved observations, not mocks.

| Run ID | Experiment / configuration | Macro F1 | Accuracy | Log loss |
| --- | --- | ---: | ---: | ---: |
| `bad9cb6b26b94ce28ff491c4d0b26d47` | 1 / logistic C=0.1 | 0.888765 | 0.888889 | 0.440502 |
| `4e5449ea8c57494d9a602569ac4ca1f9` | 1 / logistic C=1.0 | 0.910714 | 0.911111 | 0.214631 |
| `8b207014f0894e0aafed5a030213198b` | 1 / logistic C=10.0 | 0.910714 | 0.911111 | 0.129493 |
| `f1aa8c88b5d645418f17e18898805dba` | 2 / forest depth=2, trees=100 | 0.910714 | 0.911111 | 0.207764 |
| `bf7818c546234bf1b1523519f0c6c43f` | 2 / forest depth=4, trees=100 | 0.887767 | 0.888889 | 0.178238 |

F1 selection returned `f1aa8c88b5d645418f17e18898805dba` (depth-2 forest). Three runs tied; the documented newest-run tie break selected this candidate. Registry `assignment-iris` version 1 is READY with that source run. This does not imply promotion or deployment.

Minimizing log loss selected logistic C=10. Both direction-specific results are in the export. Repeated selection on this 45-row holdout introduces selection bias; no independent final test, drift, latency or production-readiness evidence is claimed.

The downloaded candidate reproduces recorded metrics within 1e-12. Its model.pkl is 81643 bytes, SHA-256 `c5f8c425cde85bdaa4ba2fd7fc01eab0237fb3e0d8082a147041fae681507781`. The exact same hash was fetched over HTTP from inside the actual Airflow container via `http://mlflow:5000`. Airflow training dependencies and inference-image execution are still pending.

Every run has retrieved metrics, provenance parameters, evaluation/lineage/split JSON artifact metadata and seven logged-model artifact entries. The DVC lookup retrieved actual MLflow lineage and matched the committed pointer. The v1-to-v2 DVC diff reported a content modification.

A real artifact-listing failure revealed that the pinned client also consults the fluent tracking URI. The isolated worker now sets both client and fluent URIs; a regression test and the passing live listing verify the fix. The uv environment lacks pip metadata, so MLflow warned that conda.yaml lists pip without a version. Model requirements record pinned MLflow/sklearn/NumPy/cloudpickle; the project environment uses uv.lock. Conda reproduction is not claimed.

Exports: [14 real tool responses and artifact checks](mlflow-live.json), [v2 isolated pull/restore/bootstrap](dvc-v2.json), and [earlier v1 recovery](dvc-bootstrap.json). The earlier DVC-only exports contain historical pending MLflow notes; the separate MLflow export establishes the completed correlation.

Model storage persists in the dedicated MLflow Docker volume. No artifacts or secret configuration were uploaded to GitHub; only source, DVC pointers and sanitized evidence are committed.
