"""Ordinary tests use explicit settings and mocked service transports."""

import os
import socket

import pytest

from mlops_agent.config import Settings


@pytest.fixture(autouse=True)
def isolated_settings_environment(monkeypatch):
    # Never let a shell's provider choice, keys or service targets affect tests.
    # Settings does not load .env implicitly; file-loading tests use tmp_path.
    for name in tuple(os.environ):
        if name.lower() in Settings.model_fields:
            monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def no_live_service_connections(monkeypatch):
    # Keep in-process ASGI/MockTransport and local Unix socket pairs available.
    # This is an in-process test guard, not an OS/subprocess network sandbox.
    for operation in ("connect", "connect_ex"):
        original = getattr(socket.socket, operation)

        def guarded(sock, address, *args, _original=original, **kwargs):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                raise AssertionError("Live network connections are forbidden in ordinary pytest")
            return _original(sock, address, *args, **kwargs)

        monkeypatch.setattr(socket.socket, operation, guarded)
