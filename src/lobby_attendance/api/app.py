"""Flask application factory and protected API routes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from threading import Lock
from uuid import uuid4
from typing import Any

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from ..audit import AuditEvent
from ..application import (
    AttendanceAdminService,
    EnrollmentService,
    InMemoryEventSink,
    QueueSynchronizer,
    RecognitionEventService,
    RecognitionPipeline,
    RetentionService,
)
from ..config import Settings
from ..domain import AuditOutcome, QueueState, UserStatus
from ..errors import AuthorizationError, ComplianceApprovalError, ConfigurationError, IntegrityError, TemplateLifecycleError
from ..rbac import Permission, Role
from ..storage import SQLiteStore
from ..storage.repositories import (
    AuditRepository,
    AuthTokenRevocationRepository,
    CorrectionRepository,
    EventRepository,
    QueueRepository,
    RBACAssignmentRepository,
    RetentionRepository,
    SuppressionRepository,
    TemplateMetadataRepository,
    UserRepository,
)
from ..vision import MockVisionProvider, OpenCVVisionProvider
from ..vision.local_matcher import LocalMatcher
from ..vision.opencv import demo_presence_liveness_checker
from .auth import AuthAttemptLimiter, SignedTokenBoundary, TokenBoundary, authenticated_principal, protected

UTC = timezone.utc
SAFE_MESSAGES = {
    "recognized-event-recorded": "Recognition event recorded.",
    "duplicate-suppressed": "This recognition event was already received.",
    "cooldown-suppressed": "Recognition event suppressed by the lobby cooldown.",
    "event-queued-locally": "Recognition event queued locally for synchronization.",
    "unknown": "Person not recognized.",
    "ambiguous": "Identity could not be confirmed.",
    "liveness-failed": "Liveness check could not be completed.",
    "low-quality": "The camera view needs better quality.",
    "no-face": "No face detected.",
    "multiple-faces": "Please have one person in view.",
    "unavailable": "Recognition is temporarily unavailable.",
}


def create_app(
    settings: Settings | None = None,
    *,
    provider: Any | None = None,
    store: SQLiteStore | None = None,
    event_sink: Any | None = None,
    token_boundary: TokenBoundary | None = None,
    testing: bool = False,
) -> Flask:
    settings = (settings or Settings.from_env()).validate()
    owns_store = store is None
    db = store or SQLiteStore(
        settings.database_path,
        encryption_key=settings.storage_encryption_key,
    )
    if settings.storage_encryption_required and not db.encrypted:
        if owns_store:
            db.close()
        raise ConfigurationError("encrypted storage is required")
    db.initialize()
    app = Flask(__name__, template_folder="../ui/templates", static_folder="../ui/static")
    app.config.update(TESTING=testing, MAX_CONTENT_LENGTH=64 * 1024)
    
    @app.after_request
    def _security_headers(response):
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.errorhandler(RequestEntityTooLarge)
    def _request_too_large(_error):
        return jsonify(error="invalid-request", message="request body is too large"), 413

    @app.errorhandler(Exception)
    def _unexpected_error(error):
        if isinstance(error, HTTPException):
            return error
        app.logger.exception("unhandled request failure")
        return jsonify(error="internal-error", message="service unavailable"), 503

    auth_revocations = AuthTokenRevocationRepository(db)
    boundary = token_boundary or _token_boundary_from_env(
        revocation_checker=auth_revocations.is_revoked,
    )
    app.extensions["lobby_token_boundary"] = boundary
    app.extensions["lobby_store"] = db
    app.extensions["lobby_owns_store"] = owns_store

    def close_owned_store() -> None:
        if owns_store and db.connection is not None:
            db.close()

    app.extensions["lobby_close_store"] = close_owned_store

    users = UserRepository(db)
    events = EventRepository(db)
    queue = QueueRepository(db)
    audit = AuditRepository(db)
    templates = TemplateMetadataRepository(db)
    roles = RBACAssignmentRepository(db)
    retention = RetentionService(RetentionRepository(db), audit, users)
    event_sink = event_sink or InMemoryEventSink()
    demo_matcher = LocalMatcher(
        matcher_version=settings.matcher_version,
        crop_size=settings.matcher_crop_size,
        threshold=settings.matcher_threshold,
        margin=settings.matcher_margin,
    ) if settings.executive_demo_mode else None
    vision_provider = provider or _default_provider(settings, matcher=demo_matcher)
    model_version = getattr(vision_provider, "model_version", None)
    if not isinstance(model_version, str) or not model_version:
        model_version = "mock-1" if settings.development_mock_vision else "unavailable"
    activation_approved = settings.compliance_approved or (
        testing and settings.development_mock_vision and settings.development_mock_compliance_approval
    )
    enrollment = EnrollmentService(
        users, templates, audit, retention, compliance_approved=activation_approved,
        demo_mode=settings.executive_demo_mode, matcher=demo_matcher,
    )
    corrections = CorrectionRepository(db)
    attendance_admin = AttendanceAdminService(events, corrections, users, audit)
    event_service = RecognitionEventService(
        users, events, None if settings.executive_demo_mode else queue,
        suppressions=SuppressionRepository(db), audit=audit,
        site_id=settings.site_id, camera_id=settings.camera_id,
        cooldown_seconds=settings.cooldown_seconds,
        model_version=model_version,
        queue_max_size=settings.queue_max_size,
        event_sink=None,
        compliance_approved=activation_approved,
    )
    pipeline = RecognitionPipeline(vision_provider, event_service, settings=settings)
    synchronizer = QueueSynchronizer(
        queue, event_sink, max_age_seconds=settings.queue_max_age_seconds,
        lease_seconds=settings.queue_lease_seconds, audit=audit,
    )
    camera_lock = Lock()
    app.extensions.update(
        lobby_users=users, lobby_events=events, lobby_queue=queue, lobby_audit=audit,
        lobby_auth_revocations=auth_revocations,
        lobby_auth_limiter=AuthAttemptLimiter(),
        lobby_templates=templates, lobby_roles=roles, lobby_enrollment=enrollment,
        lobby_corrections=corrections, lobby_attendance_admin=attendance_admin,
        lobby_retention=retention, lobby_pipeline=pipeline, lobby_synchronizer=synchronizer,
        lobby_provider=vision_provider, lobby_settings=settings, lobby_compliance_approved=activation_approved,
        lobby_demo_matcher=demo_matcher,
        # One lock covers every server-camera operation in this process. The
        # aliases preserve extension compatibility while preventing enrollment
        # and kiosk recognition from opening the camera concurrently.
        lobby_demo_lock=camera_lock,
        lobby_interaction_lock=camera_lock,
        lobby_camera_lock=camera_lock,
        lobby_demo_state={"last_action": "none"},
    )

    @app.teardown_appcontext
    def _commit_or_rollback(error: BaseException | None) -> None:
        if error is None:
            db.commit()
        else:
            db.connection.rollback()

    @app.get("/health")
    @app.get("/api/health")
    def health():
        return jsonify(_health(app))

    @app.get("/kiosk")
    def kiosk_page():
        return render_template("kiosk.html")

    @app.get("/admin")
    def admin_page():
        return render_template("admin.html")

    @app.post("/api/kiosk/interaction")
    @protected(Permission.APPEND_RECOGNITION_EVENT, token_kind="kiosk")
    def kiosk_interaction():
        if "occurred_at" in _body():
            return jsonify(error="invalid-request", message="occurred_at is not accepted; server time is used"), 400
        try:
            # Serialize access to the physical camera within this process. A
            # deployment with multiple workers still needs an external lock.
            with app.extensions["lobby_camera_lock"]:
                result = pipeline.process_interaction()
        except Exception:
            return jsonify(state="unavailable", message=SAFE_MESSAGES["unavailable"]), 503
        state = result.state
        if result.submission and result.submission.reason == "event-storage-unavailable":
            state = "unavailable"
        if state not in SAFE_MESSAGES:
            state = "unavailable"
        status = 503 if state == "unavailable" else 200
        return jsonify(state=state, message=SAFE_MESSAGES[state]), status

    @app.get("/api/admin/events")
    @protected(Permission.VIEW_ATTENDANCE_EVENTS)
    def list_events():
        limit = _limit()
        rows = events.list_events(
            limit=limit, site_ids=_site_scope(), subject_ids=_subject_scope(),
        )
        return jsonify(events=[_event_json(row) for row in rows])

    @app.post("/api/admin/events/<event_id>/corrections")
    @protected(Permission.CORRECT_ATTENDANCE_EVENTS, require_recent_auth=True)
    def correct_event(event_id: str):
        if not _is_identifier(event_id, max_length=128):
            return _invalid_request()
        body = _body()
        try:
            reason = _validated_field(body, "reason", max_length=500)
            changes = body.get("changes")
            if not isinstance(changes, dict):
                raise ValueError("changes must be an object")
            result = attendance_admin.correct(
                event_id, reason=reason, changes=changes,
                actor_id=_principal_subject() or "unknown-actor",
                site_ids=_site_scope(), subject_ids=_subject_scope(),
            )
        except AuthorizationError:
            return _scope_denied()
        except LookupError:
            return jsonify(error="not-found", message="event does not exist"), 404
        except (TypeError, ValueError):
            return _invalid_request()
        return jsonify(correction=result), 201

    @app.get("/api/admin/events/export")
    @protected(Permission.EXPORT_ATTENDANCE, require_recent_auth=True)
    def export_events():
        try:
            exported = attendance_admin.export(
                limit=_limit(), actor_id=_principal_subject() or "unknown-actor",
                site_ids=_site_scope(), subject_ids=_subject_scope(),
            )
        except ValueError:
            return _invalid_request()
        return jsonify(events=exported)

    @app.get("/api/admin/users")
    @protected(Permission.MANAGE_ENROLLMENT)
    def list_users():
        limit = _limit()
        return jsonify(users=[_user_json(row, roles.roles_for(row["user_id"])) for row in users.list_users(
            limit=limit, subject_ids=_subject_scope(),
        )])

    @app.post("/api/admin/users")
    @protected(Permission.MANAGE_ENROLLMENT, require_recent_auth=True)
    def create_user():
        body = _body()
        try:
            user_id = _validated_field(body, "user_id", max_length=64, identifier=True)
            display_name = _validated_field(body, "display_name", max_length=200)
        except ValueError:
            return _invalid_request()
        if not _subject_allowed(user_id):
            return _scope_denied()
        try:
            enrollment.create_user(user_id, display_name, actor_id=_principal_subject())
        except (IntegrityError, sqlite3.IntegrityError):
            return jsonify(error="conflict", message="user already exists"), 409
        return jsonify(user_id=user_id, status=UserStatus.SUSPENDED.value), 201

    @app.post("/api/admin/users/<user_id>/status")
    @protected(Permission.MANAGE_ENROLLMENT, require_recent_auth=True)
    def set_user_status(user_id: str):
        if not _is_identifier(user_id, max_length=64):
            return _invalid_request()
        if not _subject_allowed(user_id):
            return _scope_denied()
        if users.get(user_id) is None:
            return jsonify(error="not-found", message="user does not exist"), 404
        body = _body()
        status = body.get("status")
        try:
            if status == UserStatus.ACTIVE.value:
                enrollment.activate(user_id, actor_id=_principal_subject())
            elif status == UserStatus.SUSPENDED.value:
                enrollment.suspend(user_id, actor_id=_principal_subject())
            elif status == UserStatus.DEACTIVATED.value:
                enrollment.de_enroll(user_id, actor_id=_principal_subject())
            else:
                return jsonify(error="invalid-request", message="status must be active, suspended, or deactivated"), 400
        except ComplianceApprovalError:
            return jsonify(error="compliance-not-approved", message="biometric activation is not approved"), 409
        except TemplateLifecycleError:
            return jsonify(
                error="template-lifecycle-incomplete",
                message="biometric activation requires a protected template",
            ), 409
        except (ValueError, IntegrityError):
            return jsonify(error="not-found", message="user does not exist"), 404
        return jsonify(user_id=user_id, status=status)

    @app.post("/api/admin/demo/enrollment")
    @protected(Permission.MANAGE_ENROLLMENT, require_recent_auth=True)
    def demo_enrollment():
        if not settings.executive_demo_mode:
            return jsonify(error="not-found", message="demo mode is disabled"), 404
        body = _body()
        try:
            user_id = _validated_field(body, "user_id", max_length=64, identifier=True)
            display_name = _validated_field(body, "display_name", max_length=200)
        except ValueError:
            return _invalid_request()
        if not _subject_allowed(user_id):
            return _scope_denied()
        if not activation_approved:
            return jsonify(error="compliance-not-approved", message="biometric activation is not approved"), 409
        matcher = app.extensions.get("lobby_demo_matcher")
        capture = getattr(vision_provider, "capture_enrollment_samples", None)
        if not isinstance(matcher, LocalMatcher) or not callable(capture):
            return jsonify(state="unavailable", message=SAFE_MESSAGES["unavailable"]), 503
        with app.extensions["lobby_camera_lock"]:
            existing = users.get(user_id)
            if existing is not None and existing["status"] == UserStatus.DEACTIVATED.value:
                return jsonify(error="conflict", message="user is deactivated"), 409
            try:
                if existing is None:
                    enrollment.create_user(user_id, display_name, actor_id=_principal_subject())
                crops = capture(
                    sample_count=settings.enrollment_sample_count,
                    until=datetime.now(UTC) + timedelta(seconds=settings.interaction_timeout_seconds),
                    interval_seconds=settings.sampling_interval_seconds,
                )
                if len(crops) != settings.enrollment_sample_count:
                    return jsonify(state="unavailable", message=SAFE_MESSAGES["unavailable"]), 503
                enrollment.register_demo_template(
                    template_id="demo-" + uuid4().hex,
                    user_id=user_id,
                    crops=crops,
                    model_version=model_version,
                    actor_id=_principal_subject(),
                )
            except ComplianceApprovalError:
                return jsonify(error="compliance-not-approved", message="biometric activation is not approved"), 409
            except (TemplateLifecycleError, ValueError):
                return jsonify(state="unavailable", message=SAFE_MESSAGES["unavailable"]), 503
            except (IntegrityError, sqlite3.IntegrityError):
                return jsonify(error="conflict", message="user enrollment could not be completed"), 409
            app.extensions["lobby_demo_state"]["last_action"] = "enrolled"
            app.extensions["lobby_demo_state"].setdefault("user_ids", set()).add(user_id)
        return jsonify(user_id=user_id, status=UserStatus.ACTIVE.value, matcher_version=matcher.matcher_version), 201

    @app.get("/api/admin/demo/status")
    @protected(Permission.MANAGE_ENROLLMENT)
    def demo_status():
        if not settings.executive_demo_mode:
            return jsonify(enabled=False, state="disabled")
        matcher = app.extensions.get("lobby_demo_matcher")
        provider_ready = isinstance(vision_provider, OpenCVVisionProvider) and bool(vision_provider.model_digest)
        ready = bool(matcher and settings.demo_liveness_enabled and activation_approved and provider_ready)
        return jsonify(
            enabled=True,
            state="ready" if ready else "unavailable",
            compliance_gate="approved" if activation_approved else "pending",
            liveness="enabled" if settings.demo_liveness_enabled else "disabled",
            templates=matcher.template_count if matcher else 0,
        )

    @app.post("/api/admin/demo/reset")
    @protected(Permission.MANAGE_ENROLLMENT, require_recent_auth=True)
    def demo_reset():
        if not settings.executive_demo_mode:
            return jsonify(error="not-found", message="demo mode is disabled"), 404
        body = _body()
        if body.get("confirm") is not True:
            return jsonify(error="invalid-request", message="explicit confirmation is required"), 400
        user_id = body.get("user_id")
        if user_id is not None:
            if not isinstance(user_id, str) or not _is_identifier(user_id.strip(), max_length=64):
                return _invalid_request()
            if not _subject_allowed(user_id.strip()):
                return _scope_denied()
        with app.extensions["lobby_camera_lock"]:
            matcher = app.extensions.get("lobby_demo_matcher")
            tracked = app.extensions["lobby_demo_state"].get("user_ids", set())
            user_ids = [user_id.strip()] if user_id else list(tracked)
            if not user_ids and matcher:
                user_ids = list(matcher.identity_ids())
            if not user_ids and user_id is None:
                return jsonify(
                    error="operator-action-required",
                    message="user_id is required after a process restart",
                ), 409
            removed = 0
            for demo_user_id in user_ids:
                if not _subject_allowed(demo_user_id):
                    return _scope_denied()
                try:
                    if enrollment.reset_demo(demo_user_id, actor_id=_principal_subject()):
                        removed += 1
                except TemplateLifecycleError:
                    continue
            app.extensions["lobby_demo_state"].clear()
            app.extensions["lobby_demo_state"]["last_action"] = "reset"
        return jsonify(reset=True, removed=bool(removed))

    @app.post("/api/admin/templates")
    @protected(Permission.MANAGE_ENROLLMENT, require_recent_auth=True)
    def register_template():
        body = _body()
        try:
            fields = {
                "template_id": _validated_field(body, "template_id", max_length=128, identifier=True),
                "user_id": _validated_field(body, "user_id", max_length=64, identifier=True),
                "model_version": _validated_field(body, "model_version", max_length=128),
                "template_version": _validated_field(body, "template_version", max_length=64),
                "protected_template_hash": _validated_field(body, "protected_template_hash", max_length=128),
            }
        except ValueError:
            return _invalid_request()
        if not _subject_allowed(fields["user_id"]):
            return _scope_denied()
        try:
            enrollment.register_template_metadata(**fields, actor_id=_principal_subject())
        except (ValueError, IntegrityError, sqlite3.IntegrityError):
            return _invalid_request()
        return jsonify(template_id=fields["template_id"], registered=True), 201

    @app.post("/api/admin/users/<user_id>/roles")
    @protected(Permission.MANAGE_RBAC, require_recent_auth=True)
    def assign_role(user_id: str):
        if not _is_identifier(user_id, max_length=64):
            return _invalid_request()
        if not _subject_allowed(user_id):
            return _scope_denied()
        try:
            role_name = _validated_field(_body(), "role", max_length=64)
            role = Role(role_name)
            if users.get(user_id) is None:
                return jsonify(error="not-found", message="user does not exist"), 404
            roles.assign(user_id, role.value, assigned_by=_principal_subject())
        except (ValueError, sqlite3.IntegrityError):
            return _invalid_request()
        return jsonify(user_id=user_id, role=role.value, assigned=True)

    @app.post("/api/admin/auth/revoke")
    @protected(Permission.MANAGE_RBAC, require_recent_auth=True)
    def revoke_auth_session():
        body = _body()
        token_id = body.get("token_id")
        expires_at_raw = body.get("expires_at")
        if not isinstance(token_id, str) or not 16 <= len(token_id.strip()) <= 256:
            return _invalid_request()
        if not isinstance(expires_at_raw, str):
            return _invalid_request()
        try:
            expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                raise ValueError("expires_at must include timezone")
            expires_at = expires_at.astimezone(UTC)
        except ValueError:
            return _invalid_request()
        now = datetime.now(UTC)
        if expires_at <= now or expires_at > now + timedelta(hours=1):
            return _invalid_request()
        auth_revocations.revoke(token_id.strip(), expires_at, revoked_by=_principal_subject())
        audit.append(AuditEvent(
            audit_id=hashlib.sha256(f"auth-revoke\\x1f{token_id.strip()}\\x1f{now.isoformat()}".encode()).hexdigest()[:32],
            occurred_at=now,
            actor_id=_principal_subject(),
            action="authentication:revoke",
            outcome=AuditOutcome.SUCCESS,
            resource_type="auth-session",
            resource_id=token_id.strip(),
            metadata={"expires_at": expires_at.isoformat()},
        ))
        return jsonify(revoked=True), 201

    @app.get("/api/admin/queue")
    @protected(Permission.MANAGE_QUEUE)
    def queue_status():
        return jsonify(_queue_json(queue, max_size=settings.queue_max_size))

    @app.post("/api/admin/queue/claim")
    @protected(Permission.MANAGE_QUEUE)
    def queue_claim():
        actor = _principal_subject() or "unknown-actor"
        rows = queue.claim_pending(
            now=datetime.now(UTC), limit=_limit(),
            lease_seconds=settings.queue_lease_seconds,
            lease_owner=actor,
        )
        _audit_queue(app, "queue:claim", actor, AuditOutcome.SUCCESS, len(rows))
        return jsonify(claimed=[{"queue_id": row["queue_id"], "state": QueueState.IN_FLIGHT.value} for row in rows])

    @app.post("/api/admin/queue/synchronize")
    @protected(Permission.MANAGE_QUEUE)
    def queue_sync():
        actor = _principal_subject() or "unknown-actor"
        synced = synchronizer.synchronize(
            now=datetime.now(UTC), limit=_limit(), actor_id=actor,
        )
        return jsonify(synchronized=synced, queue=_queue_json(queue, max_size=settings.queue_max_size))

    @app.post("/api/admin/queue/retry")
    @protected(Permission.MANAGE_QUEUE)
    def queue_retry():
        retried = queue.retry_failed(now=datetime.now(UTC), limit=_limit())
        _audit_queue(app, "queue:retry", _principal_subject() or "unknown-actor", AuditOutcome.SUCCESS, retried)
        return jsonify(retried=retried, queue=_queue_json(queue, max_size=settings.queue_max_size))

    @app.post("/api/admin/queue/expire")
    @protected(Permission.MANAGE_QUEUE)
    def queue_expire():
        cutoff = datetime.now(UTC) - timedelta(seconds=settings.queue_max_age_seconds)
        expired = queue.expire_before(cutoff)
        _audit_queue(app, "queue:expire", _principal_subject() or "unknown-actor", AuditOutcome.SUCCESS, expired)
        return jsonify(expired=expired, queue=_queue_json(queue, max_size=settings.queue_max_size))

    @app.get("/api/admin/audit")
    @protected(Permission.VIEW_AUDIT)
    def list_audit():
        return jsonify(audit=[_audit_json(row) for row in audit.list_events(limit=_limit())])

    return app


def _default_provider(settings: Settings, *, matcher: LocalMatcher | None = None):
    if settings.development_mock_vision and not settings.executive_demo_mode:
        return MockVisionProvider(identity_id="synthetic-user", sample_count=5)
    return OpenCVVisionProvider(
        camera_index=settings.camera_index,
        model_path=settings.vision_model_path,
        approved_model_directory=settings.vision_model_directory,
        expected_model_sha256=settings.vision_model_sha256,
        identity_resolver=matcher.resolve if matcher else None,
        match_result_resolver=matcher.resolve_result if matcher else None,
        liveness_checker=(demo_presence_liveness_checker if settings.executive_demo_mode and settings.demo_liveness_enabled else None),
    )


def _token_boundary_from_env(*, revocation_checker=None) -> TokenBoundary | SignedTokenBoundary:
    auth_mode = os.environ.get("LOBBY_ATTENDANCE_AUTH_MODE", "legacy").strip().lower()
    if auth_mode in {"signed", "pilot"}:
        signing_key = os.environ.get("LOBBY_ATTENDANCE_AUTH_SIGNING_KEY", "")
        if not signing_key:
            raise ConfigurationError("AUTH_SIGNING_KEY is required for signed authentication")
        try:
            max_ttl = int(os.environ.get("LOBBY_ATTENDANCE_AUTH_MAX_TTL_SECONDS", "900"))
            reauth_age = int(os.environ.get("LOBBY_ATTENDANCE_AUTH_REAUTH_MAX_AGE_SECONDS", "300"))
        except ValueError as exc:
            raise ConfigurationError("signed authentication lifetime settings must be integers") from exc
        trust_forwarded = os.environ.get("LOBBY_ATTENDANCE_TRUST_FORWARDED_PROTO", "false").lower() in {"1", "true", "yes", "on"}
        try:
            return SignedTokenBoundary(
                signing_key=signing_key,
                issuer=os.environ.get("LOBBY_ATTENDANCE_AUTH_ISSUER", "lobby-attendance"),
                audience=os.environ.get("LOBBY_ATTENDANCE_AUTH_AUDIENCE", "lobby-attendance-api"),
                max_ttl_seconds=max_ttl,
                reauth_max_age_seconds=reauth_age,
                revocation_checker=revocation_checker,
                trust_forwarded_proto=trust_forwarded,
            )
        except ValueError as exc:
            raise ConfigurationError(str(exc)) from exc
    if auth_mode != "legacy":
        raise ConfigurationError("LOBBY_ATTENDANCE_AUTH_MODE must be signed or legacy")
    roles = set()
    raw_roles = os.environ.get("LOBBY_ATTENDANCE_ADMIN_ROLES", "")
    for value in raw_roles.split(","):
        if value.strip():
            try:
                roles.add(Role(value.strip()))
            except ValueError:
                raise ConfigurationError("LOBBY_ATTENDANCE_ADMIN_ROLES contains an unknown role")
    admin_token = os.environ.get("LOBBY_ATTENDANCE_ADMIN_TOKEN") or None
    if admin_token and not roles:
        raise ConfigurationError("LOBBY_ATTENDANCE_ADMIN_ROLES is required when admin authentication is configured")
    return TokenBoundary(
        admin_token=admin_token,
        kiosk_token=os.environ.get("LOBBY_ATTENDANCE_KIOSK_TOKEN") or None,
        admin_subject=os.environ.get("LOBBY_ATTENDANCE_ADMIN_SUBJECT", "configured-admin")[:128],
        admin_roles=frozenset(roles),
        mock_mode=os.environ.get("LOBBY_ATTENDANCE_DEVELOPMENT_MOCK_AUTH", "false").lower() in {"1", "true", "yes", "on"},
    )


def _health(app: Flask) -> dict[str, Any]:
    settings: Settings = app.extensions["lobby_settings"]
    db: SQLiteStore = app.extensions["lobby_store"]
    queue: QueueRepository = app.extensions["lobby_queue"]
    provider = app.extensions["lobby_provider"]
    try:
        db.connection.execute("SELECT 1").fetchone()
        database = "ready"
        queue_state = "ready"
        queue_counts = _queue_json(queue, max_size=settings.queue_max_size)
    except Exception:
        database, queue_state, queue_counts = "unavailable", "unavailable", {}
    if settings.development_mock_vision and not settings.executive_demo_mode:
        camera, model = "ready", "ready"
    else:
        camera = "configured" if isinstance(provider, OpenCVVisionProvider) else "unknown"
        model = "ready" if isinstance(provider, OpenCVVisionProvider) and provider.model_digest else "unavailable"
    return {
        "status": "ready" if database == "ready" and queue_state == "ready" else "degraded",
        "camera": camera,
        "model": model,
        "database": database,
        "queue": queue_state,
        "queue_counts": queue_counts,
        "mock_mode": settings.development_mock_vision,
        "compliance_gate": "approved" if app.extensions["lobby_compliance_approved"] else "pending",
        "biometric_activation_enabled": app.extensions["lobby_compliance_approved"],
    }


def _body() -> dict[str, Any]:
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


def _invalid_request():
    return jsonify(error="invalid-request", message="request fields are invalid"), 400


def _validated_field(body: dict[str, Any], name: str, *, max_length: int, identifier: bool = False) -> str:
    value = body.get(name)
    if not isinstance(value, str):
        raise ValueError("invalid field")
    value = value.strip()
    if not value or len(value) > max_length or any(ord(char) < 32 for char in value):
        raise ValueError("invalid field")
    if identifier and not _is_identifier(value, max_length=max_length):
        raise ValueError("invalid field")
    return value


def _is_identifier(value: str, *, max_length: int) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0," + str(max_length - 1) + r"}", value))


def _principal_subject() -> str | None:
    principal = authenticated_principal()
    return principal.subject_id if principal else None


def _site_scope() -> frozenset[str] | None:
    principal = authenticated_principal()
    if principal is None or principal.authentication_method != "signed-session":
        return None
    return principal.site_ids


def _subject_scope() -> frozenset[str] | None:
    principal = authenticated_principal()
    if principal is None or principal.authentication_method != "signed-session":
        return None
    return principal.subject_ids


def _subject_allowed(user_id: str) -> bool:
    principal = authenticated_principal()
    return principal is None or principal.authentication_method != "signed-session" or principal.can_access_subject(user_id)


def _scope_denied():
    return jsonify(error="forbidden", message="resource is outside the authorized scope"), 403


def _limit() -> int:
    raw = request.args.get("limit", "100")
    if len(raw) > 6:
        return 500
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 100
    return min(max(value, 1), 500)


def _event_json(row: Any) -> dict[str, Any]:
    return {
        "event_id": row["event_id"], "user_id": row["user_id"], "site_id": row["site_id"],
        "camera_id": row["camera_id"], "occurred_at": row["occurred_at"], "source": row["source"],
        "model_version": row["model_version"], "policy_version": row["policy_version"],
        "storage_state": row["storage_state"], "correlation_id": row["correlation_id"],
    }


def _user_json(row: Any, assigned_roles: set[str]) -> dict[str, Any]:
    return {
        "user_id": row["user_id"], "display_name": row["display_name"], "status": row["status"],
        "enrolled_at": row["enrolled_at"], "deactivated_at": row["deactivated_at"],
        "roles": sorted(assigned_roles),
    }


def _queue_json(queue: QueueRepository, *, max_size: int = 10_000) -> dict[str, Any]:
    counts = {state.value: queue.count(state) for state in QueueState}
    active = sum(counts[state.value] for state in (QueueState.PENDING, QueueState.IN_FLIGHT, QueueState.FAILED))
    if counts[QueueState.FAILED.value]:
        operator_state = "synchronization-failure"
    elif active >= max_size:
        operator_state = "queue-full"
    elif counts[QueueState.EXPIRED.value]:
        operator_state = "action-required"
    else:
        operator_state = "ready"
    return {
        **counts,
        "active_count": active,
        "capacity": max_size,
        "operator_state": operator_state,
        "action_required": operator_state != "ready",
    }


def _audit_json(row: Any) -> dict[str, Any]:
    return {
        "audit_id": row["audit_id"], "occurred_at": row["occurred_at"], "actor_id": row["actor_id"],
        "action": row["action"], "outcome": row["outcome"], "resource_type": row["resource_type"],
        "resource_id": row["resource_id"], "metadata": _safe_metadata(row["metadata_json"]),
    }


def _safe_metadata(value: str) -> dict[str, str]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return {str(key): str(item) for key, item in parsed.items()} if isinstance(parsed, dict) else {}


def _audit_queue(app: Flask, action: str, actor_id: str, outcome: AuditOutcome, count: int) -> None:
    now = datetime.now(UTC)
    audit = app.extensions.get("lobby_audit")
    if audit is None:
        return
    audit.append(AuditEvent(
        audit_id=hashlib.sha256(f"{action}\x1f{actor_id}\x1f{now.isoformat()}".encode()).hexdigest()[:32],
        occurred_at=now,
        actor_id=actor_id,
        action=action,
        outcome=outcome,
        resource_type="queue",
        resource_id=None,
        metadata={"count": str(count)},
    ))
