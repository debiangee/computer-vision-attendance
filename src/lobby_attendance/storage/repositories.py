"""Parameterized SQLite repositories with append-only event semantics."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

from ..audit import AuditEvent
from ..domain import EventSource, EventStorageState, QueueState, RecognitionEvent, UserStatus
from ..errors import IntegrityError
from .sqlite import SQLiteStore, datetime_text, utc_now_text


class UserRepository:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def create(
        self,
        user_id: str,
        display_name: str,
        *,
        status: UserStatus = UserStatus.ACTIVE,
        enrolled_at: datetime | None = None,
    ) -> None:
        now = utc_now_text()
        enrolled = datetime_text(enrolled_at) if enrolled_at else now
        self.store.connection.execute(
            """INSERT INTO users(user_id, display_name, status, enrolled_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, display_name, status.value, enrolled, now, now),
        )

    def set_status(self, user_id: str, status: UserStatus, *, deactivated_at: datetime | None = None) -> None:
        self.store.connection.execute(
            "UPDATE users SET status = ?, deactivated_at = ?, updated_at = ? WHERE user_id = ?",
            (status.value, datetime_text(deactivated_at) if deactivated_at else None, utc_now_text(), user_id),
        )

    def get_status(self, user_id: str) -> UserStatus | None:
        row = self.store.connection.execute("SELECT status FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return UserStatus(row[0]) if row else None

    def active_user_ids(self) -> set[str]:
        rows = self.store.connection.execute("SELECT user_id FROM users WHERE status = ?", (UserStatus.ACTIVE.value,))
        return {row[0] for row in rows}

    def get(self, user_id: str) -> sqlite3.Row | None:
        return self.store.connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

    def list_users(
        self, *, limit: int = 100, subject_ids: Iterable[str] | None = None,
    ) -> list[sqlite3.Row]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if subject_ids is None:
            return list(self.store.connection.execute(
                "SELECT user_id, display_name, status, enrolled_at, deactivated_at, created_at, updated_at "
                "FROM users ORDER BY created_at DESC LIMIT ?", (limit,)
            ))
        allowed = tuple(sorted(set(subject_ids)))
        if not allowed:
            return []
        placeholders = ", ".join("?" for _ in allowed)
        return list(self.store.connection.execute(
            "SELECT user_id, display_name, status, enrolled_at, deactivated_at, created_at, updated_at "
            f"FROM users WHERE user_id IN ({placeholders}) ORDER BY created_at DESC LIMIT ?",
            (*allowed, limit),
        ))


class RBACAssignmentRepository:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def assign(self, user_id: str, role: str, *, assigned_by: str | None = None, assigned_at: datetime | None = None) -> None:
        self.store.connection.execute(
            """INSERT INTO rbac_assignments(user_id, role, assigned_at, assigned_by)
               VALUES (?, ?, ?, ?) ON CONFLICT(user_id, role) DO NOTHING""",
            (user_id, role, datetime_text(assigned_at) if assigned_at else utc_now_text(), assigned_by),
        )

    def roles_for(self, user_id: str) -> set[str]:
        rows = self.store.connection.execute("SELECT role FROM rbac_assignments WHERE user_id = ?", (user_id,))
        return {row[0] for row in rows}

    def list_assignments(self, *, limit: int = 100) -> list[sqlite3.Row]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return list(self.store.connection.execute(
            "SELECT user_id, role, assigned_at, assigned_by FROM rbac_assignments "
            "ORDER BY assigned_at DESC LIMIT ?", (limit,)
        ))


class TemplateMetadataRepository:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def add(
        self,
        template_id: str,
        user_id: str,
        model_version: str,
        template_version: str,
        template_hash: str,
        *,
        created_at: datetime | None = None,
    ) -> None:
        self.store.connection.execute(
            """INSERT INTO biometric_template_metadata
               (template_id, user_id, model_version, template_version, template_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                template_id, user_id, model_version, template_version, template_hash,
                datetime_text(created_at) if created_at else utc_now_text(),
            ),
        )

    def has_active_versioned_template(self, user_id: str) -> bool:
        row = self.store.connection.execute(
            """SELECT 1 FROM biometric_template_metadata
               WHERE user_id = ? AND retired_at IS NULL
                 AND TRIM(model_version) <> ''
                 AND TRIM(template_version) <> ''
                 AND TRIM(template_hash) <> ''
               LIMIT 1""",
            (user_id,),
        ).fetchone()
        return row is not None

    def retire_for_user(self, user_id: str, *, retired_at: datetime | None = None) -> int:
        cursor = self.store.connection.execute(
            "UPDATE biometric_template_metadata SET retired_at = ? WHERE user_id = ? AND retired_at IS NULL",
            (datetime_text(retired_at) if retired_at else utc_now_text(), user_id),
        )
        return cursor.rowcount


class EventRepository:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def append(self, event: RecognitionEvent) -> None:
        try:
            self.store.connection.execute(
                """INSERT INTO recognition_events
                   (event_id, idempotency_key, user_id, site_id, camera_id, occurred_at,
                    source, model_version, policy_version, metadata_json, created_at,
                    storage_state, correlation_id, audit_metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.event_id,
                    event.idempotency_key,
                    event.user_id,
                    event.site_id,
                    event.camera_id,
                    datetime_text(event.occurred_at),
                    event.source.value,
                    event.model_version,
                    event.policy_version,
                    json.dumps(dict(event.metadata), sort_keys=True, separators=(",", ":")),
                    utc_now_text(),
                    event.storage_state.value,
                    event.correlation_id,
                    json.dumps(dict(event.audit_metadata), sort_keys=True, separators=(",", ":")),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise IntegrityError("recognition event violates identity or idempotency uniqueness") from exc

    def get_by_idempotency(self, idempotency_key: str) -> sqlite3.Row | None:
        return self.store.connection.execute(
            "SELECT * FROM recognition_events WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()

    def get_by_id(self, event_id: str, *, site_ids: Iterable[str] | None = None, subject_ids: Iterable[str] | None = None) -> sqlite3.Row | None:
        clauses = ["event_id = ?"]
        args: list[str | int] = [event_id]
        _append_scope(clauses, args, "site_id", site_ids)
        _append_scope(clauses, args, "user_id", subject_ids)
        return self.store.connection.execute(
            f"SELECT * FROM recognition_events WHERE {' AND '.join(clauses)}", args
        ).fetchone()

    def latest_for_user_camera(self, user_id: str, camera_id: str) -> datetime | None:
        row = self.store.connection.execute(
            """SELECT occurred_at FROM recognition_events
               WHERE user_id = ? AND camera_id = ? ORDER BY occurred_at DESC LIMIT 1""",
            (user_id, camera_id),
        ).fetchone()
        if not row:
            return None
        return datetime.fromisoformat(row[0])

    def list_events(
        self, *, limit: int = 100, site_ids: Iterable[str] | None = None,
        subject_ids: Iterable[str] | None = None,
    ) -> list[sqlite3.Row]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        clauses: list[str] = []
        args: list[str | int] = []
        _append_scope(clauses, args, "site_id", site_ids)
        _append_scope(clauses, args, "user_id", subject_ids)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return list(self.store.connection.execute(
            f"SELECT * FROM recognition_events{where} ORDER BY occurred_at DESC LIMIT ?",
            (*args, limit),
        ))


class SuppressionRepository:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def record(
        self,
        suppression_id: str,
        user_id: str,
        camera_id: str,
        reason: str,
        *,
        suppressed_at: datetime,
        source_event_id: str | None = None,
    ) -> None:
        self.store.connection.execute(
            """INSERT INTO suppression_records
               (suppression_id, user_id, camera_id, suppressed_at, reason, source_event_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (suppression_id, user_id, camera_id, datetime_text(suppressed_at), reason, source_event_id, utc_now_text()),
        )

    def latest_for_user_camera(self, user_id: str, camera_id: str) -> datetime | None:
        row = self.store.connection.execute(
            """SELECT suppressed_at FROM suppression_records
               WHERE user_id = ? AND camera_id = ? ORDER BY suppressed_at DESC LIMIT 1""",
            (user_id, camera_id),
        ).fetchone()
        return datetime.fromisoformat(row[0]) if row else None


class QueueRepository:
    DEFAULT_LEASE_SECONDS = 300

    def __init__(self, store: SQLiteStore):
        self.store = store

    def enqueue(
        self,
        queue_id: str,
        idempotency_key: str,
        payload: Mapping[str, Any],
        *,
        enqueued_at: datetime,
        available_at: datetime | None = None,
    ) -> None:
        try:
            self.store.connection.execute(
                """INSERT INTO local_queue_items
                   (queue_id, idempotency_key, state, enqueued_at, available_at, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    queue_id,
                    idempotency_key,
                    QueueState.PENDING.value,
                    datetime_text(enqueued_at),
                    datetime_text(available_at or enqueued_at),
                    json.dumps(dict(payload), sort_keys=True, separators=(",", ":")),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise IntegrityError("queue item violates idempotency uniqueness") from exc

    def get_by_idempotency(self, idempotency_key: str) -> sqlite3.Row | None:
        return self.store.connection.execute(
            "SELECT * FROM local_queue_items WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()

    def claim_pending(
        self,
        *,
        now: datetime,
        limit: int = 1,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        lease_owner: str | None = None,
    ) -> list[sqlite3.Row]:
        if limit <= 0 or lease_seconds <= 0:
            raise ValueError("limit and lease_seconds must be positive")
        now_text = datetime_text(now)
        lease_until = datetime_text(now + timedelta(seconds=lease_seconds))
        owner = (lease_owner or "queue-worker").strip()
        if not owner:
            raise ValueError("lease_owner must not be empty")
        with self.store.connection:
            rows = list(self.store.connection.execute(
                """SELECT * FROM local_queue_items
                   WHERE state = ? AND available_at <= ? ORDER BY enqueued_at LIMIT ?""",
                (QueueState.PENDING.value, now_text, limit),
            ))
            for row in rows:
                self.store.connection.execute(
                    """UPDATE local_queue_items
                       SET state = ?, attempts = attempts + 1, lease_until = ?, lease_owner = ?
                       WHERE queue_id = ? AND state = ?""",
                    (
                        QueueState.IN_FLIGHT.value, lease_until, owner,
                        row["queue_id"], QueueState.PENDING.value,
                    ),
                )
            return rows

    def reclaim_stale_in_flight(self, *, now: datetime, limit: int = 100) -> int:
        """Return expired claims to pending so crashes cannot strand queue items."""
        if limit <= 0:
            raise ValueError("limit must be positive")
        now_text = datetime_text(now)
        cursor = self.store.connection.execute(
            """UPDATE local_queue_items SET state = ?, available_at = ?, lease_until = NULL, lease_owner = NULL
               WHERE queue_id IN (
                 SELECT queue_id FROM local_queue_items
                 WHERE state = ? AND (lease_until IS NULL OR lease_until <= ?)
                 ORDER BY enqueued_at LIMIT ?
               )""",
            (
                QueueState.PENDING.value, now_text, QueueState.IN_FLIGHT.value,
                now_text, limit,
            ),
        )
        return cursor.rowcount

    def set_state(
        self,
        queue_id: str,
        state: QueueState,
        *,
        last_error: str | None = None,
        available_at: datetime | None = None,
    ) -> None:
        lease_until = None if state is not QueueState.IN_FLIGHT else None
        lease_owner = None if state is not QueueState.IN_FLIGHT else None
        if available_at is None:
            self.store.connection.execute(
                """UPDATE local_queue_items
                   SET state = ?, last_error = ?, lease_until = ?, lease_owner = ?
                   WHERE queue_id = ?""",
                (state.value, last_error, lease_until, lease_owner, queue_id),
            )
        else:
            self.store.connection.execute(
                """UPDATE local_queue_items
                   SET state = ?, last_error = ?, available_at = ?, lease_until = ?, lease_owner = ?
                   WHERE queue_id = ?""",
                (state.value, last_error, datetime_text(available_at), lease_until, lease_owner, queue_id),
            )

    def retry_failed(self, *, now: datetime, limit: int = 100) -> int:
        if limit <= 0:
            raise ValueError("limit must be positive")
        cursor = self.store.connection.execute(
            """UPDATE local_queue_items SET state = ?, last_error = NULL, lease_until = NULL, lease_owner = NULL
               WHERE queue_id IN (
                 SELECT queue_id FROM local_queue_items
                 WHERE state = ? AND available_at <= ? ORDER BY enqueued_at LIMIT ?
               )""",
            (QueueState.PENDING.value, QueueState.FAILED.value, datetime_text(now), limit),
        )
        return cursor.rowcount

    def expire_before(self, cutoff: datetime) -> int:
        cursor = self.store.connection.execute(
            """UPDATE local_queue_items SET state = ?, lease_until = NULL, lease_owner = NULL
               WHERE state IN (?, ?, ?) AND enqueued_at < ?""",
            (
                QueueState.EXPIRED.value, QueueState.PENDING.value, QueueState.FAILED.value,
                QueueState.IN_FLIGHT.value, datetime_text(cutoff),
            ),
        )
        return cursor.rowcount

    def count(self, state: QueueState | None = None) -> int:
        if state is None:
            row = self.store.connection.execute("SELECT COUNT(*) FROM local_queue_items").fetchone()
        else:
            row = self.store.connection.execute("SELECT COUNT(*) FROM local_queue_items WHERE state = ?", (state.value,)).fetchone()
        return int(row[0])


class RetentionRepository:
    """Explicit data-purge boundary; ordinary event deletes remain trigger-protected."""

    _EVENT_DELETE_TRIGGER = "recognition_events_no_delete"

    def __init__(self, store: SQLiteStore):
        self.store = store

    def purge_before(self, cutoff: datetime) -> dict[str, int]:
        cutoff_text = datetime_text(cutoff)
        return self._purge(
            event_where="occurred_at < ?", event_args=(cutoff_text,),
            suppression_where="suppressed_at < ?", suppression_args=(cutoff_text,),
            queue_where="enqueued_at < ?", queue_args=(cutoff_text,),
            template_where="retired_at IS NOT NULL AND retired_at < ?", template_args=(cutoff_text,),
        )

    def purge_deactivated_user(self, user_id: str) -> dict[str, int]:
        if not user_id.strip():
            raise ValueError("user_id must not be empty")
        return self._purge(
            event_where="user_id = ?", event_args=(user_id,),
            suppression_where="user_id = ?", suppression_args=(user_id,),
            queue_where="json_extract(payload_json, '$.user_id') = ?", queue_args=(user_id,),
            template_where="user_id = ? AND retired_at IS NOT NULL", template_args=(user_id,),
        )

    def _purge(
        self, *, event_where: str, event_args: tuple[str, ...],
        suppression_where: str, suppression_args: tuple[str, ...],
        queue_where: str, queue_args: tuple[str, ...],
        template_where: str, template_args: tuple[str, ...],
    ) -> dict[str, int]:
        conn = self.store.connection
        counts = {
            "recognition_events": int(conn.execute(
                f"SELECT COUNT(*) FROM recognition_events WHERE {event_where}", event_args
            ).fetchone()[0]),
            "suppression_records": int(conn.execute(
                f"SELECT COUNT(*) FROM suppression_records WHERE {suppression_where}", suppression_args
            ).fetchone()[0]),
            "local_queue_items": int(conn.execute(
                f"SELECT COUNT(*) FROM local_queue_items WHERE {queue_where}", queue_args
            ).fetchone()[0]),
            "biometric_template_metadata": int(conn.execute(
                f"SELECT COUNT(*) FROM biometric_template_metadata WHERE {template_where}", template_args
            ).fetchone()[0]),
        }
        with conn:
            conn.execute(f"DROP TRIGGER IF EXISTS {self._EVENT_DELETE_TRIGGER}")
            try:
                conn.execute(f"DELETE FROM recognition_events WHERE {event_where}", event_args)
            finally:
                conn.execute(
                    """CREATE TRIGGER recognition_events_no_delete
                       BEFORE DELETE ON recognition_events
                       BEGIN
                           SELECT RAISE(ABORT, 'recognition_events are append-only');
                       END"""
                )
            conn.execute(f"DELETE FROM suppression_records WHERE {suppression_where}", suppression_args)
            conn.execute(f"DELETE FROM local_queue_items WHERE {queue_where}", queue_args)
            conn.execute(f"DELETE FROM biometric_template_metadata WHERE {template_where}", template_args)
        return counts


class AuditRepository:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def append(self, event: AuditEvent) -> None:
        self.store.connection.execute(
            """INSERT INTO audit_events
               (audit_id, occurred_at, actor_id, action, outcome, resource_type, resource_id, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.audit_id,
                datetime_text(event.occurred_at),
                event.actor_id,
                event.action,
                event.outcome.value,
                event.resource_type,
                event.resource_id,
                json.dumps(dict(event.metadata), sort_keys=True, separators=(",", ":")),
            ),
        )

    def list_events(self, *, limit: int = 100) -> list[sqlite3.Row]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return list(self.store.connection.execute(
            "SELECT audit_id, occurred_at, actor_id, action, outcome, resource_type, resource_id, metadata_json "
            "FROM audit_events ORDER BY occurred_at DESC LIMIT ?", (limit,)
        ))


class PolicyConfigRepository:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def set(self, key: str, value: Any, version: str, *, updated_at: datetime | None = None) -> None:
        self.store.connection.execute(
            """INSERT INTO policy_config_metadata(config_key, config_value_json, version, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(config_key) DO UPDATE SET config_value_json=excluded.config_value_json,
               version=excluded.version, updated_at=excluded.updated_at""",
            (key, json.dumps(value, sort_keys=True), version, datetime_text(updated_at) if updated_at else utc_now_text()),
        )

    def get(self, key: str) -> dict[str, Any] | None:
        row = self.store.connection.execute(
            "SELECT config_value_json, version, updated_at FROM policy_config_metadata WHERE config_key = ?", (key,)
        ).fetchone()
        if not row:
            return None
        return {"value": json.loads(row[0]), "version": row[1], "updated_at": row[2]}


class CorrectionRepository:
    """Append-only correction history; recognition event rows are never changed."""

    def __init__(self, store: SQLiteStore):
        self.store = store

    def append(
        self,
        correction_id: str,
        event_id: str,
        *,
        occurred_at: datetime,
        actor_id: str,
        reason: str,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        audit_metadata: Mapping[str, str] | None = None,
    ) -> None:
        self.store.connection.execute(
            """INSERT INTO attendance_corrections
               (correction_id, event_id, occurred_at, actor_id, reason,
                before_json, after_json, audit_metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                correction_id, event_id, datetime_text(occurred_at), actor_id, reason,
                json.dumps(dict(before), sort_keys=True, separators=(",", ":")),
                json.dumps(dict(after), sort_keys=True, separators=(",", ":")),
                json.dumps(dict(audit_metadata or {}), sort_keys=True, separators=(",", ":")),
                utc_now_text(),
            ),
        )

    def list_for_event(self, event_id: str, *, limit: int = 100) -> list[sqlite3.Row]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return list(self.store.connection.execute(
            "SELECT * FROM attendance_corrections WHERE event_id = ? "
            "ORDER BY occurred_at DESC LIMIT ?", (event_id, limit)
        ))


class AuthTokenRevocationRepository:
    """Persist signed-session revocations until the token naturally expires."""

    def __init__(self, store: SQLiteStore):
        self.store = store

    def revoke(
        self,
        token_id: str,
        expires_at: datetime,
        *,
        revoked_by: str | None = None,
        revoked_at: datetime | None = None,
    ) -> None:
        self.store.connection.execute(
            """INSERT INTO auth_token_revocations(token_id, revoked_at, expires_at, revoked_by)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(token_id) DO UPDATE SET revoked_at = excluded.revoked_at,
                   expires_at = excluded.expires_at, revoked_by = excluded.revoked_by""",
            (
                token_id,
                datetime_text(revoked_at) if revoked_at else utc_now_text(),
                datetime_text(expires_at),
                revoked_by,
            ),
        )

    def is_revoked(self, token_id: str, *, now: datetime | None = None) -> bool:
        row = self.store.connection.execute(
            "SELECT expires_at FROM auth_token_revocations WHERE token_id = ?",
            (token_id,),
        ).fetchone()
        if row is None:
            return False
        current = datetime_text(now) if now else utc_now_text()
        if row["expires_at"] <= current:
            self.store.connection.execute(
                "DELETE FROM auth_token_revocations WHERE token_id = ?", (token_id,)
            )
            return False
        return True

    def purge_expired(self, *, before: datetime | None = None) -> int:
        cutoff = datetime_text(before) if before else utc_now_text()
        cursor = self.store.connection.execute(
            "DELETE FROM auth_token_revocations WHERE expires_at <= ?", (cutoff,)
        )
        return cursor.rowcount


def _append_scope(
    clauses: list[str], args: list[str | int], column: str, values: Iterable[str] | None,
) -> None:
    if values is None:
        return
    allowed = tuple(sorted(set(values)))
    if not allowed:
        clauses.append("1 = 0")
        return
    placeholders = ", ".join("?" for _ in allowed)
    clauses.append(f"{column} IN ({placeholders})")
    args.extend(allowed)
