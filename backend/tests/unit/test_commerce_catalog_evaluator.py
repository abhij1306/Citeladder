from evaluations.commerce_catalog import evaluate_catalog


def test_catalog_evaluator_reports_false_results_and_collisions() -> None:
    observed = {
        "products": [
            {"canonical_url": "https://shop.test/one"},
            {"canonical_url": "https://shop.test/one"},
            {"canonical_url": "https://shop.test/extra"},
        ]
    }
    reference = {
        "products": [
            {"canonical_url": "https://shop.test/one"},
            {"canonical_url": "https://shop.test/missing"},
        ]
    }
    report = evaluate_catalog(observed, reference)
    assert report["false_positives"] == ["https://shop.test/extra"]
    assert report["false_negatives"] == ["https://shop.test/missing"]
    assert report["identity_collisions"] == ["https://shop.test/one"]
    assert report["passed"] is False
