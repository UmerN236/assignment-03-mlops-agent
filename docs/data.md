# Dataset and local DVC storage

Recipe v2 writes 150 ordered Iris classification rows with four numeric features
and target classes 0, 1, 2. It rounds the two sepal measurements to the nearest
0.5 cm (half-up) to simulate a coarser sensor. Petal measurements, labels and row
order remain from scikit-learn 1.7.2's bundled data. This is an intentional
measurement-resolution experiment, not a claimed correction to Iris. Decimal
formatting and LF CSV lines make the recipe reproducible without network data.
V2 MD5: `c53cf26bbf3cda572dfcbfeee37b4b37`. The earlier unmodified v1 remains
recoverable at `6193fbd83e994dec9607a61c46134cd7654b845f` using that commit's recipe
or the local DVC remote (MD5 `4224576f0267bf88902f87f0f6200967`).

After `make setup`, run `make data-bootstrap` from the repository root. This
regenerates missing data, verifies its MD5 against the committed `.dvc` metadata,
populates the DVC cache and pushes to the configured local remote. Existing
different data is preserved and causes an error. Recipe/hash mismatch also fails.
`make data-status` reports workspace changes. The CSV is ignored; its pointer is
versioned in Git. MD5 is DVC content identity, not a security signature.

The default `local` remote URL is `../.local/dvc-remote` relative to `.dvc/config`,
so storage is inside this checkout's ignored `.local/dvc-remote`. It is **not**
uploaded to GitHub or available to a reviewer automatically. A clean clone can
rebuild the checked-out recipe using `make data-bootstrap`; no access to this machine is required.
Alternatively, copy an authorized DVC object store locally and configure it using
`dvc remote modify --local local url /absolute/path/to/copied-store`, then run
`dvc pull data/iris.csv.dvc`. Do not commit machine-specific paths or credentials.

For historical data, use a separate clone, checkout the exact dataset Git commit,
then pull from a store containing that content hash. If unavailable, use the
recipe from that historical commit. `dvc checkout` restores from the local cache;
it does not select a Git revision or fetch remote objects. Keep ordinary working
data safe by performing restoration in the isolated clone.

## Individually callable tools

Every tool is separately registered in `DvcTools(root).registry` with Pydantic
input and output schemas. CLI: `PYTHONPATH=src .venv/bin/python scripts/dvc-tool.py
TOOL_NAME '{JSON_ARGUMENTS}'`. Use `--schemas` for the exact machine-readable
contract. Omitted `revision` means HEAD; explicit revisions must be full lowercase
40-character Git commit SHAs. Dataset paths are restricted to `data/iris.csv`.

| Tool | Inputs | Observation |
| --- | --- | --- |
| `dvc_list_datasets` | `revision` | DVC-tracked dataset inventory at that commit |
| `dvc_get_dataset_version` | `revision`, `dataset_path` | Recorded MD5, Git commit, size, workspace hash and agreement |
| `dvc_compare_versions` | required `old_revision`, optional `new_revision` | DVC changes between commits, or commit versus current workspace |
| `dvc_get_data_status` | `dataset_path` | Actual DVC workspace change map and clean flag |
| `dvc_explain_reproduction` | `revision`, `dataset_path` | Historical recovery steps; performs no checkout |
| `dvc_resolve_run_reference` | `run_id`, `dataset_path`, `dataset_git_revision`, `dataset_dvc_md5` | Checks supplied lineage against Git metadata; does not verify the run record |
| `dvc_resolve_mlflow_run` | `run_id` | Fetches lineage through an injected run lookup and verifies the recorded reference |

The MLflow stage must supply a bounded callback to `DvcTools(run_lookup=...)`:
use `MlflowClient.get_run(run_id).data.params`, with the three exact lineage keys
`dataset_path`, `dataset_git_revision`, `dataset_dvc_md5`. Missing lookup returns
unavailable, missing lineage returns an error, and a differing hash returns
`reference_matches=false`. Callback behavior is unit-tested with mocks; **no real
training run lineage has been demonstrated yet**. CLI therefore leaves this lookup
unconfigured. Supplied run fields are never presented as retrieved facts.

All agent tools are read-only. Fixed argument lists cover only DVC list/status/diff
and Git revision/metadata reads. No generic shell, push, add, pull or checkout tool
is exposed. Subprocesses have a bounded timeout, no shell, a fixed dataset scope,
symlink/path checks and an environment excluding provider secrets and global DVC
configuration. Invalid arguments fail before execution; errors never return
plausible versions. Logs attach tool, status, duration and request ID without
arguments, output or exception bodies. Tool responses include observation times.
Infrastructure bootstrap and the isolated verification script are explicit
engineering operations, separate from agent permissions.

There are two genuine dataset revisions. Earlier DVC evidence demonstrates v1
restoration after isolated workspace corruption; the MLflow milestone compares
v1 with the intentional v2 sensor-resolution revision.

Validated with DVC 3.64.0 and pathspec 0.12.1. The pathspec pin repairs an observed
runtime import failure in DVC's ignore implementation with pathspec 1.x. On macOS,
`make setup` repairs hidden `.pth` flags inside the local venv; Make also exports
the project's source path for volumes that reapply those flags.

Command semantics follow the official [status](https://dvc.org/doc/command-reference/status),
[diff](https://dvc.org/doc/command-reference/diff),
[checkout](https://dvc.org/doc/command-reference/checkout), and
[local remote](https://dvc.org/doc/command-reference/remote/add) references.
