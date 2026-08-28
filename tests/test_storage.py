from datetime import datetime, timedelta, timezone

import sqlite3

import pytest

from lobby_attendance.audit import AuditEvent
from lobby_attendance.domain import AuditOutcome, EventSource, EventStorageState, QueueState, RecognitionEvent, UserStatus
from lobby_attendance.errors import ConfigurationError, IntegrityError
from lobby_attendance.storage import SQLiteStore
from lobby_attendance.storage.schema import MIGRATIONS
from lobby_attendance.storage.repositories import (
    AuditRepository,
    EventRepository,
    PolicyConfigRepository,
    QueueRepository,
    RBACAssignmentRepository,
    RetentionRepository,
    SuppressionRepository,
    TemplateMetadataRepository,
    UserRepository,
)

UTC = timezone.utc
NOW = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    with SQLiteStore(tmp_path / "attendance.sqlite3") as value:
        yield value


def test_sqlite_initialization_creates_all_required_tables(store):
    names = {
        row[0] for row in store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "users", "rbac_assignments", "biometric_template_metadata", "recognition_events",
        "suppression_records", "local_queue_items", "audit_events", "policy_config_metadata",
        "schema_migrations",
    } <= names
    assert store.connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == len(MIGRATIONS)


def test_users_roles_templates_and_append_only_idempotency(store):
    users = UserRepository(store)
    users.create("u-1", "Synthetic User")
    assert users.get_status("u-1") == UserStatus.ACTIVE
    users.set_status("u-1", UserStatus.SUSPENDED)
    assert users.active_user_ids() == set()
    users.set_status("u-1", UserStatus.ACTIVE)

    roles = RBACAssignmentRepository(store)
    roles.assign("u-1", "attendance-administrator", assigned_by="admin")
    assert roles.roles_for("u-1") == {"attendance-administrator"}
    TemplateMetadataRepository(store).add("t-1", "u-1", "mock-1", "1", "synthetic-hash")

    event = RecognitionEvent(
        event_id="e-1", idempotency_key="key-1", user_id="u-1", site_id="site",
        camera_id="cam", occurred_at=NOW, source=EventSource.FACE_ENCOUNTER,
        model_version="mock-1", policy_version="1", metadata={"source": "test"},
        storage_state=EventStorageState.RECORDED, correlation_id="corr-e-1",
        audit_metadata={"interaction": "test"},
    )
    events = EventRepository(store)
    events.append(event)
    assert events.get_by_idempotency("key-1")["event_id"] == "e-1"
    row = events.get_by_idempotency("key-1")
    assert row["storage_state"] == EventStorageState.RECORDED.value
    assert row["correlation_id"] == "corr-e-1"
    assert row["audit_metadata_json"] == '{"interaction":"test"}'
    with pytest.raises(IntegrityError):
        events.append(event)
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("UPDATE recognition_events SET metadata_json = '{}' WHERE event_id = ?", ("e-1",))
    assert len(events.list_events()) == 1


def test_suppression_audit_policy_metadata_and_queue_states(store):
    SuppressionRepository(store).record("s-1", "u-1", "cam", "cooldown", suppressed_at=NOW)
    assert SuppressionRepository(store).latest_for_user_camera("u-1", "cam") == NOW
    AuditRepository(store).append(AuditEvent(
        audit_id="a-1", occurred_at=NOW, actor_id="operator", action="queue:claim",
        outcome=AuditOutcome.SUCCESS, resource_type="queue", resource_id="q-1", metadata={},
    ))
    config = PolicyConfigRepository(store)
    config.set("cooldown_seconds", 300, "1", updated_at=NOW)
    assert config.get("cooldown_seconds")["value"] == 300

    queue = QueueRepository(store)
    queue.enqueue("q-1", "key-q-1", {"event_id": "e-1"}, enqueued_at=NOW)
    queue.enqueue("q-2", "key-q-2", {"event_id": "e-2"}, enqueued_at=NOW)
    claimed = queue.claim_pending(now=NOW, limit=1)
    assert len(claimed) == 1
    assert queue.count(QueueState.IN_FLIGHT) == 1
    queue.set_state("q-1", QueueState.SYNCED)
    assert queue.count(QueueState.SYNCED) == 1
    assert queue.expire_before(datetime(2024, 1, 1, tzinfo=UTC)) == 0


def test_queue_lease_reclaims_crashed_claim_and_preserves_idempotency(store):
    queue = QueueRepository(store)
    queue.enqueue("q-crash", "key-crash", {"event_id": "e-crash"}, enqueued_at=NOW)
    claimed = queue.claim_pending(now=NOW, lease_seconds=10, lease_owner="worker-1")
    assert claimed and queue.count(QueueState.IN_FLIGHT) == 1
    row = queue.get_by_idempotency("key-crash")
    assert row["lease_owner"] == "worker-1"
    assert queue.reclaim_stale_in_flight(now=NOW + timedelta(seconds=9)) == 0
    assert queue.reclaim_stale_in_flight(now=NOW + timedelta(seconds=10)) == 1
    assert queue.count(QueueState.PENDING) == 1
    with pytest.raises(IntegrityError):
        queue.enqueue("q-other", "key-crash", {"event_id": "e-crash"}, enqueued_at=NOW)


def test_queue_expiry_includes_in_flight_and_retry_clears_lease(store):
    queue = QueueRepository(store)
    old = NOW - timedelta(days=2)
    queue.enqueue("q-old", "key-old", {"event_id": "e-old"}, enqueued_at=old)
    queue.claim_pending(now=old, lease_seconds=60)
    assert queue.expire_before(NOW - timedelta(days=1)) == 1
    assert queue.count(QueueState.EXPIRED) == 1

    queue.enqueue("q-fail", "key-fail", {"event_id": "e-fail"}, enqueued_at=NOW)
    queue.claim_pending(now=NOW, lease_seconds=60)
    queue.set_state("q-fail", QueueState.FAILED, last_error="temporary", available_at=NOW)
    assert queue.retry_failed(now=NOW, limit=1) == 1
    row = queue.get_by_idempotency("key-fail")
    assert row["state"] == QueueState.PENDING.value
    assert row["lease_until"] is None and row["lease_owner"] is None


def test_retention_purge_is_explicit_audited_and_keeps_append_only_trigger(store):
    users = UserRepository(store)
    users.create("u-retain", "Retention User")
    old = NOW - timedelta(days=100)
    TemplateMetadataRepository(store).add(
        "t-retain", "u-retain", "model", "1", "hash", created_at=old,
    )
    store.connection.execute(
        "UPDATE biometric_template_metadata SET retired_at = ? WHERE template_id = ?",
        (old.isoformat(), "t-retain"),
    )
    EventRepository(store).append(RecognitionEvent(
        event_id="e-retain", idempotency_key="k-retain", user_id="u-retain",
        site_id="site", camera_id="cam", occurred_at=old,
        source=EventSource.FACE_ENCOUNTER, model_version="m", policy_version="p", metadata={},
    ))
    SuppressionRepository(store).record("s-retain", "u-retain", "cam", "cooldown", suppressed_at=old)
    QueueRepository(store).enqueue("q-retain", "kq-retain", {"user_id": "u-retain"}, enqueued_at=old)

    from lobby_attendance.application import RetentionService
    result = RetentionService(RetentionRepository(store), AuditRepository(store), users).purge_expired(
        now=NOW, retention_days=90, actor_id="operator-1",
    )
    assert result.deleted == {
        "recognition_events": 1,
        "suppression_records": 1,
        "local_queue_items": 1,
        "biometric_template_metadata": 1,
    }
    assert EventRepository(store).list_events() == []
    assert SuppressionRepository(store).latest_for_user_camera("u-retain", "cam") is None
    queue_count = QueueRepository(store).count()
    assert queue_count == 0
    assert store.connection.execute("SELECT COUNT(*) FROM biometric_template_metadata").fetchone()[0] == 0
    assert any(row["action"] == "retention:purge-expired" for row in AuditRepository(store).list_events())
    EventRepository(store).append(RecognitionEvent(
        event_id="e-new", idempotency_key="k-new", user_id="u-retain",
        site_id="site", camera_id="cam", occurred_at=NOW,
        source=EventSource.FACE_ENCOUNTER, model_version="m", policy_version="p", metadata={},
    ))
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("DELETE FROM recognition_events WHERE event_id = ?", ("e-new",))


ENCRYPTION_KEY = "11" * 32


def test_encrypted_store_round_trips_without_plaintext_sqlite_or_wal(tmp_path):
    path = tmp_path / "encrypted.sqlite3"
    with SQLiteStore(path, encryption_key=ENCRYPTION_KEY) as value:
        assert value.encrypted is True
        UserRepository(value).create("encrypted-user", "Encrypted User")

    envelope = path.read_bytes()
    assert envelope.startswith(b"LOBBYSQL1")
    assert b"SQLite format 3" not in envelope
    assert not path.with_name(path.name + "-wal").exists()
    assert not path.with_name(path.name + "-shm").exists()
    assert not path.with_name(path.name + ".tmp").exists()

    with SQLiteStore(path, encryption_key=ENCRYPTION_KEY) as reopened:
        reopened.initialize()
        assert UserRepository(reopened).get("encrypted-user")["display_name"] == "Encrypted User"

    with pytest.raises(ConfigurationError):
        SQLiteStore(path, encryption_key="22" * 32)


def test_encrypted_store_rejects_plaintext_database(tmp_path):
    path = tmp_path / "plaintext.sqlite3"
    with SQLiteStore(path) as value:
        value.initialize()

    with pytest.raises(ConfigurationError):
        SQLiteStore(path, encryption_key=ENCRYPTION_KEY)


def test_encrypted_store_rolls_back_context_manager_exceptions(tmp_path):
    path = tmp_path / "rollback.sqlite3"
    with pytest.raises(RuntimeError):
        with SQLiteStore(path, encryption_key=ENCRYPTION_KEY) as value:
            UserRepository(value).create("rolled-back", "Rolled Back")
            raise RuntimeError("synthetic failure")

    with SQLiteStore(path, encryption_key=ENCRYPTION_KEY) as reopened:
        reopened.initialize()
        assert UserRepository(reopened).get("rolled-back") is None
