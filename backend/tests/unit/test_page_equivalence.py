from __future__ import annotations

import uuid

from app.domain.demand.page_equivalence import (
    PageCandidate,
    _artifact_proofs,
    _variant_urls,
)


class _Artifact:
    def __init__(self, requested: str, final: str, canonical: str = "") -> None:
        self.requested_url = requested
        self.final_url = final
        self.normalized_facts = {"canonical_url": canonical}


def test_variant_discovery_does_not_decode_or_merge_path_content() -> None:
    variants = _variant_urls("https://www.example.com/a%2Fb?x=1")
    assert "https://example.com/a%2Fb?x=1" in variants
    assert all("/a/b" not in value for value in variants)


def test_redirect_and_canonical_are_the_only_resolution_proofs() -> None:
    target_id = uuid.uuid4()
    source_id = uuid.uuid4()
    candidates = {
        "https://example.com/page": PageCandidate(target_id, "https://example.com/page"),
        "http://www.example.com/page/": PageCandidate(
            source_id, "http://www.example.com/page/"
        ),
    }
    proofs = _artifact_proofs(
        requested_url="http://www.example.com/page/",
        candidate_by_url=candidates,
        artifacts=[
            (
                _Artifact(
                    "http://www.example.com/page/",
                    "https://example.com/page",
                    "https://example.com/page",
                ),
                source_id,
            )
        ],
    )
    assert proofs == {target_id: {"redirect", "canonical"}}
