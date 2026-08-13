from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.domain.commerce.matching import match_candidate
from app.domain.commerce.review import _comparison_artifact_ids


def test_gtin_precedes_all_other_identity_evidence() -> None:
    target_id = uuid.uuid4()
    results = match_candidate(
        {"name": "Trail Shoe", "attributes": {"gtin": "0123456789012"}},
        [
            {
                "id": target_id,
                "name": "A different title",
                "attributes": {"gtin": "0123456789012", "brand": "North"},
            }
        ],
    )

    assert results[0].target_id == target_id
    assert results[0].confidence == 1.0
    assert results[0].reasons == ("gtin",)
    assert results[0].review_required is False


def test_comparison_artifact_ids_are_unique_and_sorted() -> None:
    first = uuid.UUID("00000000-0000-0000-0000-000000000001")
    second = uuid.UUID("00000000-0000-0000-0000-000000000002")
    own = [SimpleNamespace(source_artifact_id=second)]
    competitors = [
        SimpleNamespace(source_artifact_id=first),
        SimpleNamespace(source_artifact_id=second),
        SimpleNamespace(source_artifact_id=None),
    ]
    assert _comparison_artifact_ids(own, competitors) == [str(first), str(second)]


def test_brand_model_precedes_family_and_similarity() -> None:
    results = match_candidate(
        {
            "name": "Boreal Trail Shoe",
            "attributes": {"brand": "Boreal", "mpn": "TR-42", "family": "trail"},
        },
        [
            {
                "id": uuid.uuid4(),
                "name": "Boreal shoe",
                "attributes": {"brand": "Boreal", "mpn": "TR-42", "family": "trail"},
            }
        ],
    )

    assert results[0].reasons == ("brand_model",)
    assert results[0].confidence == 0.96


def test_equal_high_confidence_matches_require_explicit_review() -> None:
    results = match_candidate(
        {
            "name": "Boreal Trail Shoe",
            "attributes": {"brand": "Boreal", "mpn": "TR-42"},
        },
        [
            {
                "id": uuid.uuid4(),
                "name": "Boreal Trail Shoe",
                "attributes": {"brand": "Boreal", "mpn": "TR-42"},
            },
            {
                "id": uuid.uuid4(),
                "name": "Boreal Trail Shoe Two",
                "attributes": {"brand": "Boreal", "mpn": "TR-42"},
            },
        ],
    )

    assert len(results) == 2
    assert all(result.review_required for result in results)
