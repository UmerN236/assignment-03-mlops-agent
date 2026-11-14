# Dataset and local DVC storage

Recipe v1 writes 150 ordered Iris classification rows with four numeric features
and target classes 0, 1, 2. It uses scikit-learn 1.7.2's bundled data, decimal
formatting and LF CSV lines; no network download or random generation is involved.
Training and split policy belong to the subsequent training milestone.

After `make setup`, run `make data-bootstrap` from the repository root. This
regenerates missing data, verifies its MD5 against the committed `.dvc` metadata,
populates the DVC cache and pushes to the configured local remote. Existing
different data is preserved and causes an error. Recipe/hash mismatch also fails.
`make data-status` reports workspace changes. The CSV is ignored; its pointer is
versioned in Git. MD5 is DVC content identity, not a security signature.

The default `local` remote URL is `../.local/dvc-remote` relative to `.dvc/config`,
so storage is inside this checkout's ignored `.local/dvc-remote`. It is **not**
uploaded to GitHub or available to a reviewer automatically. A clean clone can
rebuild v1 using `make data-bootstrap`; no access to this machine is required.
Alternatively, copy an authorized DVC object store locally and configure it using
`dvc remote modify --local local url /absolute/path/to/copied-store`, then run
`dvc pull data/iris.csv.dvc`. Do not commit machine-specific paths or credentials.

For historical data, use a separate clone, checkout the exact dataset Git commit,
then pull from a store containing that content hash. If unavailable, use the
recipe from that historical commit. `dvc checkout` restores from the local cache;
it does not select a Git revision or fetch remote objects. Keep ordinary working
data safe by performing restoration in the isolated clone.
