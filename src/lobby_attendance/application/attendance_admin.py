"""Audited attendance correction and export service boundaries."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from ..audit import AuditEvent
from ..domain import AuditOutcome
from ..errors import AuthorizationError, IntegrityError
from ..storage.repositories import AuditRepository, CorrectionRepository, EventRepository, UserRepository

UTC = timezone.utc
CORRECTABLE_FIELDS = frozenset({"user_id", "site_id", "camera_id", "occurred_at"})
EXPORT_FIELDS = (
    "event_id", "idempotency_key", "user_id", "site_id", "camera_id", "occurred_at",
    "source", "model_version", "policy_version", "storage_state", "correlation_id",
)


class AttendanceAdminService:
    def __init__(
        self,
        events: EventRepository,
        corrections: CorrectionRepository,
        users: UserRepository,
        audit: AuditRepository,
    ) -> None:
        self.events = events
        self.corrections = corrections
        self.users = users
        self.audit = audit

    def correct(
        self,
        event_id: str,
        *,
        reason: str,
        changes: Mapping[str, Any],
        actor_id: str,
        site_ids: Iterable[str] | None = None,
        subject_ids: Iterable[str] | None = None,
        occurred_at: datetime | None = None,
    ) -> dict[str, Any]:
        if not actor_id.strip() or not reason.strip() or len(reason.strip()) > 500:
            raise ValueError("actor, reason, and changes are required")
        if not isinstance(changes, Mapping) or not changes or len(changes) > 4:
            raise ValueError("changes are invalid")
        if set(changes) - CORRECTABLE_FIELDS:
            raise ValueError("changes contain a non-correctable field")
        row = self.events.get_by_id(event_id, site_ids=site_ids, subject_ids=subject_ids)
        if row is None:
            raise LookupError("event does not exist")
        before = _event_snapshot(row)
        after = dict(before)
        for key, value in changes.items():
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise ValueError("change values are invalid")
            if key in {"user_id", "site_id", "camera_id"} and any(ord(c) < 32 for c in value):
                raise ValueError("change values are invalid")
            if key == "user_id" and self.users.get(value.strip()) is None:
                raise ValueError("corrected user does not exist")
            if key == "occurred_at":
                try:
                    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
                except ValueError as exc:
                    raise ValueError("occurred_at is invalid") from exc
                if parsed.tzinfo is None:
                    raise ValueError("occurred_at must include timezone")
                after[key] = parsed.astimezone(UTC).isoformat()
            else:
                after[key] = value.strip()
        if not _scope_allows(site_ids, after["site_id"]) or not _scope_allows(subject_ids, after["user_id"]):
            raise AuthorizationError("correction would leave the authorized scope")
        when = occurred_at or datetime.now(UTC)
        correction_id = hashlib.sha256(
            f"correction\x1f{event_id}\x1f{actor_id}\x1f{when.isoformat()}\x1f{reason}".encode()
        ).hexdigest()[:32]
        try:
            self.corrections.append(
                correction_id, event_id, occurred_at=when, actor_id=actor_id,
                reason=reason.strip(), before=before, after=after,
                audit_metadata={"contract": "immutable-correction-v1"},
            )
        except IntegrityError:
            raise
        self.audit.append(AuditEvent(
            audit_id=_audit_id("attendance:correction", correction_id),
            occurred_at=when,
            actor_id=actor_id,
            action="attendance:correction",
            outcome=AuditOutcome.SUCCESS,
            resource_type="attendance-correction",
            resource_id=correction_id,
            metadata={"event_id": event_id, "reason_length": str(len(reason.strip()))},
        ))
        return {
            "correction_id": correction_id, "event_id": event_id,
            "occurred_at": when.isoformat(), "actor_id": actor_id,
            "reason": reason.strip(), "before": before, "after": after,
        }

    def export(
        self, *, limit: int = 100, actor_id: str,
        site_ids: Iterable[str] | None = None,
        subject_ids: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        if limit <= 0 or limit > 500:
            raise ValueError("limit is invalid")
        result = [{field: row[field] for field in EXPORT_FIELDS} for row in self.events.list_events(
            limit=limit, site_ids=site_ids, subject_ids=subject_ids,
        )]
        now = datetime.now(UTC)
        self.audit.append(AuditEvent(
            audit_id=_audit_id("attendance:export", f"{actor_id}:{now.isoformat()}"),
            occurred_at=now,
            actor_id=actor_id,
            action="attendance:export",
            outcome=AuditOutcome.SUCCESS,
            resource_type="attendance-export",
            resource_id=None,
            metadata={"row_count": str(len(result)), "redacted": "true"},
        ))
        return result


def _event_snapshot(row: Any) -> dict[str, Any]:
    return {field: row[field] for field in EXPORT_FIELDS}


def _audit_id(action: str, resource_id: str) -> str:
    return hashlib.sha256(f"{action}\x1f{resource_id}".encode()).hexdigest()[:32]


def _scope_allows(scope: Iterable[str] | None, value: str) -> bool:
    if scope is None:
        return True
    allowed = set(scope)
    return value in allowed or "*" in allowed
