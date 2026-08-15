import uuid

from app.analysis.site_health.change_intel import (
    ChangePage,
    ExpectedChange,
    RuleState,
    compare_crawls,
)


def _page(*, title: str = "Same", status: int = 200) -> ChangePage:
    return ChangePage(
        site_url_id=uuid.UUID(int=1),
        normalized_url="https://example.com/page",
        analysis_id=uuid.uuid4(),
        artifact_id=uuid.uuid4(),
        fields={
            "title": title,
            "meta_description": "Description",
            "h1": "Heading",
            "canonical": "https://example.com/page",
            "robots_noindex": False,
            "json_ld_present": True,
            "internal_link_count": 2,
            "http_status": status,
            "redirect_target": "https://example.com/page",
        },
        rules={
            "title": RuleState("pass", "high", uuid.uuid4()),
        },
        intended_indexable=True,
    )


def test_noop_pair_has_zero_false_regressions() -> None:
    before = _page()
    after = ChangePage(
        **{
            **before.__dict__,
            "analysis_id": uuid.uuid4(),
            "artifact_id": uuid.uuid4(),
        }
    )
    assert compare_crawls([before], [after], complete_pair=True) == ()


def test_classifies_rule_http_and_exact_expected_linkage() -> None:
    before = _page()
    event_id = uuid.uuid4()
    after = _page(title="Missing", status=503)
    after = ChangePage(
        **{
            **after.__dict__,
            "rules": {"title": RuleState("fail", "critical", uuid.uuid4())},
        }
    )
    changes = compare_crawls(
        [before],
        [after],
        complete_pair=True,
        expected={(after.site_url_id, "title"): ExpectedChange(event_id, "Missing")},
    )
    by_field = {item.field: item for item in changes}
    assert by_field["title"].change_class == "critical-regression"
    assert by_field["title"].expected is True
    assert by_field["title"].implementation_event_id == event_id
    assert by_field["http_status"].change_class == "critical-regression"


def test_redirect_target_is_an_explicit_neutral_change() -> None:
    before = _page()
    after = ChangePage(
        **{
            **before.__dict__,
            "analysis_id": uuid.uuid4(),
            "artifact_id": uuid.uuid4(),
            "fields": {
                **before.fields,
                "redirect_target": "https://example.com/destination",
            },
        }
    )
    changes = compare_crawls([before], [after], complete_pair=True)
    assert [(item.field, item.change_class) for item in changes] == [
        ("redirect_target", "neutral-change")
    ]


def test_partial_pair_suppresses_added_and_removed_claims() -> None:
    before = _page()
    added = ChangePage(
        **{
            **before.__dict__,
            "site_url_id": uuid.UUID(int=2),
            "normalized_url": "https://example.com/added",
        }
    )
    assert compare_crawls([before], [added], complete_pair=False) == ()
    fields = {
        item.field for item in compare_crawls([before], [added], complete_pair=True)
    }
    assert fields == {"url_presence"}
