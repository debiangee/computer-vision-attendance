"""Retry-safe synchronization of the minimal local event queue."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Protocol

from ..audit import AuditEvent
from ..domain import AuditOutcome, QueueState
from ..storage.repositories import QueueRepository

UTC = timezone.utc


class EventSink(Protocol):
    """Authenticated append sink boundary; implementations must deduplicate keys."""

    def send(self, payload: Mapping[str, str]) -> None:
        ...


class InMemoryEventSink:
    """Deterministic test sink with idempotency-key deduplication."""

    def __init__(self) -> None:
        self._payloads: dict[str, dict[str, str]] = {}

    def send(self, payload: Mapping[str, str]) -> None:
        key = payload.get("idempotency_key")
        if not key:
            raise ValueError("queue payload requires idempotency_key")
        self._payloads.setdefault(key, dict(payload))

    @property
    def payloads(self) -> tuple[Mapping[str, str], ...]:
        return tuple(self._payloads.values())

    def has(self, idempotency_key: str) -> bool:
        return idempotency_key in self._payloads


class QueueSynchronizer:
    """Claim, send, and transition queue items without duplicate submissions."""

    def __init__(
        self,
        queue_repository: QueueRepository,
        sink: EventSink,
        *,
        retry_delay_seconds: int = 30,
        max_age_seconds: int = 86_400,
        lease_seconds: int = QueueRepository.DEFAULT_LEASE_SECONDS,
        lease_owner: str = "queue-synchronizer",
        audit=None,
    ) -> None:
        if retry_delay_seconds < 0 or max_age_seconds <= 0 or lease_seconds <= 0:
            raise ValueError("invalid queue retry, age, or lease configuration")
        if not lease_owner.strip():
            raise ValueError("lease_owner must not be empty")
        self.queue = queue_repository
        self.sink = sink
        self.retry_delay_seconds = retry_delay_seconds
        self.max_age_seconds = max_age_seconds
        self.lease_seconds = lease_seconds
        self.lease_owner = lease_owner
        self.audit = audit
        self.last_failure_count = 0
        self.last_expired_count = 0

    def synchronize(self, *, now: datetime, limit: int = 100, actor_id: str | None = None) -> int:
        current = _utc(now)
        self.last_failure_count = 0
        self.last_expired_count = self.queue.expire_before(
            current - timedelta(seconds=self.max_age_seconds)
        )
        if self.last_expired_count:
            self._audit(
                "queue:expire", actor_id, AuditOutcome.SUCCESS,
                metadata={"count": str(self.last_expired_count)},
            )
        # Reclaim before retry/claim so a crashed worker cannot strand an event.
        reclaimed = self.queue.reclaim_stale_in_flight(now=current, limit=limit)
        if reclaimed:
            self._audit("queue:reclaim", actor_id, AuditOutcome.SUCCESS, metadata={"count": str(reclaimed)})
        retried = self.queue.retry_failed(now=current, limit=limit)
        if retried:
            self._audit("queue:retry", actor_id, AuditOutcome.SUCCESS, metadata={"count": str(retried)})
        claimed = self.queue.claim_pending(
            now=current, limit=limit, lease_seconds=self.lease_seconds,
            lease_owner=self.lease_owner,
        )
        for row in claimed:
            self._audit("queue:claim", actor_id, AuditOutcome.SUCCESS, resource_id=row["queue_id"])
        synced = 0
        for row in claimed:
            try:
                payload = json.loads(row["payload_json"])
                self.sink.send(payload)
            except Exception:
                self.last_failure_count += 1
                self.queue.set_state(
                    row["queue_id"], QueueState.FAILED,
                    last_error="event sink unavailable",
                    available_at=current + timedelta(seconds=self.retry_delay_seconds),
                )
                self._audit(
                    "queue:synchronize", actor_id, AuditOutcome.FAILURE,
                    resource_id=row["queue_id"], metadata={"state": QueueState.FAILED.value},
                )
            else:
                self.queue.set_state(row["queue_id"], QueueState.SYNCED)
                self._audit(
                    "queue:synchronize", actor_id, AuditOutcome.SUCCESS,
                    resource_id=row["queue_id"], metadata={"state": QueueState.SYNCED.value},
                )
                synced += 1
        return synced

    def _audit(
        self, action: str, actor_id: str | None, outcome: AuditOutcome,
        *, resource_id: str | None = None, metadata: dict[str, str] | None = None,
    ) -> None:
        if not self.audit:
            return
        stamp = datetime.now(UTC).isoformat()
        audit_id = hashlib.sha256(f"{action}\x1f{resource_id}\x1f{stamp}".encode()).hexdigest()[:32]
        self.audit.append(AuditEvent(
            audit_id=audit_id, occurred_at=datetime.now(UTC), actor_id=actor_id,
            action=action, outcome=outcome, resource_type="queue",
            resource_id=resource_id, metadata=metadata or {},
        ))


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
