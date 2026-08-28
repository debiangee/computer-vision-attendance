"""Framework-independent domain values for recognition encounters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Mapping


class UserStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


class EventSource(StrEnum):
    FACE_ENCOUNTER = "face-encounter"


class QueueState(StrEnum):
    PENDING = "pending"
    IN_FLIGHT = "in-flight"
    SYNCED = "synced"
    FAILED = "failed"
    EXPIRED = "expired"


class EventStorageState(StrEnum):
    RECORDED = "recorded"
    QUEUED = "queued"
    SYNCHRONIZED = "synchronized"
    REJECTED = "rejected"


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class RecognitionObservation:
    """One transient camera/model observation; never persisted as a frame."""

    observed_at: datetime
    identity_id: str | None
    liveness_passed: bool
    quality_passed: bool


@dataclass(frozen=True, slots=True)
class RecognitionEvent:
    event_id: str
    idempotency_key: str
    user_id: str
    site_id: str
    camera_id: str
    occurred_at: datetime
    source: EventSource
    model_version: str
    policy_version: str
    metadata: Mapping[str, str]
    storage_state: EventStorageState = EventStorageState.RECORDED
    correlation_id: str | None = None
    audit_metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QueueItem:
    queue_id: str
    idempotency_key: str
    state: QueueState
    enqueued_at: datetime
    payload: Mapping[str, str]
