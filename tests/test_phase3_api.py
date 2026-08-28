from datetime import datetime, timezone

import pytest

from lobby_attendance.api import create_app
from lobby_attendance.api.auth import TokenBoundary
from lobby_attendance.api.app import _token_boundary_from_env
from lobby_attendance.config import Settings
from lobby_attendance.errors import ConfigurationError
from lobby_attendance.domain import EventSource, QueueState, RecognitionEvent, UserStatus
from lobby_attendance.rbac import Permission, Role
from lobby_attendance.storage import SQLiteStore
from lobby_attendance.storage.repositories import AuditRepository, CorrectionRepository, EventRepository, QueueRepository, UserRepository
from lobby_attendance.vision import MockVisionProvider

UTC = timezone.utc


ALL_ADMIN_ROLES = frozenset({
    Role.ENROLLMENT_ADMINISTRATOR,
    Role.ATTENDANCE_ADMINISTRATOR,
    Role.AUDITOR,
    Role.SYSTEM_OPERATOR,
    Role.RBAC_ADMINISTRATOR,
})


def _app(tmp_path, *, roles=None, admin_token="admin-secret", kiosk_token="kiosk-secret", provider=None, admin_subject="configured-admin", event_sink=None, settings=None):
    store = SQLiteStore(tmp_path / "api.sqlite3")
    boundary = TokenBoundary(
        admin_token=admin_token,
        kiosk_token=kiosk_token,
        admin_subject=admin_subject,
        admin_roles=frozenset(ALL_ADMIN_ROLES if roles is None else roles),
    )
    app = create_app(
        settings or Settings(database_path=tmp_path / "api.sqlite3", development_mock_vision=True, development_mock_compliance_approval=True),
        store=store, provider=provider or MockVisionProvider(identity_id="synthetic-user"),
        event_sink=event_sink, token_boundary=boundary, testing=True,
    )
    return app, store


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_health_and_missing_token_denial(tmp_path):
    app, store = _app(tmp_path)
    client = app.test_client()
    health = client.get("/api/health")
    assert health.status_code == 200
    body = health.get_json()
    assert body["database"] == "ready"
    assert body["queue"] == "ready"
    assert body["camera"] == "ready"
    assert "secret" not in str(body).lower()
    assert client.get("/api/admin/events").status_code == 403
    store.close()


def test_kiosk_is_safe_and_records_only_safe_state(tmp_path):
    app, store = _app(tmp_path)
    UserRepository(store).create("synthetic-user", "Synthetic User", status=UserStatus.ACTIVE)
    client = app.test_client()
    response = client.post("/api/kiosk/interaction", headers=bearer("kiosk-secret"), json={})
    assert response.status_code == 200
    body = response.get_json()
    assert body["state"] == "recognized-event-recorded"
    assert set(body) == {"state", "message"}
    assert "confidence" not in str(body).lower()
    assert "template" not in str(body).lower()
    assert "synthetic-user" not in str(body)
    store.close()


def test_admin_enrollment_event_access_and_rbac_denial(tmp_path):
    app, store = _app(tmp_path)
    client = app.test_client()
    created = client.post("/api/admin/users", headers=bearer("admin-secret"), json={"user_id": "u-1", "display_name": "Test User"})
    assert created.status_code == 201
    assert created.get_json()["status"] == "suspended"
    assert client.post(
        "/api/admin/templates", headers=bearer("admin-secret"),
        json={
            "template_id": "t-u-1", "user_id": "u-1", "model_version": "mock-1",
            "template_version": "1", "protected_template_hash": "synthetic-hash",
        },
    ).status_code == 201
    assert client.post("/api/admin/users/u-1/status", headers=bearer("admin-secret"), json={"status": "active"}).status_code == 200
    assert client.post("/api/admin/users/u-1/roles", headers=bearer("admin-secret"), json={"role": "auditor"}).status_code == 200
    users = client.get("/api/admin/users", headers=bearer("admin-secret"))
    assert users.status_code == 200 and users.get_json()["users"][0]["display_name"] == "Test User"
    events = client.get("/api/admin/events", headers=bearer("admin-secret"))
    assert events.status_code == 200 and events.get_json()["events"] == []
    app2, store2 = _app(tmp_path / "restricted", roles={Role.AUDITOR})
    assert app2.test_client().post("/api/admin/users", headers=bearer("admin-secret"), json={"user_id": "x", "display_name": "X"}).status_code == 403
    store.close()
    store2.close()


def test_queue_status_and_operations_require_operator_scope(tmp_path):
    app, store = _app(tmp_path)
    users = UserRepository(store)
    users.create("u-queue", "Queue User")
    QueueRepository(store).enqueue("q-1", "key-1", {"event_id": "evt-1"}, enqueued_at=datetime.now(UTC))
    client = app.test_client()
    queue = client.get("/api/admin/queue", headers=bearer("admin-secret"))
    assert queue.status_code == 200
    assert queue.get_json()["pending"] == 1
    claim = client.post("/api/admin/queue/claim", headers=bearer("admin-secret"))
    assert claim.status_code == 200 and claim.get_json()["claimed"][0]["state"] == QueueState.IN_FLIGHT.value
    app2, store2 = _app(tmp_path / "restricted-queue", roles={Role.AUDITOR})
    assert app2.test_client().get("/api/admin/queue", headers=bearer("admin-secret")).status_code == 403
    store.close()
    store2.close()


def test_kiosk_and_admin_pages_render_neutral_ui(tmp_path):
    app, store = _app(tmp_path)
    client = app.test_client()
    kiosk = client.get("/kiosk")
    admin = client.get("/admin")
    assert kiosk.status_code == 200
    assert admin.status_code == 200
    assert b"Time In" not in kiosk.data and b"Time Out" not in kiosk.data
    assert b"Template metadata ID" in admin.data
    store.close()


def test_missing_config_fails_closed_for_admin_mutation(tmp_path):
    store = SQLiteStore(tmp_path / "missing.sqlite3")
    app = create_app(Settings(database_path=tmp_path / "missing.sqlite3", development_mock_vision=True), store=store, token_boundary=TokenBoundary(), testing=True)
    response = app.test_client().post("/api/admin/users", json={"user_id": "u", "display_name": "U"})
    assert response.status_code == 503
    assert response.get_json()["error"] == "configuration-error"
    store.close()


def test_kiosk_rejects_caller_controlled_event_time(tmp_path):
    app, store = _app(tmp_path)
    UserRepository(store).create("synthetic-user", "Synthetic User", status=UserStatus.ACTIVE)
    client = app.test_client()
    response = client.post(
        "/api/kiosk/interaction",
        headers=bearer("kiosk-secret"),
        json={"occurred_at": "1999-01-01T00:00:00Z"},
    )
    assert response.status_code == 400
    assert response.get_json() == {
        "error": "invalid-request",
        "message": "occurred_at is not accepted; server time is used",
    }
    assert EventRepository(store).list_events() == []
    store.close()


def test_configured_admin_roles_are_explicit_and_restrict_permissions(tmp_path):
    app, store = _app(tmp_path, roles={Role.AUDITOR}, admin_subject="auditor-7")
    client = app.test_client()
    assert client.get("/api/admin/events", headers=bearer("admin-secret")).status_code == 200
    assert client.post(
        "/api/admin/users", headers=bearer("admin-secret"),
        json={"user_id": "u-1", "display_name": "Test User"},
    ).status_code == 403
    store.close()


def test_admin_token_requires_explicit_roles_from_environment(monkeypatch):
    monkeypatch.setenv("LOBBY_ATTENDANCE_ADMIN_TOKEN", "configured-secret")
    monkeypatch.delenv("LOBBY_ATTENDANCE_ADMIN_ROLES", raising=False)
    with pytest.raises(ConfigurationError, match="ADMIN_ROLES is required"):
        _token_boundary_from_env()


def test_mutation_audit_uses_authenticated_subject_and_denials_are_bounded(tmp_path):
    app, store = _app(tmp_path, admin_subject="enrollment-operator")
    client = app.test_client()
    denied = client.get("/api/admin/events", headers=bearer("wrong-secret"))
    assert denied.status_code == 403
    created = client.post(
        "/api/admin/users", headers=bearer("admin-secret"),
        json={"user_id": "u-1", "display_name": "Test User"},
    )
    assert created.status_code == 201
    rows = AuditRepository(store).list_events(limit=10)
    assert any(row["actor_id"] == "enrollment-operator" and row["action"] == "enrollment:create" for row in rows)
    denied_rows = [row for row in rows if row["action"] == "authorization:denied"]
    assert denied_rows and denied_rows[0]["actor_id"] is None
    assert "wrong-secret" not in str(denied_rows[0])
    store.close()


def test_api_rejects_oversized_or_invalid_fields_without_exception_details(tmp_path):
    app, store = _app(tmp_path)
    client = app.test_client()
    response = client.post(
        "/api/admin/users", headers=bearer("admin-secret"),
        json={"user_id": "bad id", "display_name": "x" * 201},
    )
    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid-request", "message": "request fields are invalid"}
    template = client.post(
        "/api/admin/templates", headers=bearer("admin-secret"),
        json={"template_id": "t-1", "user_id": "missing", "model_version": "m", "template_version": "v", "protected_template_hash": "h"},
    )
    assert template.status_code == 400
    assert "does not exist" not in template.get_data(as_text=True)
    store.close()


def test_security_headers_are_present_on_local_pages(tmp_path):
    app, store = _app(tmp_path)
    response = app.test_client().get("/kiosk")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    store.close()


def _append_event(store, *, event_id="evt-1", user_id="u-1"):
    UserRepository(store).create(user_id, "User", status=UserStatus.ACTIVE)
    EventRepository(store).append(RecognitionEvent(
        event_id=event_id, idempotency_key="key-" + event_id, user_id=user_id,
        site_id="site", camera_id="camera", occurred_at=datetime.now(UTC),
        source=EventSource.FACE_ENCOUNTER, model_version="model-1", policy_version="policy-1",
        metadata={"event_type": "RECOGNIZED_ENCOUNTER"}, correlation_id="corr-" + event_id,
        audit_metadata={"interaction": "test"},
    ))


def test_activation_requires_explicit_compliance_and_audits_denial(tmp_path):
    store = SQLiteStore(tmp_path / "blocked.sqlite3")
    app = create_app(
        Settings(database_path=tmp_path / "blocked.sqlite3", development_mock_vision=True),
        store=store, token_boundary=TokenBoundary(
            admin_token="admin-secret", admin_roles=frozenset({Role.ENROLLMENT_ADMINISTRATOR}),
        ), testing=True,
    )
    client = app.test_client()
    assert client.post("/api/admin/users", headers=bearer("admin-secret"), json={"user_id": "u-1", "display_name": "User"}).status_code == 201
    response = client.post("/api/admin/users/u-1/status", headers=bearer("admin-secret"), json={"status": "active"})
    assert response.status_code == 409
    assert response.get_json() == {"error": "compliance-not-approved", "message": "biometric activation is not approved"}
    assert UserRepository(store).get_status("u-1") is UserStatus.SUSPENDED
    denied = [row for row in AuditRepository(store).list_events() if row["action"] == "enrollment:activate"]
    assert denied and denied[0]["outcome"] == "denied" and denied[0]["actor_id"] == "configured-admin"
    assert client.get("/api/health").get_json()["compliance_gate"] == "pending"
    store.close()


def test_compliance_approved_activation_and_health_state(tmp_path):
    app, store = _app(tmp_path, roles={Role.ENROLLMENT_ADMINISTRATOR})
    client = app.test_client()
    assert client.post("/api/admin/users", headers=bearer("admin-secret"), json={"user_id": "u-1", "display_name": "User"}).status_code == 201
    assert client.post(
        "/api/admin/templates", headers=bearer("admin-secret"),
        json={
            "template_id": "t-u-1", "user_id": "u-1", "model_version": "mock-1",
            "template_version": "1", "protected_template_hash": "synthetic-hash",
        },
    ).status_code == 201
    assert client.post("/api/admin/users/u-1/status", headers=bearer("admin-secret"), json={"status": "active"}).status_code == 200
    health = client.get("/api/health").get_json()
    assert health["compliance_gate"] == "approved"
    assert health["biometric_activation_enabled"] is True
    store.close()


def test_correction_is_immutable_audited_and_role_bound(tmp_path):
    app, store = _app(tmp_path)
    _append_event(store)
    client = app.test_client()
    response = client.post(
        "/api/admin/events/evt-1/corrections", headers=bearer("admin-secret"),
        json={"reason": "operator verified timestamp", "changes": {"site_id": "site-corrected"}},
    )
    assert response.status_code == 201
    correction = response.get_json()["correction"]
    assert correction["before"]["site_id"] == "site"
    assert correction["after"]["site_id"] == "site-corrected"
    assert EventRepository(store).get_by_id("evt-1")["site_id"] == "site"
    history = CorrectionRepository(store).list_for_event("evt-1")
    assert len(history) == 1 and history[0]["actor_id"] == "configured-admin"
    assert any(row["action"] == "attendance:correction" for row in AuditRepository(store).list_events())
    restricted, restricted_store = _app(tmp_path / "restricted-correction", roles={Role.AUDITOR})
    assert restricted.test_client().post(
        "/api/admin/events/evt-1/corrections", headers=bearer("admin-secret"),
        json={"reason": "x", "changes": {"site_id": "nope"}},
    ).status_code == 403
    store.close()
    restricted_store.close()


def test_export_is_redacted_audited_and_validates_correction_input(tmp_path):
    app, store = _app(tmp_path)
    _append_event(store)
    client = app.test_client()
    exported = client.get("/api/admin/events/export", headers=bearer("admin-secret"))
    assert exported.status_code == 200
    body = exported.get_json()
    assert body["events"][0]["event_id"] == "evt-1"
    assert "metadata" not in body["events"][0]
    assert "templates" not in str(body).lower() and "secrets" not in str(body).lower()
    assert any(row["action"] == "attendance:export" and row["actor_id"] == "configured-admin" for row in AuditRepository(store).list_events())
    invalid = client.post(
        "/api/admin/events/evt-1/corrections", headers=bearer("admin-secret"),
        json={"reason": "x", "changes": {"metadata": "leak"}},
    )
    assert invalid.status_code == 400
    store.close()


class _FailingSink:
    def send(self, payload):
        raise RuntimeError("must not be returned")


def test_queue_operations_audit_failures_and_safe_operator_state(tmp_path):
    app, store = _app(tmp_path, event_sink=_FailingSink(), roles={Role.SYSTEM_OPERATOR})
    QueueRepository(store).enqueue("q-1", "key-q-1", {"event_id": "evt-1"}, enqueued_at=datetime.now(UTC))
    client = app.test_client()
    assert client.post("/api/admin/queue/claim", headers=bearer("admin-secret")).status_code == 200
    # Return the claimed item to pending so synchronization owns the claim.
    QueueRepository(store).set_state("q-1", QueueState.PENDING)
    sync = client.post("/api/admin/queue/synchronize", headers=bearer("admin-secret"))
    assert sync.status_code == 200
    queue_body = sync.get_json()["queue"]
    assert queue_body["operator_state"] == "synchronization-failure"
    assert queue_body["action_required"] is True
    assert "must not be returned" not in str(sync.get_json())
    client.post("/api/admin/queue/retry", headers=bearer("admin-secret"))
    client.post("/api/admin/queue/expire", headers=bearer("admin-secret"))
    actions = {row["action"] for row in AuditRepository(store).list_events()}
    assert {"queue:claim", "queue:synchronize", "queue:retry", "queue:expire"} <= actions
    failure = [row for row in AuditRepository(store).list_events() if row["action"] == "queue:synchronize"]
    assert failure and failure[0]["outcome"] == "failure" and failure[0]["actor_id"] == "configured-admin"
    store.close()


def test_queue_full_is_distinct_safe_state(tmp_path):
    settings = Settings(
        database_path=tmp_path / "full.sqlite3", queue_max_size=1,
        development_mock_vision=True, development_mock_compliance_approval=True,
    )
    app, store = _app(tmp_path, settings=settings, roles={Role.SYSTEM_OPERATOR})
    QueueRepository(store).enqueue("q-1", "key-q-1", {"event_id": "evt-1"}, enqueued_at=datetime.now(UTC))
    body = app.test_client().get("/api/admin/queue", headers=bearer("admin-secret")).get_json()
    assert body["operator_state"] == "queue-full"
    assert body["capacity"] == 1 and body["active_count"] == 1
    store.close()


def test_compliance_approved_activation_requires_protected_template(tmp_path):
    app, store = _app(tmp_path, roles={Role.ENROLLMENT_ADMINISTRATOR})
    client = app.test_client()
    assert client.post(
        "/api/admin/users", headers=bearer("admin-secret"),
        json={"user_id": "u-no-template", "display_name": "No Template"},
    ).status_code == 201

    response = client.post(
        "/api/admin/users/u-no-template/status",
        headers=bearer("admin-secret"), json={"status": "active"},
    )

    assert response.status_code == 409
    assert response.get_json() == {
        "error": "template-lifecycle-incomplete",
        "message": "biometric activation requires a protected template",
    }
    assert UserRepository(store).get_status("u-no-template") is UserStatus.SUSPENDED
    denied = [
        row for row in AuditRepository(store).list_events()
        if row["action"] == "enrollment:activate"
    ]
    assert denied and denied[0]["outcome"] == "denied"
    store.close()



def test_factory_wires_encrypted_storage_and_request_commit(tmp_path):
    key = "33" * 32
    database_path = tmp_path / "factory-encrypted.sqlite3"
    settings = Settings(
        database_path=database_path,
        storage_encryption_key=key,
        storage_encryption_required=True,
        development_mock_vision=True,
        development_mock_compliance_approval=True,
    )
    app = create_app(
        settings,
        provider=MockVisionProvider(identity_id="synthetic-user"),
        token_boundary=TokenBoundary(
            admin_token="admin-secret", kiosk_token="kiosk-secret", admin_roles=ALL_ADMIN_ROLES,
        ),
        testing=True,
    )
    store = app.extensions["lobby_store"]
    assert store.encrypted is True
    UserRepository(store).create("encrypted-app-user", "Encrypted App User")
    assert app.test_client().get("/api/health").status_code == 200
    app.extensions["lobby_close_store"]()

    with SQLiteStore(database_path, encryption_key=key) as reopened:
        reopened.initialize()
        assert UserRepository(reopened).get("encrypted-app-user")["display_name"] == "Encrypted App User"


def test_factory_rejects_unencrypted_injected_store_when_encryption_required(tmp_path):
    path = tmp_path / "injected-plaintext.sqlite3"
    store = SQLiteStore(path)
    try:
        store.initialize()
        with pytest.raises(ConfigurationError, match="encrypted storage is required"):
            create_app(
                Settings(
                    database_path=path,
                    storage_encryption_key="44" * 32,
                    storage_encryption_required=True,
                    development_mock_vision=True,
                ),
                store=store,
                provider=MockVisionProvider(identity_id="synthetic-user"),
                testing=True,
            )
    finally:
        store.close()
