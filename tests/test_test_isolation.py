"""A missing service mock must fail before any real TCP connection."""

import socket

import pytest

from mlops_agent.config import Settings


@pytest.mark.parametrize("operation", ["connect", "connect_ex"])
@pytest.mark.parametrize("family", [socket.AF_INET, socket.AF_INET6])
def test_live_tcp_is_blocked_including_loopback(operation, family):
    address = ("127.0.0.1", 5000) if family == socket.AF_INET else ("::1", 8080)
    with socket.socket(family) as connection:
        with pytest.raises(AssertionError, match="Live network connections are forbidden"):
            getattr(connection, operation)(address)


def test_settings_start_without_shell_credentials_or_service_overrides():
    settings = Settings()
    assert not settings.provider_ready()
    assert settings.airflow_token is None
    assert settings.airflow_password is None
    assert settings.mlflow_tracking_uri == "http://127.0.0.1:5000"
