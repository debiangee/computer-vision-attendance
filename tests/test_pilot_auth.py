from datetime import datetime, timedelta, timezone

from lobby_attendance.api import create_app
from lobby_attendance.api.auth import SignedTokenBoundary, issue_signed_token
from lobby_attendance.config import Settings
from lobby_attendance.rbac import Role
from lobby_attendance.storage import SQLiteStore
from lobby_attendance.storage.repositories import AuthTokenRevocationRepository

UTC = timezone.utc
KEY = b"pilot-auth-signing-key-0123456789"
ISSUER = "pilot-issuer"
AUDIENCE = "pilot-api"


def _token(*roles, token_kind="admin", token_id=None, auth_time=None, now=None, ttl_seconds=900, sites=("local-site",), subjects=("*",)):
    return issue_signed_token(
        KEY,
        subject="pilot-admin",
        roles=list(roles),
        issuer=ISSUER,
        audience=AUDIENCE,
        token_kind=token_kind,
        token_id=token_id,
        auth_time=auth_time,
        now=now,
        ttl_seconds=ttl_seconds,
        sites=sites,
        subjects=subjects,
    )


def _app(tmp_path):
    store = SQLiteStore(tmp_path / "pilot-auth.sqlite3")
    boundary = SignedTokenBoundary(
        signing_key=KEY,
        issuer=ISSUER,
        audience=AUDIENCE,
        revocation_checker=AuthTokenRevocationRepository(store).is_revoked,
    )
    app = create_app(
        Settings(database_path=tmp_path / "pilot-auth.sqlite3", development_mock_vision=True),
        store=store,
        token_boundary=boundary,
        testing=True,
    )
    return app, store


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_signed_sessions_require_tls_and_recent_auth_for_sensitive_actions(tmp_path):
    app, store = _app(tmp_path)
    token = _token(Role.ENROLLMENT_ADMINISTRATOR, token_id="enroll-session-0001")
    client = app.test_client()
    body = {"user_id": "pilot-user", "display_name": "Pilot User"}

    assert client.post("/api/admin/users", headers=_headers(token), json=body).status_code == 426
    secure = client.post(
        "/api/admin/users", headers=_headers(token), json=body, base_url="https://localhost",
    )
    assert secure.status_code == 201

    old = _token(
        Role.ENROLLMENT_ADMINISTRATOR,
        token_id="old-auth-session-01",
        auth_time=datetime.now(UTC) - timedelta(seconds=301),
    )
    reauth_required = client.post(
        "/api/admin/users", headers=_headers(old),
        json={"user_id": "old-user", "display_name": "Old User"},
        base_url="https://localhost",
    )
    assert reauth_required.status_code == 401
    assert reauth_required.get_json()["error"] == "reauthentication-required"
    store.close()


def test_signed_sessions_expire_and_cannot_cross_token_kind(tmp_path):
    app, store = _app(tmp_path)
    client = app.test_client()
    expired = _token(
        Role.ENROLLMENT_ADMINISTRATOR,
        token_id="expired-session-01",
        now=datetime.now(UTC) - timedelta(seconds=120),
        ttl_seconds=60,
    )
    assert client.post(
        "/api/admin/users", headers=_headers(expired),
        json={"user_id": "expired-user", "display_name": "Expired User"},
        base_url="https://localhost",
    ).status_code == 403

    kiosk = _token(Role.KIOSK_SERVICE, token_kind="kiosk", token_id="kiosk-session-0001")
    denied = client.get("/api/admin/events", headers=_headers(kiosk), base_url="https://localhost")
    assert denied.status_code == 403
    store.close()


def test_signed_session_revocation_is_durable_and_audited(tmp_path):
    app, store = _app(tmp_path)
    client = app.test_client()
    revoked_id = "revoked-session-01"
    user_token = _token(Role.ENROLLMENT_ADMINISTRATOR, token_id=revoked_id)
    admin_token = _token(Role.RBAC_ADMINISTRATOR, token_id="rbac-session-0001")
    expires_at = datetime.now(UTC) + timedelta(minutes=5)

    response = client.post(
        "/api/admin/auth/revoke",
        headers=_headers(admin_token),
        json={"token_id": revoked_id, "expires_at": expires_at.isoformat()},
        base_url="https://localhost",
    )
    assert response.status_code == 201
    assert response.get_json() == {"revoked": True}
    assert AuthTokenRevocationRepository(store).is_revoked(revoked_id)

    denied = client.post(
        "/api/admin/users",
        headers=_headers(user_token),
        json={"user_id": "revoked-user", "display_name": "Revoked User"},
        base_url="https://localhost",
    )
    assert denied.status_code == 403
    assert any(row["action"] == "authentication:revoke" for row in app.extensions["lobby_audit"].list_events())
    store.close()


def test_environment_signed_mode_requires_key_and_builds_signed_boundary(monkeypatch):
    from lobby_attendance.api.app import _token_boundary_from_env
    from lobby_attendance.errors import ConfigurationError

    monkeypatch.setenv("LOBBY_ATTENDANCE_AUTH_MODE", "signed")
    monkeypatch.delenv("LOBBY_ATTENDANCE_AUTH_SIGNING_KEY", raising=False)
    try:
        _token_boundary_from_env()
    except ConfigurationError as exc:
        assert "AUTH_SIGNING_KEY" in str(exc)
    else:
        raise AssertionError("signed authentication must require a signing key")

    monkeypatch.setenv("LOBBY_ATTENDANCE_AUTH_SIGNING_KEY", KEY.decode())
    monkeypatch.setenv("LOBBY_ATTENDANCE_AUTH_ISSUER", ISSUER)
    monkeypatch.setenv("LOBBY_ATTENDANCE_AUTH_AUDIENCE", AUDIENCE)
    boundary = _token_boundary_from_env()
    assert isinstance(boundary, SignedTokenBoundary)
    assert boundary.requires_tls is True


def test_authentication_failures_are_rate_limited_without_token_details(tmp_path):
    app, store = _app(tmp_path)
    client = app.test_client()
    for _ in range(10):
        response = client.get(
            "/api/admin/events", headers=_headers("not-a-valid-session"), base_url="https://localhost",
        )
        assert response.status_code == 403
    limited = client.get(
        "/api/admin/events", headers=_headers("not-a-valid-session"), base_url="https://localhost",
    )
    assert limited.status_code == 429
    assert "not-a-valid-session" not in limited.get_data(as_text=True)
    store.close()


def test_signed_sessions_enforce_subject_site_scope_and_role_separation(tmp_path):
    app, store = _app(tmp_path)
    client = app.test_client()
    limited = _token(
        Role.ENROLLMENT_ADMINISTRATOR,
        token_id="limited-session-01",
        subjects=("pilot-user",),
    )
    assert client.post(
        "/api/admin/users", headers=_headers(limited),
        json={"user_id": "pilot-user", "display_name": "Pilot User"},
        base_url="https://localhost",
    ).status_code == 201
    outside_subject = client.post(
        "/api/admin/users", headers=_headers(limited),
        json={"user_id": "other-user", "display_name": "Other User"},
        base_url="https://localhost",
    )
    assert outside_subject.status_code == 403
    users = client.get("/api/admin/users", headers=_headers(limited), base_url="https://localhost")
    assert [row["user_id"] for row in users.get_json()["users"]] == ["pilot-user"]

    outside_site = _token(
        Role.ATTENDANCE_ADMINISTRATOR,
        token_id="outside-site-session",
        sites=("other-site",),
    )
    assert client.get(
        "/api/admin/events", headers=_headers(outside_site), base_url="https://localhost",
    ).status_code == 403

    conflicting_roles = _token(
        Role.ENROLLMENT_ADMINISTRATOR,
        Role.ATTENDANCE_ADMINISTRATOR,
        token_id="conflicting-session",
    )
    assert client.get(
        "/api/admin/events", headers=_headers(conflicting_roles), base_url="https://localhost",
    ).status_code == 403
    store.close()
