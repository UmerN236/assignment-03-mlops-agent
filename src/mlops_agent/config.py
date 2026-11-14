"""Validated configuration with secret-safe diagnostics and no service side effects."""

import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(ValueError):
    """Safe to display: contains field names and fixed messages, never input values."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None, extra="ignore", env_ignore_empty=True, hide_input_in_errors=True
    )

    llm_provider: Literal["openrouter", "gemini"] = "openrouter"
    llm_model: str | None = None
    openrouter_model: str = "openrouter/free"
    gemini_model: str | None = None
    openrouter_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    tool_timeout_seconds: float = Field(default=30, ge=1, le=120)
    llm_timeout_seconds: float = Field(default=60, ge=1, le=180)
    max_tool_iterations: int = Field(default=8, ge=1, le=16)
    mlflow_tracking_uri: str = "http://127.0.0.1:5000"
    airflow_base_url: str = "http://127.0.0.1:8080"
    airflow_username: str = "admin"
    airflow_password: SecretStr | None = None
    airflow_token: SecretStr | None = None
    airflow_training_dag_id: str = "assignment_training"
    kubeconfig: Path = Path(".local/kubeconfig")
    kubernetes_readonly_kubeconfig: Path = Path(".local/kubeconfig-agent")
    kubernetes_context: Literal["kind-mlops-assignment3"] = "kind-mlops-assignment3"
    kubernetes_namespace: Literal["mlops-agent"] = "mlops-agent"
    dvc_repo_path: Path = Path(".")

    @field_validator("mlflow_tracking_uri", "airflow_base_url")
    @classmethod
    def service_url(cls, value: str) -> str:
        try:
            url = urlsplit(value)
            valid = (
                url.scheme in {"http", "https"}
                and bool(url.hostname)
                and not url.username
                and not url.password
                and not url.query
                and not url.fragment
            )
            _ = url.port
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Use an HTTP(S) service URL without credentials, query or fragment")
        return value.rstrip("/")

    @model_validator(mode="after")
    def free_model_only(self) -> "Settings":
        if self.llm_model is None:
            self.llm_model = (
                self.openrouter_model if self.llm_provider == "openrouter" else self.gemini_model
            )
        if self.llm_provider == "openrouter" and not (
            self.llm_model == "openrouter/free"
            or (self.llm_model is not None and self.llm_model.endswith(":free"))
        ):
            raise ValueError("OpenRouter requires an explicitly free model")
        if self.llm_provider == "gemini" and (
            not self.llm_model or self.llm_model == "openrouter/free"
        ):
            raise ValueError("Gemini requires an explicitly configured free-tier model")
        return self

    def provider_ready(self) -> bool:
        key = self.openrouter_api_key if self.llm_provider == "openrouter" else self.gemini_api_key
        return key is not None and bool(key.get_secret_value().strip())

    def require_provider(self) -> None:
        if not self.provider_ready():
            name = "OPENROUTER_API_KEY" if self.llm_provider == "openrouter" else "GEMINI_API_KEY"
            raise ConfigurationError(f"Missing {name}; live LLM requests are unavailable")

    def safe_summary(self) -> dict[str, str | bool | int]:
        # Deliberate allowlist. Never serialize the complete settings object for logs.
        return {
            "provider": self.llm_provider,
            "provider_key_present": self.provider_ready(),
            "airflow_credential_present": bool(self.airflow_token or self.airflow_password),
            "namespace": self.kubernetes_namespace,
            "context": self.kubernetes_context,
            "max_tool_iterations": self.max_tool_iterations,
        }


def load_settings(env_file: Path | None = Path(".env")) -> Settings:
    """Load without modifying the file; environment variables take precedence."""
    try:
        return Settings(_env_file=env_file)
    except ValidationError as exc:
        fields = sorted({str(e["loc"][0]) if e["loc"] else "configuration" for e in exc.errors()})
        raise ConfigurationError("Invalid configuration fields: " + ", ".join(fields)) from None


def main() -> None:
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from None
    print(json.dumps(settings.safe_summary(), sort_keys=True))
