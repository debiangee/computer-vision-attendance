"""Deterministic synthetic vision provider for tests and local development."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence

from ..domain import RecognitionObservation
from .protocol import VisionSample, VisionStatus

UTC = timezone.utc


class MockVisionProvider:
    """Generate bounded observations without camera access or personal data."""

    def __init__(
        self,
        *,
        identity_id: str | None = "synthetic-user",
        sample_count: int = 5,
        liveness_passed: bool = True,
        quality_passed: bool = True,
        statuses: Sequence[VisionStatus] | None = None,
        start_at: datetime | None = None,
        interval_seconds: float = 0.2,
    ) -> None:
        if not 0 <= sample_count <= 5:
            raise ValueError("sample_count must be between 0 and 5")
        if interval_seconds < 0:
            raise ValueError("interval_seconds must be non-negative")
        self.identity_id = identity_id
        self.sample_count = sample_count
        self.liveness_passed = liveness_passed
        self.quality_passed = quality_passed
        self.statuses = tuple(statuses or ())
        self.start_at = start_at
        self.interval_seconds = interval_seconds

    def observe(
        self,
        *,
        until: datetime,
        interval_seconds: float | None = None,
    ) -> tuple[VisionSample, ...]:
        end = _utc(until)
        interval = self.interval_seconds if interval_seconds is None else interval_seconds
        if interval < 0:
            raise ValueError("interval_seconds must be non-negative")
        start = _utc(self.start_at) if self.start_at else end - timedelta(
            seconds=interval * max(self.sample_count - 1, 0)
        )
        samples: list[VisionSample] = []
        for index in range(self.sample_count):
            observed_at = start + timedelta(seconds=interval * index)
            if observed_at > end:
                break
            status = self.statuses[index] if index < len(self.statuses) else None
            observation = RecognitionObservation(
                observed_at=observed_at,
                identity_id=self.identity_id,
                liveness_passed=self.liveness_passed,
                quality_passed=self.quality_passed,
            )
            samples.append(VisionSample(
                observed_at=observed_at,
                observation=observation,
                status=status or _status_for(observation),
            ))
        return tuple(samples)


def _status_for(observation: RecognitionObservation) -> VisionStatus:
    if not observation.identity_id:
        return VisionStatus.NO_FACE
    if not observation.quality_passed:
        return VisionStatus.LOW_QUALITY
    if not observation.liveness_passed:
        return VisionStatus.LIVENESS_FAILED
    return VisionStatus.RECOGNIZED


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
