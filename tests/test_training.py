import numpy as np
import pytest
from pydantic import ValidationError

from mlops_agent.dataset import dataset_bytes
from mlops_agent.training import (
    TrainingConfig,
    evaluate_classifier,
    fit_classifier,
    prepare_split,
    training_lineage,
    validate_dataset,
)


@pytest.mark.parametrize("classifier", ["logistic", "forest"])
def test_training_is_deterministic_and_split_is_disjoint(classifier):
    config = TrainingConfig(classifier=classifier)
    data = prepare_split(dataset_bytes(), config)
    repeat = prepare_split(dataset_bytes(), config)
    assert data.evaluation_id == repeat.evaluation_id
    assert set(data.train_indices).isdisjoint(data.test_indices)
    assert len(data.train_indices) == 105 and len(data.test_indices) == 45
    assert np.bincount(data.labels[data.test_indices]).tolist() == [15, 15, 15]
    first = evaluate_classifier(fit_classifier(data, config), data)
    second = evaluate_classifier(fit_classifier(repeat, config), repeat)
    assert first == second
    assert set(first[0]) == {"accuracy", "f1_macro", "log_loss"}
    assert len(first[1]["actual"]) == 45


def test_scaler_is_fitted_only_on_train_and_cohort_changes_with_split_and_data():
    content = dataset_bytes()
    data = prepare_split(content, TrainingConfig())
    model = fit_classifier(data, TrainingConfig())
    np.testing.assert_allclose(model[0].mean_, data.features[data.train_indices].mean(axis=0))
    changed_seed = prepare_split(content, TrainingConfig(split_seed=43))
    assert data.split_sha256 != changed_seed.split_sha256
    assert data.evaluation_id != changed_seed.evaluation_id
    changed_data = prepare_split(content.replace(b"5.0", b"5.1", 1), TrainingConfig())
    assert changed_data.split_sha256 == data.split_sha256
    assert changed_data.evaluation_id != data.evaluation_id


@pytest.mark.parametrize(
    "mutation",
    [
        lambda b: b.replace(b"sepal_length", b"unexpected", 1),
        lambda b: b.replace(b"5.0", b"nan", 1),
        lambda b: b.replace(b"5.0", b"", 1),
        lambda b: b.replace(b",0\n", b",9\n", 1),
        lambda b: b.replace(b",0\n", b",0,extra\n", 1),
        lambda b: b"\n".join(b.splitlines()[:-1]),
    ],
)
def test_validation_rejects_bad_training_input(mutation):
    with pytest.raises(ValueError, match="Dataset validation failed"):
        validate_dataset(mutation(dataset_bytes()))


@pytest.mark.parametrize(
    "kwargs", [{"C": float("inf")}, {"split_seed": -1}, {"classifier": "shell"}, {"max_depth": 0}]
)
def test_config_is_bounded(kwargs):
    with pytest.raises(ValidationError):
        TrainingConfig(**kwargs)


def test_training_refuses_uncommitted_or_mismatched_lineage(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "mlops_agent.training.DvcTools.get_version",
        lambda *args: {"workspace_matches_revision": False},
    )
    with pytest.raises(ValueError, match="committed DVC"):
        training_lineage(tmp_path)
    monkeypatch.setattr(
        "mlops_agent.training.DvcTools.get_version",
        lambda *args: {"workspace_matches_revision": True},
    )
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: SimpleNamespace(stdout=" M source.py"))
    with pytest.raises(ValueError, match="Commit code"):
        training_lineage(tmp_path)
