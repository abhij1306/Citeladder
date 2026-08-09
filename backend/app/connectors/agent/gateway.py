"""Provider-neutral model gateway contracts and deterministic fake adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.config.provider_catalog import ERROR_CONNECTION


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    structured_output: bool
    native_tool_calling: bool
    context_limit: int
    output_limit: int
    content_types: tuple[str, ...] = ("text",)
    streaming: bool = False
    usage_reporting: bool = True
    safety_metadata: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "structured_output": self.structured_output,
            "native_tool_calling": self.native_tool_calling,
            "context_limit": self.context_limit,
            "output_limit": self.output_limit,
            "content_types": list(self.content_types),
            "streaming": self.streaming,
            "usage_reporting": self.usage_reporting,
            "safety_metadata": self.safety_metadata,
        }


@dataclass(frozen=True, slots=True)
class ModelResult:
    content: str
    provider_adapter: str
    endpoint_host: str
    requested_model: str
    returned_model: str
    finish_status: str
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0
    safety: dict[str, Any] = field(default_factory=dict)


class ModelGateway(Protocol):
    @property
    def adapter_name(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def base_url_host(self) -> str: ...

    def validate_configuration(self) -> None: ...

    def capabilities(self) -> ModelCapabilities: ...

    async def complete_text(self, *, system: str, user: str) -> ModelResult: ...

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
        schema: dict[str, Any],
    ) -> ModelResult: ...

    async def complete_json(self, *, system: str, user: str) -> str: ...

    async def complete_structured_json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
        schema: dict[str, Any],
    ) -> str: ...

    @staticmethod
    def normalize_usage(value: object) -> dict[str, int]: ...

    @staticmethod
    def classify_error(exc: Exception) -> dict[str, Any]: ...


class FakeModelGateway:
    """CI adapter with fixed output and full provenance; never performs I/O."""

    def __init__(self, content: str = "{}", *, model: str = "fake-agent-v1") -> None:
        self._content = content
        self._model = model
        self.calls: list[dict[str, Any]] = []

    @property
    def adapter_name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return self._model

    @property
    def base_url_host(self) -> str:
        return "fake.invalid"

    def validate_configuration(self) -> None:
        return None

    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            structured_output=True,
            native_tool_calling=False,
            context_limit=32_000,
            output_limit=4_096,
        )

    async def complete_text(self, *, system: str, user: str) -> ModelResult:
        self.calls.append({"kind": "text", "system": system, "user": user})
        return self._result()

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
        schema: dict[str, Any],
    ) -> ModelResult:
        self.calls.append(
            {
                "kind": "structured",
                "system": system,
                "user": user,
                "schema_name": schema_name,
                "schema": schema,
            }
        )
        return self._result()

    async def complete_json(self, *, system: str, user: str) -> str:
        return (await self.complete_text(system=system, user=user)).content

    async def complete_structured_json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
        schema: dict[str, Any],
    ) -> str:
        return (
            await self.complete_structured(
                system=system,
                user=user,
                schema_name=schema_name,
                schema=schema,
            )
        ).content

    @staticmethod
    def normalize_usage(value: object) -> dict[str, int]:
        if not isinstance(value, Mapping):
            return {}
        return {
            key: int(value[key])
            for key in ("input_tokens", "output_tokens", "total_tokens")
            if isinstance(value.get(key), int) and value[key] >= 0
        }

    @staticmethod
    def classify_error(exc: Exception) -> dict[str, Any]:
        return {
            "code": str(getattr(exc, "error_code", ERROR_CONNECTION)),
            "retryable": bool(getattr(exc, "retryable", False)),
        }

    def _result(self) -> ModelResult:
        return ModelResult(
            content=self._content,
            provider_adapter="fake",
            endpoint_host=self.base_url_host,
            requested_model=self.model,
            returned_model=self.model,
            finish_status="stop",
            usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
