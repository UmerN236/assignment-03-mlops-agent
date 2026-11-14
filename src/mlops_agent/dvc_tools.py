"""Read-only DVC tools. No caller-supplied executable, command or repository."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, field_validator

from mlops_agent.dataset import DATASET
from mlops_agent.tools import ToolDefinition, ToolFailure, ToolInput, ToolRegistry

POINTER = f"{DATASET}.dvc"
REVISION = re.compile(r"(?:HEAD|[0-9a-f]{40})\Z")


class RevisionInput(ToolInput):
    revision: str = "HEAD"

    @field_validator("revision")
    @classmethod
    def safe_revision(cls, value: str) -> str:
        if not REVISION.fullmatch(value):
            raise ValueError("Only HEAD or a full lowercase commit SHA is allowed")
        return value


class DatasetInput(RevisionInput):
    dataset_path: Literal["data/iris.csv"] = DATASET


class CompareInput(ToolInput):
    old_revision: str
    new_revision: str | None = None

    @field_validator("old_revision", "new_revision")
    @classmethod
    def safe_revision(cls, value: str | None) -> str | None:
        return RevisionInput.safe_revision(value) if value is not None else None


class StatusInput(ToolInput):
    dataset_path: Literal["data/iris.csv"] = DATASET


class RunReferenceInput(ToolInput):
    """Exact lineage fields returned by an MLflow run-details tool, not an invented run."""

    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    dataset_path: Literal["data/iris.csv"] = DATASET
    dataset_git_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    dataset_dvc_md5: str = Field(pattern=r"^[a-f0-9]{32}$")


class RunLookupInput(ToolInput):
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class DvcTools:
    def __init__(
        self,
        root: Path,
        timeout: float = 30,
        run_lookup: Callable[[str], dict[str, str]] | None = None,
    ):
        # Defer availability checks until execution so an absent data checkout
        # does not prevent the agent from querying independent services.
        self.root = root.resolve()
        if not 0 < timeout <= 120:
            raise ValueError("Timeout must be bounded")
        self.timeout = timeout
        self.run_lookup = run_lookup
        self.git = shutil.which("git") or "git"
        self.dvc = str(Path(sys.executable).parent / "dvc")
        self.registry = ToolRegistry(
            [
                ToolDefinition(
                    "dvc_resolve_mlflow_run",
                    "Resolve a run's recorded lineage through the configured MLflow run lookup",
                    RunLookupInput,
                    self.resolve_run,
                ),
                ToolDefinition(
                    "dvc_list_datasets",
                    "List allowlisted DVC datasets at a Git revision",
                    RevisionInput,
                    self.list_datasets,
                ),
                ToolDefinition(
                    "dvc_get_dataset_version",
                    "Read committed content hash and workspace identity",
                    DatasetInput,
                    self.get_version,
                ),
                ToolDefinition(
                    "dvc_compare_versions",
                    "Compare two commits or a commit with workspace data",
                    CompareInput,
                    self.compare,
                ),
                ToolDefinition(
                    "dvc_get_data_status",
                    "Observe actual DVC workspace changes",
                    StatusInput,
                    self.status,
                ),
                ToolDefinition(
                    "dvc_resolve_run_reference",
                    "Verify supplied MLflow lineage against Git/DVC; does not fetch the MLflow run",
                    RunReferenceInput,
                    self.resolve_reference,
                ),
                ToolDefinition(
                    "dvc_explain_reproduction",
                    "Plan historical recovery in a separate clone",
                    DatasetInput,
                    self.reproduction,
                ),
            ]
        )

    def _check_paths(self) -> None:
        if not self.root.is_dir():
            raise ToolFailure("DVC repository unavailable", "unavailable")
        for name in (
            ".git",
            ".dvc",
            ".dvc/config",
            ".dvc/cache",
            "data",
            POINTER,
            DATASET,
            ".local",
            ".local/cache",
            ".local/config",
        ):
            path = self.root / name
            if path.is_symlink() or not path.resolve().is_relative_to(self.root):
                raise ValueError("Symlink or path escape is disallowed")

    def _run(self, operation: str, *values: str) -> str:
        """Closed operation allowlist. Validate here even if invoked outside the registry."""
        self._check_paths()
        if operation == "revision" and len(values) == 1:
            revision = RevisionInput.safe_revision(values[0])
            argv = [
                self.git,
                "-c",
                "core.fsmonitor=false",
                "rev-parse",
                "--verify",
                f"{revision}^{{commit}}",
            ]
        elif operation == "metadata" and len(values) == 1:
            revision = RevisionInput.safe_revision(values[0])
            if revision == "HEAD":
                raise ValueError("Resolve HEAD before metadata access")
            argv = [self.git, "-c", "core.fsmonitor=false", "show", f"{revision}:{POINTER}"]
        elif operation == "list" and len(values) == 1:
            revision = RevisionInput.safe_revision(values[0])
            argv = [self.dvc, "list", ".", "data", "--dvc-only", "--json", "--rev", revision]
        elif operation == "status" and not values:
            argv = [self.dvc, "status", "--json", POINTER]
        elif operation == "diff" and len(values) in (1, 2):
            revisions = [RevisionInput.safe_revision(value) for value in values]
            argv = [self.dvc, "diff", *revisions, "--json", "--show-hash", "--targets", DATASET]
        else:
            raise ValueError("Operation is not allowlisted")
        # Do not inherit provider keys, Git credentials, shell hooks or global DVC configs.
        environment = {
            "PATH": os.defpath,
            "DVC_NO_ANALYTICS": "true",
            "DVC_SITE_CACHE_DIR": str(self.root / ".local/cache/dvc"),
            "DVC_GLOBAL_CONFIG_DIR": str(self.root / ".local/config/dvc"),
            "DVC_SYSTEM_CONFIG_DIR": str(self.root / ".local/config/dvc-system"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }
        try:
            result = subprocess.run(
                argv,
                cwd=self.root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            raise ToolFailure("DVC/Git operation timed out", "unavailable") from None
        except OSError:
            raise ToolFailure("DVC/Git executable unavailable", "unavailable") from None
        if result.returncode:
            raise ToolFailure("DVC/Git command failed; requested evidence is unavailable")
        return result.stdout

    def _revision(self, value: str) -> str:
        resolved = self._run("revision", value).strip()
        if not re.fullmatch(r"[a-f0-9]{40}", resolved):
            raise ToolFailure("Git returned an invalid commit identity")
        return resolved

    def _metadata(self, revision: str) -> dict:
        content = yaml.safe_load(self._run("metadata", revision))
        outs = content.get("outs", []) if isinstance(content, dict) else []
        if (
            len(outs) != 1
            or outs[0].get("path") != "iris.csv"
            or outs[0].get("hash") != "md5"
            or not re.fullmatch(r"[a-f0-9]{32}", str(outs[0].get("md5", "")))
        ):
            raise ToolFailure("Dataset metadata is unsupported or invalid")
        return {
            "dataset_path": DATASET,
            "dataset_git_revision": revision,
            "dataset_dvc_md5": outs[0]["md5"],
            "size_bytes": outs[0].get("size"),
        }

    def _json(self, operation: str, *values: str) -> dict | list:
        try:
            result = json.loads(self._run(operation, *values))
        except json.JSONDecodeError:
            raise ToolFailure("DVC returned malformed JSON") from None
        expected = list if operation == "list" else dict
        if not isinstance(result, expected):
            raise ToolFailure("DVC returned an unsupported response")
        return result

    def list_datasets(self, args: RevisionInput) -> dict:
        revision = self._revision(args.revision)
        entries = self._json("list", revision)
        datasets = [entry for entry in entries if entry.get("path") == "iris.csv"]
        return {
            "dataset_git_revision": revision,
            "directory": "data",
            "datasets": datasets,
            "scope": [DATASET],
        }

    def get_version(self, args: DatasetInput) -> dict:
        metadata = self._metadata(self._revision(args.revision))
        target = self.root / DATASET
        workspace_hash = (
            hashlib.md5(target.read_bytes(), usedforsecurity=False).hexdigest()
            if target.is_file()
            else None
        )
        return {
            **metadata,
            "workspace_md5": workspace_hash,
            "workspace_matches_revision": workspace_hash == metadata["dataset_dvc_md5"],
        }

    def compare(self, args: CompareInput) -> dict:
        old = self._revision(args.old_revision)
        new = self._revision(args.new_revision) if args.new_revision else None
        changes = self._json("diff", old, *([new] if new else []))
        return {
            "old_revision": old,
            "new_revision": new,
            "new_is_workspace": new is None,
            "changes": changes,
        }

    def status(self, args: StatusInput) -> dict:
        changes = self._json("status")
        return {"dataset_path": args.dataset_path, "changes": changes, "clean": not changes}

    def resolve_reference(self, args: RunReferenceInput) -> dict:
        metadata = self._metadata(self._revision(args.dataset_git_revision))
        return {
            **metadata,
            "supplied_run_id": args.run_id,
            "reference_matches": metadata["dataset_dvc_md5"] == args.dataset_dvc_md5,
            "run_record_verified": False,
            "limitation": "Run fields are caller-supplied; correlate with MLflow run details",
        }

    def resolve_run(self, args: RunLookupInput) -> dict:
        if self.run_lookup is None:
            raise ToolFailure("MLflow run lookup is not configured", "unavailable")
        try:
            params = self.run_lookup(args.run_id)
            reference = RunReferenceInput(
                run_id=args.run_id,
                dataset_path=params["dataset_path"],
                dataset_git_revision=params["dataset_git_revision"],
                dataset_dvc_md5=params["dataset_dvc_md5"],
            )
        except (KeyError, ValueError, TypeError):
            raise ToolFailure("MLflow run has missing or invalid dataset lineage") from None
        return {
            **self.resolve_reference(reference),
            "run_record_verified": True,
            "limitation": "Run lineage was retrieved; hash agreement does not prove model quality",
        }

    def reproduction(self, args: DatasetInput) -> dict:
        metadata = self._metadata(self._revision(args.revision))
        return {
            **metadata,
            "executes_checkout": False,
            "steps": [
                "Create a separate clone; preserve the main workspace",
                f"git checkout --detach {metadata['dataset_git_revision']}",
                "make setup",
                "Configure a local DVC remote containing the required hash, or make data-bootstrap",
                f"dvc pull {POINTER} fetches and checks out; dvc checkout uses cached data only",
                "Verify content hash and clean DVC status before using the dataset",
            ],
        }
