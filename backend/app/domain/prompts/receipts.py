# Generation receipts: proof that the backend produced a prompt's text.
#
# The onboarding flow generates prompts from verified brand-website evidence
# and then persists them through the ordinary manual-create endpoint. Those
# prompts must skip the topical-binding gate — binding is word-overlap against
# the project's stored vocabulary, and a correct measurement prompt is
# brand-NEUTRAL by design (the same text is run for the brand AND its
# competitors, so a prompt naming the brand measures nothing). Correct prompts
# therefore bind only on category wording, and legitimate synonyms
# ("agencies offering experimentation services" vs "digital marketing") share
# no literal token.
#
# But ``origin`` arrives in the request body, so a client could simply claim
# ``generated`` and bypass the gate for arbitrary text. A receipt closes that:
# the suggestion endpoints return an HMAC over each prompt's NORMALIZED text,
# and ``create_prompt`` honours the exemption only when the receipt verifies.
# Forging one requires the signing secret, so the gate still holds for every
# text the backend did not itself generate.
#
from __future__ import annotations

import hmac
import uuid
from hashlib import sha256

from app.core.config import settings
from app.domain.prompts.normalization import prompt_text_hash

# Domain separation: this key must never collide with another HMAC use of the
# same secret.
_RECEIPT_CONTEXT = b"citeladder.prompt-generation-receipt.v2"


def _receipt_message(
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
    cohort: str,
    text: str,
) -> bytes:
    values = (
        str(workspace_id),
        str(project_id),
        str(prompt_set_id),
        cohort,
        prompt_text_hash(text),
    )
    return (
        _RECEIPT_CONTEXT + b"\0" + b"\0".join(value.encode("utf-8") for value in values)
    )


def issue_prompt_receipt(
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
    cohort: str,
    text: str,
) -> str:
    """Mint a receipt bound to one generated prompt destination and cohort.

    Keyed on the normalized text hash (the same canonical form the DB uniqueness
    constraint uses), so trivial whitespace/case edits do not invalidate a
    receipt while a genuine text change does.
    """
    message = _receipt_message(
        workspace_id=workspace_id,
        project_id=project_id,
        prompt_set_id=prompt_set_id,
        cohort=cohort,
        text=text,
    )
    return hmac.new(
        settings.jwt_secret_key.encode("utf-8"), message, sha256
    ).hexdigest()


def verify_prompt_receipt(
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
    cohort: str,
    text: str,
    receipt: str | None,
) -> bool:
    """Whether ``receipt`` matches every generated-prompt binding.

    Constant-time comparison; a missing or malformed receipt is simply False
    (the caller then applies the ordinary binding gate).
    """
    if not receipt:
        return False
    expected = issue_prompt_receipt(
        workspace_id=workspace_id,
        project_id=project_id,
        prompt_set_id=prompt_set_id,
        cohort=cohort,
        text=text,
    )
    return hmac.compare_digest(expected, str(receipt))
