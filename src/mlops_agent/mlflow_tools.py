"""Read-only MLflow intelligence via a bounded, isolated supported-client worker."""

import json
import math
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from mlops_agent.config import Settings
from mlops_agent.tools import ToolDefinition, ToolFailure, ToolInput, ToolRegistry

PARAMETERS = {
    "dataset_path",
    "dataset_git_revision",
    "dataset_dvc_md5",
    "code_git_revision",
    "split_seed",
    "test_fraction",
    "split_sha256",
    "evaluation_id",
    "evaluation_policy",
    "dataset_recipe",
    "classifier",
    "C",
    "max_depth",
    "n_estimators",
    "model_seed",
    "sklearn_version",
    "train_rows",
    "test_rows",
}
CAVEATS = [
    "Scores are comparable only within one evaluation_id (data, split and metric policy).",
    "Repeated selection on this small held-out split introduces selection bias; "
    "no independent final test.",
    "Best requested metric is a candidate, not production readiness "
    "or a retraining recommendation.",
    "No deployment, freshness, drift, latency or quality-gate evidence is supplied by this tool.",
]


class ExperimentsInput(ToolInput):
    limit: int = Field(default=20, ge=1, le=100)


class RunsInput(ToolInput):
    experiment_ids: list[str] = Field(min_length=1, max_length=10)
    limit: int = Field(default=5, ge=1, le=100)
    recent_hours: int = Field(default=168, ge=1, le=8760)

    @field_validator("experiment_ids")
    @classmethod
    def valid_ids(cls, values: list[str]) -> list[str]:
        if any(not item.isascii() or not item.isdecimal() or len(item) > 20 for item in values):
            raise ValueError("Invalid experiment ID")
        if len(set(values)) != len(values):
            raise ValueError("Distinct experiment IDs required")
        return values


class SelectionInput(RunsInput):
    metric: str = Field(default="f1_macro", pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    direction: Literal["maximize", "minimize"]
    evaluation_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class ComparisonInput(SelectionInput):
    experiment_ids: list[str] = Field(min_length=2, max_length=10)


class RunInput(ToolInput):
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class RegistryInput(ToolInput):
    model_name: Literal["assignment-iris"] = "assignment-iris"
    limit: int = Field(default=20, ge=1, le=100)


def summarize_run(run) -> dict:
    return {
        "run_id": run.info.run_id,
        "experiment_id": run.info.experiment_id,
        "status": run.info.status,
        "start_time_ms": run.info.start_time,
        "end_time_ms": run.info.end_time,
        "metrics": {k: v for k, v in run.data.metrics.items() if math.isfinite(v)},
        "parameters": {k: v for k, v in run.data.params.items() if k in PARAMETERS},
        "model_id": run.data.tags.get("assignment.model_id"),
    }


def artifact_info(item) -> dict:
    return {"path": item.path, "is_dir": item.is_dir, "file_size": item.file_size}


def rank_runs(runs: list[dict], args: SelectionInput) -> dict:
    eligible, excluded = [], []
    for run in runs:
        params = run["parameters"]
        reason = None
        required = {
            "evaluation_id",
            "dataset_dvc_md5",
            "dataset_git_revision",
            "code_git_revision",
            "dataset_path",
            "split_seed",
            "split_sha256",
            "evaluation_policy",
        }
        if run["status"] != "FINISHED":
            reason = "run_not_finished"
        elif not run.get("model_id"):
            reason = "missing_model_reference"
        elif not required.issubset(params) or any(not params[k] for k in required):
            reason = "missing_evaluation_lineage"
        elif args.metric not in run["metrics"] or not math.isfinite(run["metrics"][args.metric]):
            reason = "missing_or_nonfinite_metric"
        elif args.evaluation_id and params["evaluation_id"] != args.evaluation_id:
            reason = "different_requested_evaluation"
        if reason:
            excluded.append({"run_id": run["run_id"], "reason": reason})
        else:
            eligible.append(run)
    # Check actual provenance as well as the recorded cohort ID, so a mislabeled
    # evaluation_id cannot silently authorize cross-dataset/split comparisons.
    groups = {
        (
            r["parameters"]["evaluation_id"],
            r["parameters"]["dataset_dvc_md5"],
            r["parameters"]["split_sha256"],
            r["parameters"]["evaluation_policy"],
        )
        for r in eligible
    }
    comparable = len(groups) == 1
    ordered = (
        sorted(
            eligible,
            key=lambda r: (
                (-1 if args.direction == "maximize" else 1) * r["metrics"][args.metric],
                -(r["start_time_ms"] or 0),
                r["run_id"],
            ),
        )
        if comparable
        else []
    )
    return {
        "metric": args.metric,
        "direction": args.direction,
        "comparable": comparable,
        "evaluation_groups": len(groups),
        "selected_run": ordered[0] if ordered else None,
        "ranking": [{"run_id": r["run_id"], "value": r["metrics"][args.metric]} for r in ordered],
        "excluded": excluded,
        "selection_scope": "Only the returned recent window, not all historical runs",
        "reason": "ranked_comparable_runs"
        if comparable
        else ("incompatible_evaluations_choose_evaluation_id" if groups else "no_eligible_runs"),
        "caveats": CAVEATS,
    }


class ClientReader:
    """Only this worker uses MlflowClient; no UI or generic HTTP scraping."""

    def __init__(self, client):
        self.client = client

    def experiments(self, args: ExperimentsInput) -> dict:
        items = self.client.search_experiments(max_results=args.limit, order_by=["name ASC"])
        return {
            "experiments": [
                {
                    "experiment_id": e.experiment_id,
                    "name": e.name,
                    "artifact_location": e.artifact_location,
                }
                for e in items
            ],
            "has_more": bool(getattr(items, "token", None)),
        }

    def runs(self, args: RunsInput) -> dict:
        if any(not item.isdecimal() or len(item) > 20 for item in args.experiment_ids):
            raise ValueError("Invalid experiment ID")
        since = int((datetime.now(UTC) - timedelta(hours=args.recent_hours)).timestamp() * 1000)
        items = self.client.search_runs(
            experiment_ids=args.experiment_ids,
            filter_string=(
                f"tags.`assignment.training` = 'true' AND attributes.start_time >= {since}"
            ),
            max_results=args.limit,
            order_by=["attributes.start_time DESC"],
        )
        return {
            "runs": [summarize_run(r) for r in items],
            "has_more": bool(getattr(items, "token", None)),
            "since_ms": since,
            "limit": args.limit,
            "order": "newest_first",
        }

    def details(self, args: RunInput) -> dict:
        run = self.client.get_run(args.run_id)
        result = summarize_run(run)
        result["artifacts"] = [
            artifact_info(item) for item in self.client.list_artifacts(args.run_id)
        ]
        model_id = result["model_id"]
        if model_id:
            model = self.client.get_logged_model(model_id)
            result["logged_model"] = {
                "model_id": model.model_id,
                "model_uri": model.model_uri,
                "source_run_id": model.source_run_id,
                "artifacts": [
                    artifact_info(item)
                    for item in self.client.list_logged_model_artifacts(model_id)
                ],
            }
        else:
            result["logged_model"] = None
        return result

    def lineage(self, args: RunInput) -> dict:
        # DVC provenance remains available when artifact storage is unavailable.
        return {"parameters": summarize_run(self.client.get_run(args.run_id))["parameters"]}

    def selection(self, args: SelectionInput) -> dict:
        evidence = self.runs(args)
        return {**evidence, **rank_runs(evidence["runs"], args)}

    def comparison(self, args: ComparisonInput) -> dict:
        if len(set(args.experiment_ids)) < 2:
            raise ValueError("Two distinct experiments required")
        evidence = self.selection(args)
        evidence["experiments"] = [
            {
                "experiment_id": eid,
                "recent_run_count": sum(r["experiment_id"] == eid for r in evidence["runs"]),
            }
            for eid in args.experiment_ids
        ]
        evidence["coverage_limitation"] = (
            "A global last-N window can omit an experiment; "
            "zero count means no returned runs, not no history"
        )
        return evidence

    def registry(self, args: RegistryInput) -> dict:
        items = self.client.search_model_versions(
            filter_string=f"name = '{args.model_name}'",
            max_results=args.limit,
            order_by=["version_number DESC"],
        )
        return {
            "model_name": args.model_name,
            "versions": [
                {
                    "version": v.version,
                    "run_id": v.run_id,
                    "status": v.status,
                    "source": v.source,
                    "aliases": v.aliases,
                }
                for v in items
            ],
            "has_more": bool(getattr(items, "token", None)),
            "note": "Registry records are not deployment or promotion evidence"
            if items
            else "No versions returned for this model; registration may not have occurred",
        }


OPERATIONS = {
    "experiments": ExperimentsInput,
    "runs": RunsInput,
    "details": RunInput,
    "lineage": RunInput,
    "selection": SelectionInput,
    "comparison": ComparisonInput,
    "registry": RegistryInput,
}


class MlflowTools:
    def __init__(
        self,
        tracking_uri: str,
        timeout: float = 30,
        transport: Callable[[str, dict], dict] | None = None,
    ):
        self.uri = Settings.service_url(tracking_uri)
        if not 0 < timeout <= 120:
            raise ValueError("Timeout must be bounded")
        self.timeout = timeout
        self.transport = transport or self._worker
        names = [
            ("mlflow_list_experiments", "experiments", "List experiments and artifact locations"),
            ("mlflow_list_runs", "runs", "List recent recorded assignment training runs"),
            (
                "mlflow_get_run",
                "details",
                "Retrieve metrics, parameters and run/model artifact metadata",
            ),
            (
                "mlflow_select_best",
                "selection",
                "Select a comparable candidate by metric and direction",
            ),
            ("mlflow_compare_runs", "selection", "Compare the last N runs with evaluation caveats"),
            (
                "mlflow_compare_experiments",
                "comparison",
                "Compare recent runs across distinct experiments",
            ),
            ("mlflow_model_versions", "registry", "Retrieve registered assignment model versions"),
        ]
        self.registry = ToolRegistry(
            [
                ToolDefinition(
                    name,
                    description,
                    OPERATIONS[operation],
                    lambda args, op=operation: self.transport(op, args.model_dump()),
                )
                for name, operation, description in names
            ]
        )

    def run_params(self, run_id: str) -> dict[str, str]:
        args = RunInput(run_id=run_id)
        return self.transport("lineage", args.model_dump())["parameters"]

    def _worker(self, operation: str, args: dict) -> dict:
        root = Path(__file__).resolve().parents[2]
        environment = {
            "PATH": os.defpath,
            "PYTHONPATH": str(root / "src"),
            "MLFLOW_HTTP_REQUEST_TIMEOUT": str(max(1, int(self.timeout))),
            "MLFLOW_HTTP_REQUEST_MAX_RETRIES": "0",
            "MLFLOW_ENABLE_ASYNC_LOGGING": "false",
            "XDG_CACHE_HOME": str(root / ".local/cache"),
            "MPLCONFIGDIR": str(root / ".local/cache/matplotlib"),
            "NETRC": os.devnull,
        }
        try:
            result = subprocess.run(
                [sys.executable, "-m", "mlops_agent.mlflow_tools", "--worker"],
                input=json.dumps({"uri": self.uri, "operation": operation, "arguments": args}),
                capture_output=True,
                text=True,
                env=environment,
                cwd=root,
                timeout=self.timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            raise ToolFailure("MLflow operation timed out", "unavailable") from None
        except OSError:
            raise ToolFailure("MLflow client worker unavailable", "unavailable") from None
        if result.returncode:
            raise ToolFailure(
                "MLflow service/client unavailable; no observations returned", "unavailable"
            )
        try:
            response = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise ToolFailure("MLflow worker returned invalid evidence") from None
        if not isinstance(response, dict):
            raise ToolFailure("MLflow worker returned invalid evidence")
        return response


def worker_main() -> None:
    import mlflow
    from mlflow import MlflowClient

    try:
        request = json.load(sys.stdin)
        operation = request["operation"]
        args = OPERATIONS[operation].model_validate(request["arguments"])
        uri = Settings.service_url(request["uri"])
        # In 3.6, artifact repository resolution also consults the fluent URI,
        # even when MlflowClient has an explicit URI. This is process-local.
        mlflow.set_tracking_uri(uri)
        mlflow.set_registry_uri(uri)
        reader = ClientReader(MlflowClient(tracking_uri=uri, registry_uri=uri))
        print(json.dumps(getattr(reader, operation)(args), allow_nan=False))
    except Exception:
        # Do not propagate remote exception text, URIs, authentication or SDK logs.
        raise SystemExit(1) from None


if __name__ == "__main__" and sys.argv[1:] == ["--worker"]:
    worker_main()
