"""Replaceable, bounded vision boundary with explicit safe-rejection states."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from ..domain import RecognitionObservation


class VisionStatus(StrEnum):
    RECOGNIZED = "recognized"
    NO_FACE = "no-face"
    MULTIPLE_FACES = "multiple-faces"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"
    LOW_QUALITY = "low-quality"
    LIVENESS_FAILED = "liveness-failed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class VisionSample:
    """One transient observation plus a user/operator-safe state."""

    observed_at: datetime
    observation: RecognitionObservation
    status: VisionStatus = VisionStatus.RECOGNIZED
    detail: str | None = None


class VisionObservationProvider(Protocol):
    """Produces transient observations for the policy layer; stores no frames."""

    def observe(
        self,
        *,
        until: datetime,
        interval_seconds: float = 0.2,
    ) -> Iterable[VisionSample | RecognitionObservation]:
        """Return a bounded sample window ending no later than ``until``."""
        ...
