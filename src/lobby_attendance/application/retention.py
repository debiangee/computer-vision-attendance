"""Controlled, audited retention and de-enrollment cleanup operations."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..audit import AuditEvent
from ..domain import AuditOutcome, UserStatus
from ..storage.repositories import AuditRepository, RetentionRepository, UserRepository

UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class RetentionResult:
    operation: str
    cutoff: datetime | None
    deleted: dict[str, int]


class RetentionService:
    """Operations-layer boundary for explicit local data deletion.

    Recognition events are immutable during normal operation. The repository's
    named purge methods are the only path that temporarily bypasses the event
    delete trigger, and every successful purge is recorded in the audit log.
    """

    def __init__(
        self,
        retention: RetentionRepository,
        audit: AuditRepository,
        users: UserRepository | None = None,
    ) -> None:
        self.retention = retention
        self.audit = audit
        self.users = users

    def purge_expired(
        self,
        *,
        now: datetime,
        retention_days: int,
        actor_id: str,
    ) -> RetentionResult:
        if retention_days <= 0:
            raise ValueError("retention_days must be positive")
        actor = _actor(actor_id)
        current = _utc(now)
        cutoff = current - timedelta(days=retention_days)
        deleted = self.retention.purge_before(cutoff)
        self._audit("retention:purge-expired", actor, deleted, cutoff)
        return RetentionResult("purge-expired", cutoff, deleted)

    def cleanup_de_enrollment(
        self,
        user_id: str,
        *,
        actor_id: str,
        now: datetime | None = None,
    ) -> RetentionResult:
        actor = _actor(actor_id)
        if self.users is not None and self.users.get_status(user_id) is not UserStatus.DEACTIVATED:
            raise ValueError("de-enrollment cleanup requires a deactivated user")
        deleted = self.retention.purge_deactivated_user(user_id)
        current = _utc(now or datetime.now(UTC))
        self._audit("retention:de-enrollment-cleanup", actor, deleted, current)
        return RetentionResult("de-enrollment-cleanup", current, deleted)

    def _audit(
        self,
        action: str,
        actor_id: str,
        deleted: dict[str, int],
        cutoff: datetime,
    ) -> None:
        resource_id = hashlib.sha256(f"{action}\x1f{actor_id}\x1f{cutoff.isoformat()}\x1f{datetime.now(UTC).isoformat()}".encode()).hexdigest()[:32]
        self.audit.append(AuditEvent(
            audit_id=resource_id,
            occurred_at=datetime.now(UTC),
            actor_id=actor_id,
            action=action,
            outcome=AuditOutcome.SUCCESS,
            resource_type="retention",
            resource_id=resource_id,
            metadata={key: str(value) for key, value in deleted.items()},
        ))


def _actor(actor_id: str) -> str:
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise ValueError("actor_id is required for retention operations")
    return actor_id.strip()[:128]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
