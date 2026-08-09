from app.domain.site_health.comparison import action_resolution_state


def test_action_resolution_requires_observed_passing_evidence() -> None:
    assert action_resolution_state(["pass", "pass"]) == "verified"
    assert action_resolution_state(["pass", "fail"]) == "partial"
    assert action_resolution_state(["pass", None]) == "partial"
    assert action_resolution_state(["fail", None]) == "unresolved"
    assert action_resolution_state([None]) == "unresolved"
    assert action_resolution_state([]) == "unresolved"
