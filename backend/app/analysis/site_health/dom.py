"""Shared DOM-traversal helpers for the Site Health fact extractors.

Extraction is deliberately **fail-open**: hostile or malformed HTML must
persist whatever partial facts were readable rather than crash the analyze
task (see ``test_malformed_html_never_crashes``). That contract is not the
same as *silence*. Before this module, ``parser``, ``fact_links``, and
``fact_signals`` each re-derived it with a byte-identical ``_text`` copy and
bare ``except Exception: pass``, so a genuine bug in a traversal was
indistinguishable from a page that really had no title, no CTAs, and no
forms — and the rules then scored that bug as a content gap.

One owner, one exception set, one log line. Callers still choose what a
failed read means for their bucket; they no longer choose whether anyone
finds out.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from lxml import etree

logger = logging.getLogger("app.analysis.site_health.dom")

#: Errors a DOM read may raise on real-world input and still fail open.
#:
#: ``etree.Error`` is lxml's base (XPath evaluation, parser, and serialization
#: failures). ``AttributeError`` covers nodes that are not elements — comments
#: and processing instructions have no ``text_content``/``getparent``.
#: ``TypeError``/``ValueError`` cover the string and URL handling wrapped
#: around those reads. Anything OUTSIDE this set is a bug, and it propagates:
#: the fail-open contract exists for bad HTML, not for bad code.
DOM_ERRORS: Final = (etree.Error, AttributeError, TypeError, ValueError)


def dom_failure(operation: str, exc: BaseException) -> None:
    """Record one failed DOM read at debug, then let the caller fail open.

    Called on every swallowed traversal so an empty fact bucket caused by an
    error is separable from an empty bucket caused by an empty page. Debug
    level because a malformed page is expected traffic, not an incident.
    """
    logger.debug(
        "site-health DOM read failed; continuing with partial facts",
        exc_info=True,
        extra={"operation": operation, "error_type": type(exc).__name__},
    )


def node_text(node: Any) -> str:
    """Stripped ``text_content()`` for one node, or ``""`` when unreadable."""
    try:
        return (node.text_content() or "").strip()
    except DOM_ERRORS as exc:
        dom_failure("node_text", exc)
        return ""


def xpath(root: Any, expression: str) -> list[Any]:
    """Evaluate ``expression``, returning ``[]`` when the read fails.

    The empty list is the fail-open value every caller already used; the
    difference is that reaching it now leaves a trace.
    """
    try:
        return list(root.xpath(expression))
    except DOM_ERRORS as exc:
        dom_failure(f"xpath:{expression}", exc)
        return []
