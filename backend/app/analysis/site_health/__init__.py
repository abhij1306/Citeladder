# Site Health deep analysis package (Task 5).
#
# Pure, deterministic building blocks composed by ``page_analysis`` to turn
# one fetched page into analysis evidence that the worker persists:
#
#   - ``parser`` — bounded HTML/delivery fact extraction (lxml, hardened).
#   - ``structured_data`` — JSON-LD / microdata parse + required-property
#     validation against the config-owned schema map.
#   - ``page_analysis`` — the classification, traits, evaluation, and scoring
#     interface used by workers and end-to-end fixture contracts.
#   - ``rules`` — evaluate the config-owned rule catalog into explicit
#     measurement outcomes with exact evidence + provenance.
#   - ``scoring`` — deterministic Web Fundamentals and AEO Readiness
#     measurement plus crawl-level aggregation.
#
# Everything here is a PURE function (no I/O, no ORM): the worker owns all
# persistence, transactions, and lifecycle. Determinism is preserved so the
# same bytes always yield the same facts/evaluations/measurements (invariant 9).
from __future__ import annotations
