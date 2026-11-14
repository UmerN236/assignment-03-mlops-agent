"""Byte-stable Iris recipe v2: simulate coarser sepal sensor resolution."""

import csv
import hashlib
import io
import math
from pathlib import Path

from sklearn.datasets import load_iris

DATASET = "data/iris.csv"


def dataset_bytes() -> bytes:
    iris = load_iris()
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["sepal_length", "sepal_width", "petal_length", "petal_width", "target"])
    for features, target in zip(iris.data, iris.target, strict=True):
        # Intentional data revision, not a claimed correction to the source data.
        # Only sepal measurements change, to nearest 0.5 cm (half-up).
        revised = [math.floor(value * 2 + 0.5) / 2 for value in features[:2]]
        writer.writerow([*(f"{value:.1f}" for value in [*revised, *features[2:]]), int(target)])
    return stream.getvalue().encode("ascii")


def prepare_dataset(root: Path) -> str:
    """Create missing v2 data; refuse to overwrite any different existing dataset."""
    target = root / DATASET
    content = dataset_bytes()
    if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Dataset must be a regular file inside the repository")
    if target.exists() and target.read_bytes() != content:
        raise ValueError("Existing dataset differs; refusing to overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return hashlib.md5(content, usedforsecurity=False).hexdigest()


def main() -> None:
    print(prepare_dataset(Path.cwd()))
