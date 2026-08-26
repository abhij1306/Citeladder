from evaluations.commerce_catalog import evaluate_catalog


def _reference() -> dict:
    return {
        "dataset_id": "dated-reference",
        "crawl_date": "2026-08-26",
        "categories": [
            {
                "name": "Shoes",
                "url": "https://shop.test/shoes",
                "products": [
                    {
                        "product_url": "https://shop.test/one",
                        "product_title": "Trail One",
                        "current_price_aud": 19.0,
                        "product_identifier": "STYLE-1",
                    },
                    {
                        "product_url": "https://shop.test/missing",
                        "product_title": "Missing",
                        "current_price_aud": 29.0,
                    },
                ],
            }
        ],
    }


def test_catalog_evaluator_flattens_reference_and_reports_diagnostics() -> None:
    observed = {
        "categories": [
            {
                "id": "category-1",
                "name": "Shoes",
                "canonical_url": "https://shop.test/shoes",
            }
        ],
        "products": [
            {
                "canonical_url": "https://shop.test/one",
                "name": "Trail One",
                "price": 20.0,
                "sku": "STYLE-1",
                "field_sources": {},
                "category_ids": ["category-1"],
            },
            {"canonical_url": "https://shop.test/one"},
            {"canonical_url": "https://shop.test/shoes"},
        ],
    }

    report = evaluate_catalog(observed, _reference())

    assert report["reference_urls"]["reference_count"] == 2
    assert report["reference_urls"]["missing"] == ["https://shop.test/missing"]
    assert report["duplicate_canonical_products"] == ["https://shop.test/one"]
    assert report["category_urls_emitted_as_products"] == ["https://shop.test/shoes"]
    assert report["prices"]["changed_count"] == 1
    assert report["identifier_provenance_violations"] == [
        {
            "canonical_url": "https://shop.test/one",
            "field": "sku",
            "value": "STYLE-1",
        }
    ]
    assert report["acquisition_unavailable"]["state"] == "unavailable_in_export"
    assert "passed" not in report


def test_catalog_evaluator_treats_reference_mismatch_as_diagnostic_data() -> None:
    report = evaluate_catalog({"products": [], "categories": []}, _reference())

    assert report["reference_urls"]["observed_count"] == 0
    assert report["reference_urls"]["missing"]
    assert "passed" not in report
