"""Crawl failure summaries (SH-2/SH-5 — B1) + root-failure projection (SH-4 — B3).

The single owner of "why did this crawl fail": the worker's terminalization
writes ``SiteCrawl.error_message`` from it, and the read paths project the
same evidence as ``CrawlResponse.failure_summary`` and the pages/dashboard
``root_errors`` array. The source of truth is persisted rows only
(invariant 7): the crawl's root discover task plus its terminal root-target
``SiteFetchAttempt`` rows — one per REAL network call (invariant 3). A
failure is always a stable code + a human sentence + status/attempts when
present — never a bare ``http_4xx`` token.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health_acquisition import (
    ERROR_BOT_BLOCKED,
    ERROR_CONNECTION_FAILED,
    ERROR_DNS_RESOLUTION_FAILED,
    ERROR_HTTP_4XX,
    ERROR_HTTP_5XX,
    ERROR_MALFORMED_RESPONSE,
    ERROR_REDIRECT_LIMIT,
    ERROR_RESPONSE_TOO_LARGE,
    ERROR_ROBOTS_DENIED,
    ERROR_ROBOTS_UNAVAILABLE,
    ERROR_SSRF_BLOCKED,
    ERROR_TIMEOUT,
    ERROR_UNSUPPORTED_CONTENT_TYPE,
    FETCH_ATTEMPT_OUTCOME_ERROR,
)
from app.core.config.site_health_contracts import (
    TASK_KIND_DISCOVER,
)
from app.core.config.task_queue import TASK_STATUS_FAILED
from app.models.site_health import SiteCrawl, SiteCrawlTask, SiteFetchAttempt

# Human sentence per stable fetch error token (SH-5). HTTP 4xx/5xx are NOT
# here: their sentences name the terminal status code (and the attempt count
# for a retried 5xx), so they are composed by ``humanize_crawl_failure``.
_FAILURE_BASE_MESSAGES: Final[dict[str, str]] = {
    ERROR_DNS_RESOLUTION_FAILED: "The domain could not be resolved (DNS)",
    ERROR_CONNECTION_FAILED: "The site could not be reached (connection failed)",
    ERROR_TIMEOUT: "The site did not answer in time",
    ERROR_ROBOTS_DENIED: (
        "The site's robots.txt disallows the crawler from fetching the start URL"
    ),
    ERROR_ROBOTS_UNAVAILABLE: (
        "The site's robots.txt endpoint returned a server error, so fetching "
        "paused (a temporary disallow)"
    ),
    ERROR_BOT_BLOCKED: (
        "The site answered the start URL with a bot-protection challenge"
    ),
    ERROR_SSRF_BLOCKED: "The start URL is not permitted by the crawl safety policy",
    ERROR_REDIRECT_LIMIT: "The start URL redirected too many times",
    ERROR_RESPONSE_TOO_LARGE: "The start URL's response was too large to process",
    ERROR_UNSUPPORTED_CONTENT_TYPE: "The start URL did not return an HTML page",
    ERROR_MALFORMED_RESPONSE: "The site returned a response that could not be read",
}

# Fallback sentence for a failure with no (or an unrecognized) code — a crash
# or a legacy row. Still a sentence, never the bare code.
_FAILURE_GENERIC_MESSAGE: Final = "The crawl failed before it could fetch the start URL"


def humanize_crawl_failure(
    *, code: str, status_code: int | None, attempts: int | None
) -> str:
    """One uniform human sentence for a crawl failure (SH-5).

    The stable machine ``code`` travels alongside (``failure_summary.code``);
    this is the prose. An HTTP failure names the terminal status; a retried
    failure names the attempt count ("The site returned HTTP 500 after 4
    attempts"); an unrecognized code still gets a sentence.
    """
    tries = max(int(attempts or 0), 1)
    if code in (ERROR_HTTP_4XX, ERROR_HTTP_5XX) and status_code is not None:
        if code == ERROR_HTTP_5XX and tries > 1:
            return f"The site returned HTTP {status_code} after {tries} attempts"
        return f"The site returned HTTP {status_code} for the start URL"
    base = _FAILURE_BASE_MESSAGES.get(code)
    if base is None:
        return _FAILURE_GENERIC_MESSAGE
    if tries > 1:
        return f"{base} after {tries} attempts"
    return base


async def _root_discover_task(
    session: AsyncSession, crawl: SiteCrawl
) -> SiteCrawlTask | None:
    """The crawl's root discover task (depth 0), latest generation first.

    A root fetch failure never creates a ``SiteUrl`` row, so the task row +
    its fetch attempts are the ONLY evidence the crawl's start URL failed —
    which is exactly what the failure summary and ``root_errors`` project.
    """
    return await session.scalar(
        select(SiteCrawlTask)
        .where(
            SiteCrawlTask.crawl_id == crawl.id,
            SiteCrawlTask.task_kind == TASK_KIND_DISCOVER,
            SiteCrawlTask.depth == 0,
        )
        .order_by(SiteCrawlTask.generation.desc(), SiteCrawlTask.created_at.desc())
        .limit(1)
    )


async def load_root_failure_summary(
    session: AsyncSession, *, crawl: SiteCrawl
) -> dict | None:
    """The humanized failure summary for a failed crawl (B1), or ``None``.

    Shape: ``{code, message, attempts, status_code, target_url}`` — the same
    dict the worker reads ``error_message`` from at terminalization and the
    API projects as ``CrawlResponse.failure_summary``. ``None`` when the
    crawl's root discover task did not end terminally failed (a healthy or
    merely partial crawl has no root failure to summarize).
    """
    task = await _root_discover_task(session, crawl)
    if task is None or task.status != TASK_STATUS_FAILED:
        return None
    # The terminal call of the final queue attempt carries the classified
    # task-level token + status (e.g. http_4xx / 404, http_5xx / 500).
    terminal = await session.scalar(
        select(SiteFetchAttempt)
        .where(SiteFetchAttempt.task_id == task.id)
        .order_by(
            SiteFetchAttempt.attempt_number.desc(),
            SiteFetchAttempt.request_ordinal.desc(),
        )
        .limit(1)
    )
    code = (terminal.error_code if terminal is not None else "") or ""
    if not code:
        code = task.error_code or ""
    status_code = terminal.status_code if terminal is not None else None
    attempts = int(task.attempt_count or 0) or None
    return {
        "code": code,
        "message": humanize_crawl_failure(
            code=code, status_code=status_code, attempts=attempts
        ),
        "attempts": attempts,
        "status_code": status_code,
        "target_url": task.requested_url or crawl.root_url,
    }


async def load_root_errors(session: AsyncSession, *, crawl: SiteCrawl) -> list[dict]:
    """Project the crawl's terminal root-target fetch failures (SH-4 — B3).

    Read-only rows for the Errors & Blocked tab's failure block — one per
    REAL network call the root discover task lost, in call order. These are
    deliberately NOT page rows: no ``site_url_id`` exists for a URL the crawl
    never admitted, so they can never enter the cursored pages contract or
    carry a PageDetail link. Empty unless the root task ended terminally
    failed — a retried-then-succeeded root leaves no residue here (its
    intermediate rows describe a recovered hiccup, not an actionable
    failure).
    """
    task = await _root_discover_task(session, crawl)
    if task is None or task.status != TASK_STATUS_FAILED:
        return []
    rows = list(
        (
            await session.scalars(
                select(SiteFetchAttempt)
                .where(
                    SiteFetchAttempt.task_id == task.id,
                    SiteFetchAttempt.outcome == FETCH_ATTEMPT_OUTCOME_ERROR,
                )
                .order_by(
                    SiteFetchAttempt.attempt_number.asc(),
                    SiteFetchAttempt.request_ordinal.asc(),
                )
            )
        ).all()
    )
    target = task.requested_url or crawl.root_url
    return [
        {
            "method": row.method or "GET",
            "target": target,
            "outcome": row.outcome,
            "error_code": row.error_code or "",
            "status_code": row.status_code,
            "latency_ms": row.latency_ms,
        }
        for row in rows
    ]


__all__ = [
    "humanize_crawl_failure",
    "load_root_errors",
    "load_root_failure_summary",
]
