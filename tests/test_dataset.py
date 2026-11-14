import csv
import hashlib
import io

import pytest

from mlops_agent.dataset import DATASET, dataset_bytes, prepare_dataset


def test_v2_changes_only_sepal_resolution():
    from sklearn.datasets import load_iris

    rows = list(csv.DictReader(io.StringIO(dataset_bytes().decode())))
    original = load_iris()
    changed = 0
    for row, features, target in zip(rows, original.data, original.target, strict=True):
        for name, value in zip(["sepal_length", "sepal_width"], features[:2], strict=True):
            revised = float(row[name])
            assert (revised * 2).is_integer()
            assert abs(revised - value) <= 0.25
            changed += revised != value
        assert [float(row["petal_length"]), float(row["petal_width"])] == list(features[2:])
        assert int(row["target"]) == target
    assert changed > 0


def test_recipe_is_stable_and_has_expected_classification_shape(tmp_path):
    content = dataset_bytes()
    rows = list(csv.DictReader(io.StringIO(content.decode())))
    assert len(rows) == 150
    assert {row["target"] for row in rows} == {"0", "1", "2"}
    assert all(len(row) == 5 for row in rows)
    digest = prepare_dataset(tmp_path)
    assert digest == hashlib.md5(content, usedforsecurity=False).hexdigest()
    assert prepare_dataset(tmp_path) == digest
    assert (tmp_path / DATASET).read_bytes() == content


def test_recipe_preserves_different_existing_data(tmp_path):
    target = tmp_path / DATASET
    target.parent.mkdir()
    target.write_bytes(b"user dataset")
    with pytest.raises(ValueError, match="refusing"):
        prepare_dataset(tmp_path)
    assert target.read_bytes() == b"user dataset"


def test_recipe_rejects_symlink_escape(tmp_path):
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "data").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    (tmp_path / "elsewhere/iris.csv").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="regular file"):
        prepare_dataset(tmp_path)
