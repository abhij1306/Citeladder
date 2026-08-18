# Site Health domain DTOs used by the Task 3 discovery pipeline.
#
# Small, immutable value types shared by ``discovery``/``planner``/the worker.
# These are internal domain contracts (not HTTP request/response models — those
# arrive with the Task 6 API); they carry the deterministic frontier-ordering
# key and the bounded discovery output the worker persists.
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config.site_health_crawl_policy import (
    CORPUS_DISPOSITION_ANALYZE,
    CORPUS_DISPOSITION_VERSION,
    DISPOSITION_REASON_HTML_CONTENT,
    ITEM_KIND_HTML_PAGE,
)


@dataclass(frozen=True, slots=True)
class FrontierCandidate:
    """A canonical in-scope URL awaiting admission, with its ordering key.

    Deterministic frontier order is ``(parent_position, link_ordinal,
    url_hash)`` under the crawl's stored seed: the seed fixes the parent order
    and each parent lists its links in document order, so the same seed + same
    site always admits URLs in the same order (invariant 9).
    """

    url: str
    url_hash: str
    depth: int
    source_kind: str
    value_priority: int = 0
    parent_position: int = 0
    link_ordinal: int = 0
    # Corpus disposition decided at admission and carried to persistence, so a
    # document is inventoried without ever being handed to the HTML analyzer.
    disposition: str = CORPUS_DISPOSITION_ANALYZE
    disposition_reason: str = DISPOSITION_REASON_HTML_CONTENT
    disposition_version: str = CORPUS_DISPOSITION_VERSION
    item_kind: str = ITEM_KIND_HTML_PAGE
    # The admission verdict's value kind, carried rather than re-derived. The
    # admission that produced this candidate was scoped (root domain, globs);
    # a later bare ``classify_url_admission(url)`` is unscoped and can return a
    # DIFFERENT verdict for the same URL, so re-deriving it downstream risked
    # persisting a value kind that disagreed with the one used to admit.
    value_kind: str = "other"
    rewrite_reason: str = ""
    rewrite_version: str = ""

    @property
    def analyzable(self) -> bool:
        """Whether this candidate may receive an ``analyze`` task."""
        return self.disposition == CORPUS_DISPOSITION_ANALYZE

    @classmethod
    def from_admission(
        cls,
        admission,
        *,
        url: str,
        url_hash: str,
        depth: int,
        source_kind: str,
        parent_position: int = 0,
        link_ordinal: int = 0,
        rewrite_reason: str = "",
        rewrite_version: str = "",
    ) -> FrontierCandidate:
        """Build a candidate carrying one admission decision's full verdict.

        Every builder routes through here so priority and disposition can never
        drift apart — reading only ``.priority`` off an admission is what would
        silently hand a PDF to the HTML analyzer.
        """
        return cls(
            url=url,
            url_hash=url_hash,
            depth=depth,
            source_kind=source_kind,
            value_priority=admission.priority,
            parent_position=parent_position,
            link_ordinal=link_ordinal,
            rewrite_reason=rewrite_reason,
            rewrite_version=rewrite_version,
            disposition=admission.disposition,
            disposition_reason=admission.disposition_reason,
            disposition_version=admission.disposition_version,
            item_kind=admission.item_kind,
            value_kind=admission.value_kind,
        )

    @property
    def order_key(self) -> tuple[int, int, int, str]:
        return (
            -self.value_priority,
            self.parent_position,
            self.link_ordinal,
            self.url_hash,
        )


@dataclass(frozen=True, slots=True)
class DiscoveredLink:
    """One in-scope link extracted from a fetched page (document order)."""

    url: str
    url_hash: str
    ordinal: int
    rewrite_reason: str = ""
    rewrite_version: str = ""


@dataclass(frozen=True, slots=True)
class DiscoveryOutput:
    """The bounded result of executing one discover task.

    ``title``/``content_type``/``status_code``/``final_url`` describe the
    fetched page; ``links`` are the canonical in-scope links (already narrowed);
    ``redirect_chain`` records re-validated hops. The worker turns this into a
    ``SiteUrlObservation`` + admits ``links`` into the frontier.
    """

    requested_url: str
    final_url: str
    status_code: int | None
    content_type: str
    title: str
    links: tuple[DiscoveredLink, ...] = ()
    redirect_chain: tuple[dict, ...] = ()


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    """The outcome of a batched frontier admission attempt.

    TWO metrics, deliberately not collapsed into one — they answer different
    questions and one number cannot serve both:

    - ``admitted``: per-crawl identities this batch admitted for the FIRST time
      (a new queue slot, or a new ``SiteUrlObservation`` for a sample crawl).
      This is the frontier-ceiling and ``admitted_url_count`` metric, because
      it is what ``CrawlLifecycle.reconcile`` independently re-derives from the
      crawl's observation rows. Uniqueness is per CRAWL, not per project
      identity, so a recrawl of an already-known site still counts every URL.
    - ``observed``: every candidate whose identity resolved, including
      re-observations. This is the progress/telemetry number — a URL reached
      twice (a sitemap entry that is also linked from a page) is two
      observations of one admission.

    Counting re-observations toward the CEILING is what made a Starter crawl
    exhaust its frontier early and skip genuine URLs, while counting only new
    ``SiteUrl`` rows made a recrawl report zero progress. Splitting the two
    fixes the first without reintroducing the second.

    ``sample_capped`` is True when a Free crawl hit its workspace-wide
    allowance and admission stopped. ``site_url_ids`` maps
    ``url_hash -> SiteUrl.id`` for the URLs admitted (or already present) so
    the caller can write observations and enqueue child tasks.
    """

    admitted: int
    sample_capped: bool
    site_url_ids: dict[str, str] = field(default_factory=dict)
    observed: int = 0
