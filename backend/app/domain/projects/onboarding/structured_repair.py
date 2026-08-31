"""Bounded repair loop for evidence-grounded onboarding model responses."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

from pydantic import BaseModel, ValidationError

from app.connectors.agent.gateway import ModelGateway
from app.connectors.answer_engines.errors import ProviderError
from app.core.config.brand_discovery import brand_discovery_settings


async def complete_validated_envelope[EnvelopeT: BaseModel](
    client: ModelGateway,
    *,
    system: str,
    user: str,
    schema_name: str,
    envelope_type: type[EnvelopeT],
    validate: Callable[[EnvelopeT], None],
) -> EnvelopeT:
    """Generate, validate, and boundedly repair one structured response.

    Schema or evidence-reference failures receive concise validation feedback on
    the next attempt. Retryable provider failures retain that repair context and
    honor the provider/configured backoff without weakening deterministic gates.
    """
    attempt_user = user
    maximum_attempts = brand_discovery_settings.synthesis_max_attempts
    for attempt in range(maximum_attempts):
        try:
            raw = await client.complete_structured_json(
                system=system,
                user=attempt_user,
                schema_name=schema_name,
                schema=envelope_type.model_json_schema(),
            )
            envelope = envelope_type.model_validate_json(raw)
            validate(envelope)
            return envelope
        except ProviderError as exc:
            if not exc.retryable or attempt + 1 >= maximum_attempts:
                raise
            delay = brand_discovery_settings.synthesis_retry_delay(
                attempt, retry_after_seconds=exc.retry_after_seconds
            )
        except (ValidationError, ValueError) as exc:
            if attempt + 1 >= maximum_attempts:
                raise
            attempt_user = _repair_request(user, exc)
            continue
        await asyncio.sleep(delay)
    raise RuntimeError("structured onboarding attempts exhausted")


def _repair_request(user: str, exc: ValidationError | ValueError) -> str:
    feedback = {
        "instruction": (
            "Regenerate the complete response. Correct every validation error, "
            "use only identifiers and evidence references supplied in the request, "
            "and return no commentary outside the JSON object."
        ),
        "validation_errors": _validation_errors(exc),
    }
    encoded = json.dumps(feedback, separators=(",", ":"))
    return f"{user}\n\nCORRECTION_REQUIRED:\n{encoded}"


def _validation_errors(exc: ValidationError | ValueError) -> list[dict[str, str]]:
    if isinstance(exc, ValidationError):
        return [
            {
                "path": ".".join(str(part) for part in item["loc"]),
                "type": str(item["type"]),
                "message": str(item["msg"])[:300],
            }
            for item in exc.errors(include_input=False, include_url=False)[:10]
        ]
    return [{"path": "response", "type": "contract_error", "message": str(exc)[:300]}]
