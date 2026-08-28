"""Pure recognition-event policy; intentionally independent of Flask and OpenCV."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

from .domain import EventSource, RecognitionObservation

UTC = timezone.utc
POLICY_VERSION = "1"


@dataclass(frozen=True, slots=True)
class StableMatch:
    identity_id: str | None
    accepted_count: int
    sample_count: int


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    accepted: bool
    reason: str
    identity_id: str | None = None
    occurred_at: datetime | None = None
    idempotency_key: str | None = None


def normalize_event_timestamp(value: datetime) -> datetime:
    """Return an aware UTC timestamp; naive input is explicitly interpreted as UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def passes_observation_gates(observation: RecognitionObservation) -> bool:
    return bool(observation.identity_id and observation.liveness_passed and observation.quality_passed)


def aggregate_stable_identity(
    observations: Sequence[RecognitionObservation],
    *,
    window_size: int = 5,
    required_count: int = 3,
) -> StableMatch:
    """Accept only one unambiguous identity meeting the stable window threshold."""
    if window_size <= 0 or required_count <= 0 or required_count > window_size:
        raise ValueError("invalid stable-match window")
    window = tuple(observations[-window_size:])
    counts = Counter(
        observation.identity_id
        for observation in window
        if passes_observation_gates(observation)
    )
    if not counts:
        return StableMatch(None, 0, len(window))
    top = counts.most_common()
    identity_id, count = top[0]
    tied = len(top) > 1 and top[1][1] == count
    if tied or count < required_count:
        return StableMatch(None, count, len(window))
    return StableMatch(identity_id, count, len(window))


def is_active_authorized_user(identity_id: str | None, active_user_ids: Iterable[str]) -> bool:
    return bool(identity_id and identity_id in set(active_user_ids))


def cooldown_allows(
    last_event_at: datetime | None,
    occurred_at: datetime,
    cooldown_seconds: int,
) -> bool:
    if cooldown_seconds < 0:
        raise ValueError("cooldown_seconds must be non-negative")
    if last_event_at is None:
        return True
    last = normalize_event_timestamp(last_event_at)
    current = normalize_event_timestamp(occurred_at)
    if current < last:
        return False
    return current - last >= timedelta(seconds=cooldown_seconds)


def generate_idempotency_key(
    *,
    user_id: str,
    site_id: str,
    camera_id: str,
    occurred_at: datetime,
    source: EventSource = EventSource.FACE_ENCOUNTER,
    model_version: str,
    policy_version: str = POLICY_VERSION,
) -> str:
    normalized_time = normalize_event_timestamp(occurred_at).isoformat()
    canonical = "\x1f".join((user_id, site_id, camera_id, normalized_time, source.value, model_version, policy_version))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def safe_rejection(reason: str) -> PolicyDecision:
    """Create a rejection without exposing confidence or biometric details."""
    return PolicyDecision(accepted=False, reason=reason)


def evaluate_encounter(
    observations: Sequence[RecognitionObservation],
    *,
    active_user_ids: Iterable[str],
    occurred_at: datetime,
    site_id: str,
    camera_id: str,
    last_event_at: datetime | None,
    cooldown_seconds: int,
    model_version: str,
    policy_version: str = POLICY_VERSION,
    window_size: int = 5,
    required_count: int = 3,
) -> PolicyDecision:
    """Apply stable match, authorization, and cooldown gates in a deterministic order."""
    match = aggregate_stable_identity(
        observations, window_size=window_size, required_count=required_count
    )
    if match.identity_id is None:
        return safe_rejection("stable-match-not-established")
    if not is_active_authorized_user(match.identity_id, active_user_ids):
        return safe_rejection("identity-not-authorized")
    normalized_time = normalize_event_timestamp(occurred_at)
    if not cooldown_allows(last_event_at, normalized_time, cooldown_seconds):
        return safe_rejection("cooldown-active")
    key = generate_idempotency_key(
        user_id=match.identity_id,
        site_id=site_id,
        camera_id=camera_id,
        occurred_at=normalized_time,
        model_version=model_version,
        policy_version=policy_version,
    )
    return PolicyDecision(True, "recognized-event-eligible", match.identity_id, normalized_time, key)
