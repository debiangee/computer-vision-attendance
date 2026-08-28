"""Recognition encounter event service and local-first persistence fallback."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Sequence

from ..audit import AuditEvent
from ..domain import AuditOutcome, EventSource, EventStorageState, QueueState, RecognitionEvent, RecognitionObservation
from ..errors import IntegrityError
from ..policy import (
    POLICY_VERSION,
    aggregate_stable_identity,
    evaluate_encounter,
    generate_idempotency_key,
)
from ..storage.repositories import (
    AuditRepository,
    EventRepository,
    QueueRepository,
    SuppressionRepository,
    UserRepository,
)
from .queue_sync import EventSink

UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class EventSubmission:
    state: str
    reason: str
    idempotency_key: str | None = None
    event: RecognitionEvent | None = None


class RecognitionEventService:
    """Apply authorization/cooldown policy and append one immutable encounter."""

    def __init__(
        self,
        users: UserRepository,
        events: EventRepository | None,
        queue: QueueRepository | None,
        *,
        suppressions: SuppressionRepository | None = None,
        audit: AuditRepository | None = None,
        site_id: str = "local-site",
        camera_id: str = "lobby-camera",
        cooldown_seconds: int = 300,
        model_version: str = "unknown",
        policy_version: str = POLICY_VERSION,
        queue_max_size: int = 10_000,
        event_sink: EventSink | None = None,
        compliance_approved: bool = False,
    ) -> None:
        self.users = users
        self.events = events
        self.queue = queue
        self.suppressions = suppressions
        self.audit = audit
        self.site_id = site_id
        self.camera_id = camera_id
        self.cooldown_seconds = cooldown_seconds
        self.model_version = model_version
        self.policy_version = policy_version
        self.queue_max_size = queue_max_size
        self.event_sink = event_sink
        self.compliance_approved = compliance_approved

    def submit(
        self,
        observations: Sequence[RecognitionObservation],
        *,
        occurred_at: datetime,
        sample_window_size: int = 5,
        required_count: int = 3,
    ) -> EventSubmission:
        if not self.compliance_approved:
            self._audit_compliance_block(occurred_at)
            return EventSubmission("rejected", "compliance-not-approved")
        if len(observations) < sample_window_size:
            return EventSubmission("rejected", "stable-window-incomplete")
        active_ids = self.users.active_user_ids()
        last_event_at = None
        match = aggregate_stable_identity(
            observations, window_size=sample_window_size, required_count=required_count
        )
        if match.identity_id and match.identity_id in active_ids:
            candidate_key = generate_idempotency_key(
                user_id=match.identity_id,
                site_id=self.site_id,
                camera_id=self.camera_id,
                occurred_at=occurred_at,
                model_version=self.model_version,
                policy_version=self.policy_version,
            )
            if self.events and self.events.get_by_idempotency(candidate_key):
                return EventSubmission("duplicate", "idempotent-retry", candidate_key)
            if self.queue and self.queue.get_by_idempotency(candidate_key):
                return EventSubmission("duplicate", "idempotent-retry", candidate_key)
        if match.identity_id and self.events:
            last_event_at = self.events.latest_for_user_camera(match.identity_id, self.camera_id)
        decision = evaluate_encounter(
            observations,
            active_user_ids=active_ids,
            occurred_at=occurred_at,
            site_id=self.site_id,
            camera_id=self.camera_id,
            last_event_at=last_event_at,
            cooldown_seconds=self.cooldown_seconds,
            model_version=self.model_version,
            policy_version=self.policy_version,
            window_size=sample_window_size,
            required_count=required_count,
        )
        if not decision.accepted:
            if decision.reason == "cooldown-active" and match.identity_id:
                self._record_suppression(match.identity_id, decision.occurred_at or occurred_at)
            return EventSubmission("suppressed" if decision.reason == "cooldown-active" else "rejected", decision.reason)

        assert decision.identity_id and decision.occurred_at and decision.idempotency_key
        existing = self.events.get_by_idempotency(decision.idempotency_key) if self.events else None
        if existing:
            return EventSubmission("duplicate", "idempotent-retry", decision.idempotency_key)
        event = RecognitionEvent(
            event_id="evt-" + decision.idempotency_key[:32],
            idempotency_key=decision.idempotency_key,
            user_id=decision.identity_id,
            site_id=self.site_id,
            camera_id=self.camera_id,
            occurred_at=decision.occurred_at,
            source=EventSource.FACE_ENCOUNTER,
            model_version=self.model_version,
            policy_version=self.policy_version,
            metadata={"sample_count": str(len(observations)), "event_type": "RECOGNIZED_ENCOUNTER"},
            storage_state=EventStorageState.RECORDED,
            correlation_id="corr-" + decision.idempotency_key[:32],
            audit_metadata={"interaction": "bounded-camera-sample"},
        )
        try:
            if self.event_sink:
                self.event_sink.send(_event_payload(event))
            elif self.events:
                self.events.append(event)
            else:
                raise RuntimeError("event sink unavailable")
        except IntegrityError:
            if self.events and self.events.get_by_idempotency(event.idempotency_key):
                return EventSubmission("duplicate", "idempotent-retry", event.idempotency_key, event)
            raise
        except Exception as exc:
            if not self._enqueue(event, error=str(exc)):
                rejected = replace(event, storage_state=EventStorageState.REJECTED)
                self._audit("event:rejected", rejected, AuditOutcome.FAILURE)
                return EventSubmission("rejected", "event-storage-unavailable", event.idempotency_key, rejected)
            queued = replace(event, storage_state=EventStorageState.QUEUED)
            self._audit("event:queue", queued, AuditOutcome.SUCCESS)
            return EventSubmission("queued", "event-queued-locally", event.idempotency_key, queued)
        self._audit("event:record", event, AuditOutcome.SUCCESS)
        return EventSubmission("recorded", "recognized-event-recorded", event.idempotency_key, event)

    def _audit_compliance_block(self, occurred_at: datetime) -> None:
        if not self.audit:
            return
        try:
            self.audit.append(AuditEvent(
                audit_id=_stable_id("audit", "recognition:blocked", occurred_at.isoformat()),
                occurred_at=occurred_at,
                actor_id=None,
                action="recognition:blocked",
                outcome=AuditOutcome.DENIED,
                resource_type="recognition-event",
                resource_id=None,
                metadata={"reason": "compliance-not-approved"},
            ))
        except Exception:
            # A missing approval must remain fail-closed even if audit storage is unavailable.
            pass

    def _enqueue(self, event: RecognitionEvent, *, error: str) -> bool:
        if not self.queue:
            return False
        active_queue_count = sum(
            self.queue.count(state)
            for state in (QueueState.PENDING, QueueState.IN_FLIGHT, QueueState.FAILED)
        )
        if active_queue_count >= self.queue_max_size:
            return False
        payload = _event_payload(replace(event, storage_state=EventStorageState.QUEUED))
        try:
            self.queue.enqueue(
                "queue-" + event.idempotency_key[:32], event.idempotency_key, payload,
                enqueued_at=event.occurred_at,
            )
        except IntegrityError:
            return True
        return True

    def _record_suppression(self, user_id: str, occurred_at: datetime) -> None:
        suppression_id = _stable_id("suppression", user_id, self.camera_id, occurred_at.isoformat())
        if self.suppressions:
            try:
                self.suppressions.record(
                    suppression_id, user_id, self.camera_id, "cooldown",
                    suppressed_at=occurred_at,
                )
            except IntegrityError:
                pass
        if self.audit:
            try:
                self.audit.append(AuditEvent(
                    audit_id=_stable_id("audit", "cooldown", user_id, self.camera_id, occurred_at.isoformat()),
                    occurred_at=occurred_at,
                    actor_id=None,
                    action="event:cooldown-suppressed",
                    outcome=AuditOutcome.SUCCESS,
                    resource_type="recognition-event",
                    resource_id=None,
                    metadata={"camera_id": self.camera_id, "reason": "cooldown"},
                ))
            except IntegrityError:
                pass

    def _audit(self, action: str, event: RecognitionEvent, outcome: AuditOutcome) -> None:
        if not self.audit:
            return
        self.audit.append(AuditEvent(
            audit_id=_stable_id("audit", action, event.idempotency_key),
            occurred_at=event.occurred_at,
            actor_id=None,
            action=action,
            outcome=outcome,
            resource_type="recognition-event",
            resource_id=event.event_id,
            metadata={"source": event.source.value, "storage_state": event.storage_state.value},
        ))


def _event_payload(event: RecognitionEvent) -> dict[str, str]:
    return {
        "event_id": event.event_id,
        "idempotency_key": event.idempotency_key,
        "user_id": event.user_id,
        "site_id": event.site_id,
        "camera_id": event.camera_id,
        "occurred_at": event.occurred_at.astimezone(UTC).isoformat(),
        "source": event.source.value,
        "model_version": event.model_version,
        "policy_version": event.policy_version,
        "storage_state": event.storage_state.value,
        "correlation_id": event.correlation_id or event.idempotency_key,
        "audit_metadata": json.dumps(dict(event.audit_metadata), sort_keys=True, separators=(",", ":")),
    }


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]
