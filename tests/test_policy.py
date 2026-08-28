from datetime import datetime, timedelta, timezone

from lobby_attendance.domain import RecognitionObservation
from lobby_attendance.policy import (
    aggregate_stable_identity,
    cooldown_allows,
    evaluate_encounter,
    generate_idempotency_key,
    normalize_event_timestamp,
)

UTC = timezone.utc


def observation(identity="u-1", *, live=True, quality=True, second=0):
    return RecognitionObservation(datetime(2025, 1, 1, 12, 0, second, tzinfo=UTC), identity, live, quality)


def test_stable_three_of_five_accepts_only_gated_same_identity():
    result = aggregate_stable_identity([
        observation(),
        observation(live=False),
        observation(),
        observation("u-2"),
        observation(),
    ])
    assert result.identity_id == "u-1"
    assert result.accepted_count == 3
    assert result.sample_count == 5


def test_stable_match_rejects_tie_and_liveness_failure():
    result = aggregate_stable_identity([
        observation("u-1"), observation("u-1", quality=False),
        observation("u-2"), observation("u-2"), observation(None),
    ])
    assert result.identity_id is None


def test_encounter_rejects_unknown_and_cooldown_without_sensitive_detail():
    samples = [observation()] * 5
    now = datetime(2025, 1, 1, 12, 5, tzinfo=UTC)
    unknown = evaluate_encounter(
        samples, active_user_ids=set(), occurred_at=now, site_id="site", camera_id="cam",
        last_event_at=None, cooldown_seconds=300, model_version="mock-1",
    )
    assert not unknown.accepted
    assert unknown.reason == "identity-not-authorized"

    cooldown = evaluate_encounter(
        samples, active_user_ids={"u-1"}, occurred_at=now, site_id="site", camera_id="cam",
        last_event_at=now - timedelta(seconds=299), cooldown_seconds=300, model_version="mock-1",
    )
    assert not cooldown.accepted
    assert cooldown.reason == "cooldown-active"


def test_event_key_is_deterministic_and_timestamp_is_utc():
    naive = datetime(2025, 1, 1, 12, 0)
    aware = naive.replace(tzinfo=UTC)
    assert normalize_event_timestamp(naive) == aware
    assert generate_idempotency_key(
        user_id="u-1", site_id="site", camera_id="cam", occurred_at=naive, model_version="mock-1"
    ) == generate_idempotency_key(
        user_id="u-1", site_id="site", camera_id="cam", occurred_at=aware, model_version="mock-1"
    )
    decision = evaluate_encounter(
        [observation()] * 5, active_user_ids={"u-1"}, occurred_at=naive,
        site_id="site", camera_id="cam", last_event_at=None, cooldown_seconds=300,
        model_version="mock-1",
    )
    assert decision.accepted
    assert decision.occurred_at.tzinfo == UTC
    assert decision.idempotency_key


def test_cooldown_boundary_and_clock_rollback_are_safe():
    last = datetime(2025, 1, 1, tzinfo=UTC)
    assert not cooldown_allows(last, last + timedelta(seconds=299), 300)
    assert cooldown_allows(last, last + timedelta(seconds=300), 300)
    assert not cooldown_allows(last, last - timedelta(seconds=1), 0)
