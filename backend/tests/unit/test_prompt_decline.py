from app.analysis.service import _decline_is_confirmed


def test_decline_requires_three_of_a_full_four_movement_window() -> None:
    common = {
        "immediate_delta": -8.0,
        "declining_engines": 2,
        "repetitions_confirm": True,
    }
    assert not _decline_is_confirmed(recent_deltas=[-8, -7, -6], **common)
    assert _decline_is_confirmed(recent_deltas=[-8, -7, 1, -6], **common)


def test_decline_requires_current_cross_engine_and_repetition_evidence() -> None:
    movements = [-8.0, -7.0, 1.0, -6.0]
    assert not _decline_is_confirmed(
        immediate_delta=1.0,
        recent_deltas=movements,
        declining_engines=2,
        repetitions_confirm=True,
    )
    assert not _decline_is_confirmed(
        immediate_delta=-8.0,
        recent_deltas=movements,
        declining_engines=1,
        repetitions_confirm=True,
    )
    assert not _decline_is_confirmed(
        immediate_delta=-8.0,
        recent_deltas=movements,
        declining_engines=2,
        repetitions_confirm=False,
    )
