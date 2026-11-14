"""Configuration safety tests run without credentials or live services."""

import os

import pytest
from pydantic import ValidationError

from mlops_agent.config import ConfigurationError, Settings, load_settings


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    names = set(Settings.model_fields)
    for name in os.environ:
        if name.lower() in names:
            monkeypatch.delenv(name)


def test_defaults_are_bounded_and_dedicated():
    settings = load_settings(None)
    assert settings.kubernetes_namespace == "mlops-agent"
    assert settings.kubernetes_context == "kind-mlops-assignment3"
    assert settings.tool_timeout_seconds == 30
    assert settings.max_tool_iterations == 8
    assert not settings.provider_ready()


def test_missing_credential_does_not_block_independent_setup():
    settings = load_settings(None)
    assert not settings.provider_ready()
    with pytest.raises(ConfigurationError, match="Missing OPENROUTER_API_KEY"):
        settings.require_provider()


def test_env_file_is_read_only_and_process_env_wins(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    content = "MAX_TOOL_ITERATIONS=4\nOPENROUTER_API_KEY=test-sentinel\n"
    path.write_text(content)
    monkeypatch.setenv("MAX_TOOL_ITERATIONS", "6")
    settings = load_settings(path)
    assert settings.max_tool_iterations == 6
    assert settings.provider_ready()
    assert path.read_text() == content


def test_empty_template_keeps_defaults(tmp_path):
    path = tmp_path / ".env"
    path.write_text("LLM_PROVIDER=\nLLM_MODEL=\nTOOL_TIMEOUT_SECONDS=\n")
    settings = load_settings(path)
    assert settings.llm_model == "openrouter/free"
    assert settings.tool_timeout_seconds == 30


def test_provider_specific_model_is_respected(tmp_path):
    path = tmp_path / ".env"
    path.write_text("OPENROUTER_MODEL=example/configured:free\n")
    assert load_settings(path).llm_model == "example/configured:free"


def test_generic_model_overrides_provider_model():
    settings = Settings(llm_model="example/selected:free", openrouter_model="example/other:free")
    assert settings.llm_model == "example/selected:free"


@pytest.mark.parametrize("field,value", [("tool_timeout_seconds", 0), ("max_tool_iterations", 99)])
def test_invalid_execution_bounds(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


@pytest.mark.parametrize("field", ["kubernetes_namespace", "kubernetes_context"])
def test_unrelated_cluster_scope_is_rejected(field):
    with pytest.raises(ValidationError):
        Settings(**{field: "unrelated"})


@pytest.mark.parametrize("model", ["openrouter/auto", "some/paid-model", ""])
def test_paid_or_implicit_openrouter_model_is_rejected(model):
    with pytest.raises(ValidationError):
        Settings(llm_model=model)


def test_other_provider_key_is_not_used_as_fallback():
    settings = Settings(gemini_api_key="test-sentinel")
    assert not settings.provider_ready()


def test_safe_summary_and_repr_exclude_secrets():
    settings = Settings(openrouter_api_key="test-sentinel", airflow_password="password-sentinel")
    output = str(settings.safe_summary()) + repr(settings)
    assert "test-sentinel" not in output
    assert "password-sentinel" not in output
    assert settings.safe_summary()["provider_key_present"] is True


def test_invalid_url_diagnostic_hides_input(tmp_path):
    path = tmp_path / ".env"
    path.write_text("AIRFLOW_BASE_URL=http://user:private-sentinel@localhost\n")
    with pytest.raises(ConfigurationError) as info:
        load_settings(path)
    assert "airflow_base_url" in str(info.value)
    assert "private-sentinel" not in str(info.value)


def test_invalid_secret_type_diagnostic_hides_input(tmp_path):
    path = tmp_path / ".env"
    path.write_text("TOOL_TIMEOUT_SECONDS=private-sentinel\n")
    with pytest.raises(ConfigurationError) as info:
        load_settings(path)
    assert "private-sentinel" not in str(info.value)
