"""Engineering verifier must preserve unrelated and different existing containers."""

import json
import runpy
from types import SimpleNamespace

import pytest


def verifier():
    return runpy.run_path("scripts/verify-inference.py")


def test_foreign_container_is_rejected_before_replacement(monkeypatch):
    module = verifier()
    inspect = module["inspect_container"]
    foreign = {"Name": "/mlops-assignment3-inference", "Config": {"Labels": {}}}
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps(foreign))

    monkeypatch.setitem(inspect.__globals__, "docker", docker)
    with pytest.raises(AssertionError):
        inspect("mlops-assignment3-inference")
    assert len(calls) == 1 and calls[0][0] == "inspect"


def test_different_owned_image_requires_explicit_replacement(monkeypatch):
    start = verifier()["start"]
    existing = {"Config": {"Image": "old"}, "State": {"Running": True}}
    monkeypatch.setitem(start.__globals__, "inspect_container", lambda _: existing)
    monkeypatch.setitem(start.__globals__, "docker", lambda *a, **k: pytest.fail("No mutation"))
    with pytest.raises(ValueError, match="replace-owned"):
        start("new", "mlops-assignment3-inference")


def test_same_stopped_owned_image_resumes_without_removal(monkeypatch):
    start = verifier()["start"]
    existing = {"Config": {"Image": "same"}, "State": {"Running": False}}
    calls = []
    monkeypatch.setitem(start.__globals__, "inspect_container", lambda _: existing)
    monkeypatch.setitem(start.__globals__, "docker", lambda *a, **k: calls.append(a))
    assert start("same", "mlops-assignment3-inference") == existing
    assert calls == [("start", "mlops-assignment3-inference")]
