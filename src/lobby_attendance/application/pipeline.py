"""Bounded capture orchestration; policy and persistence remain deterministic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

from ..config import Settings
from ..domain import RecognitionObservation
from ..policy import PolicyDecision, safe_rejection
from ..vision.protocol import VisionObservationProvider, VisionSample, VisionStatus
from .events import EventSubmission, RecognitionEventService

UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class InteractionResult:
    state: str
    samples: tuple[VisionSample, ...]
    submission: EventSubmission | None = None
    decision: PolicyDecision | None = None


class RecognitionPipeline:
    """Capture no more than five transient samples and submit one event decision."""

    def __init__(
        self,
        provider: VisionObservationProvider,
        event_service: RecognitionEventService,
        *,
        settings: Settings | None = None,
    ) -> None:
        self.provider = provider
        self.event_service = event_service
        self.settings = settings or Settings()

    def process_interaction(self, *, occurred_at: datetime | None = None) -> InteractionResult:
        started = datetime.now(UTC)
        until = started + timedelta(seconds=self.settings.interaction_timeout_seconds)
        raw_samples = _observe_provider(
            self.provider,
            until=until,
            interval_seconds=self.settings.sampling_interval_seconds,
        )
        samples = tuple(_coerce_sample(value) for value in raw_samples)
        samples = samples[: min(self.settings.capture_max_samples, 5)]
        if not samples:
            return InteractionResult("no-face", samples)
        if any(sample.status is VisionStatus.UNAVAILABLE for sample in samples):
            return InteractionResult("unavailable", samples)
        if all(sample.status is VisionStatus.NO_FACE for sample in samples):
            return InteractionResult("no-face", samples)
        if all(sample.status is VisionStatus.MULTIPLE_FACES for sample in samples):
            return InteractionResult("multiple-faces", samples)
        if all(sample.status is VisionStatus.LOW_QUALITY for sample in samples):
            return InteractionResult("low-quality", samples)
        if all(sample.status is VisionStatus.LIVENESS_FAILED for sample in samples):
            return InteractionResult("liveness-failed", samples)
        if all(sample.status in (VisionStatus.UNKNOWN, VisionStatus.AMBIGUOUS) for sample in samples):
            return InteractionResult("unknown", samples)

        invalid_statuses = {sample.status for sample in samples if sample.status is not VisionStatus.RECOGNIZED}
        if invalid_statuses:
            state = _mixed_rejection_state(invalid_statuses)
            return InteractionResult(state, samples, decision=safe_rejection("mixed-invalid-window"))

        observations = tuple(sample.observation for sample in samples)
        if len(observations) < self.settings.stable_window_size:
            return InteractionResult(
                "ambiguous", samples,
                decision=safe_rejection("stable-window-incomplete"),
            )
        submission = self.event_service.submit(
            observations,
            occurred_at=occurred_at or started,
            sample_window_size=self.settings.stable_window_size,
            required_count=self.settings.stable_required_count,
        )
        if self.settings.executive_demo_mode and submission.state in {"queued", "rejected"}:
            return InteractionResult("unavailable", samples, submission)
        state = {
            "recorded": "recognized-event-recorded",
            "queued": "event-queued-locally",
            "duplicate": "duplicate-suppressed",
            "suppressed": "cooldown-suppressed",
            "rejected": _rejection_state(samples, submission.reason),
        }[submission.state]
        return InteractionResult(state, samples, submission)


def _observe_provider(
    provider: VisionObservationProvider,
    *,
    until: datetime,
    interval_seconds: float,
):
    try:
        return provider.observe(until=until, interval_seconds=interval_seconds)
    except TypeError as exc:
        # Keep Phase 1 providers implementing only observe(until=...) compatible.
        if "interval_seconds" not in str(exc):
            raise
        return provider.observe(until=until)


def _coerce_sample(value: VisionSample | RecognitionObservation) -> VisionSample:
    if isinstance(value, VisionSample):
        return value
    status = VisionStatus.RECOGNIZED if value.identity_id and value.liveness_passed and value.quality_passed else VisionStatus.UNKNOWN
    return VisionSample(value.observed_at, value, status)


def _mixed_rejection_state(statuses: set[VisionStatus]) -> str:
    priority = (
        (VisionStatus.UNAVAILABLE, "unavailable"),
        (VisionStatus.MULTIPLE_FACES, "multiple-faces"),
        (VisionStatus.LIVENESS_FAILED, "liveness-failed"),
        (VisionStatus.LOW_QUALITY, "low-quality"),
        (VisionStatus.UNKNOWN, "unknown"),
        (VisionStatus.AMBIGUOUS, "ambiguous"),
        (VisionStatus.NO_FACE, "no-face"),
    )
    for status, state in priority:
        if status in statuses:
            return state
    return "ambiguous"

def _rejection_state(samples: Sequence[VisionSample], reason: str) -> str:
    if reason == "identity-not-authorized":
        return "unknown"
    if reason == "stable-match-not-established":
        statuses = {sample.status for sample in samples}
        if VisionStatus.LIVENESS_FAILED in statuses:
            return "liveness-failed"
        if VisionStatus.LOW_QUALITY in statuses:
            return "low-quality"
        if VisionStatus.MULTIPLE_FACES in statuses:
            return "multiple-faces"
    return "ambiguous"
