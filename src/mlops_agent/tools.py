"""Provider-neutral structured tool registry and secret-safe result envelope."""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    tool: str
    observed_at: datetime
    status: Literal["ok", "invalid_request", "unavailable", "error"]
    evidence: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: float = Field(ge=0)


class ToolFailure(Exception):
    def __init__(self, message: str, status: Literal["unavailable", "error"] = "error"):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[ToolInput]
    handler: Callable[[Any], dict[str, Any]]
    output_model: type[ToolResult] = ToolResult

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_model.model_json_schema(),
            "output_schema": self.output_model.model_json_schema(),
        }


class ToolRegistry:
    def __init__(self, definitions: list[ToolDefinition]):
        self.tools = {item.name: item for item in definitions}
        if len(self.tools) != len(definitions):
            raise ValueError("Duplicate tool name")

    def call(self, name: str, arguments: dict, request_id: str | None = None) -> ToolResult:
        started = time.monotonic()
        evidence: dict[str, Any] = {}
        error = None
        status = "ok"
        definition = self.tools.get(name)
        try:
            if definition is None:
                raise ToolFailure("Tool is not registered", "unavailable")
            validated = definition.input_model.model_validate(arguments)
            candidate = definition.handler(validated)
            try:
                if not isinstance(candidate, dict):
                    raise TypeError
                json.dumps(candidate, allow_nan=False)
            except (TypeError, ValueError):
                raise ToolFailure("Tool returned invalid JSON evidence") from None
            evidence = candidate
        except (ValidationError, ValueError):
            status, error = "invalid_request", "Invalid tool arguments or disallowed path/revision"
        except ToolFailure as exc:
            status, error = exc.status, str(exc)
        except Exception:
            # Exception payloads can contain service credentials or command output.
            status, error = "error", "Tool failed; no operational facts are available"
        result = ToolResult(
            request_id=request_id or str(uuid4()),
            tool=name if definition else "unregistered",
            observed_at=datetime.now(UTC),
            status=status,
            evidence=evidence,
            error=error,
            duration_ms=(time.monotonic() - started) * 1000,
        )
        logging.getLogger(__name__).info(
            "tool_result",
            extra={
                "tool": result.tool,
                "status": result.status,
                "duration_ms": result.duration_ms,
                "request_id": result.request_id,
            },
        )
        return result
