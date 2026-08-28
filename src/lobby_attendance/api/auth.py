"""Authentication boundaries for prototype and signed pilot sessions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from threading import Lock
from typing import Callable, Mapping

from flask import current_app, g, jsonify, request

from ..audit import AuditEvent
from ..domain import AuditOutcome
from ..errors import AuthorizationError
from ..rbac import Permission, Principal, Role, require_permission, roles_obey_separation

UTC = timezone.utc
MAX_SUBJECT_LENGTH = 128
MAX_SCOPE_ITEMS = 256


class AuthAttemptLimiter:
    """Bound failed authentication attempts per process and request origin."""

    def __init__(self, *, max_failures: int = 10, window_seconds: int = 60, max_keys: int = 1024) -> None:
        if max_failures <= 0 or window_seconds <= 0 or max_keys <= 0:
            raise ValueError("authentication limiter bounds must be positive")
        self.max_failures = max_failures
        self.window_seconds = float(window_seconds)
        self.max_keys = max_keys
        self._failures: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            failures = self._prune(key, now)
            return len(failures) < self.max_failures

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            if key not in self._failures and len(self._failures) >= self.max_keys:
                oldest = min(self._failures, key=lambda item: self._failures[item][-1] if self._failures[item] else now)
                self._failures.pop(oldest, None)
            failures = self._prune(key, now)
            failures.append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def _prune(self, key: str, now: float) -> deque[float]:
        failures = self._failures.setdefault(key, deque())
        cutoff = now - self.window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()
        return failures


@dataclass(frozen=True, slots=True)
class TokenBoundary:
    """Legacy static-token boundary retained only for tests and the demo."""

    admin_token: str | None = None
    kiosk_token: str | None = None
    admin_subject: str = "configured-admin"
    admin_roles: frozenset[Role] = frozenset()
    mock_mode: bool = False

    @property
    def admin_configured(self) -> bool:
        return bool(self.admin_token)

    @property
    def kiosk_configured(self) -> bool:
        return bool(self.kiosk_token)

    @property
    def requires_tls(self) -> bool:
        return False

    @property
    def enforces_recent_auth(self) -> bool:
        return False

    @property
    def signed_sessions(self) -> bool:
        return False

    def configured_for(self, token_kind: str) -> bool:
        return self.admin_configured if token_kind == "admin" else self.kiosk_configured

    def tls_is_valid(self) -> bool:
        return True

    def has_recent_auth(self, principal: Principal) -> bool:
        return True

    def principal_for_request(self) -> Principal | None:
        supplied = _supplied_token()
        if not supplied:
            return None
        if self.kiosk_token and hmac.compare_digest(supplied, self.kiosk_token):
            return Principal.with_roles("kiosk-service", {Role.KIOSK_SERVICE}, token_kind="kiosk")
        if self.admin_token and hmac.compare_digest(supplied, self.admin_token):
            return Principal.with_roles(self.admin_subject, self.admin_roles, token_kind="admin")
        if self.mock_mode and hmac.compare_digest(supplied, "development-mock-token"):
            return Principal.with_roles(
                "development-mock", self.admin_roles | {Role.KIOSK_SERVICE}, token_kind="admin",
            )
        return None


@dataclass(frozen=True, slots=True)
class SignedTokenBoundary:
    """Validate short-lived signed sessions issued by an approved identity adapter.

    The repository intentionally does not implement an identity provider. An
    approved IdP or identity gateway must issue these claims using the agreed
    signing key, issuer, audience, roles, and scopes. Static shared tokens are
    not accepted by this boundary.
    """

    signing_key: bytes | str
    issuer: str
    audience: str
    max_ttl_seconds: int = 900
    reauth_max_age_seconds: int = 300
    revocation_checker: Callable[[str], bool] | None = None
    trust_forwarded_proto: bool = False

    def __post_init__(self) -> None:
        key = self.signing_key.encode("utf-8") if isinstance(self.signing_key, str) else bytes(self.signing_key)
        if len(key) < 32:
            raise ValueError("signed-session key must contain at least 32 bytes")
        if not self.issuer.strip() or not self.audience.strip():
            raise ValueError("signed-session issuer and audience are required")
        if not 60 <= self.max_ttl_seconds <= 3600:
            raise ValueError("signed-session lifetime must be between 60 and 3600 seconds")
        if not 30 <= self.reauth_max_age_seconds <= self.max_ttl_seconds:
            raise ValueError("reauthentication age is outside the session lifetime")
        object.__setattr__(self, "signing_key", key)

    @property
    def admin_configured(self) -> bool:
        return True

    @property
    def kiosk_configured(self) -> bool:
        return True

    @property
    def requires_tls(self) -> bool:
        return True

    @property
    def enforces_recent_auth(self) -> bool:
        return True

    @property
    def signed_sessions(self) -> bool:
        return True

    def configured_for(self, token_kind: str) -> bool:
        return token_kind in {"admin", "kiosk"}

    def tls_is_valid(self) -> bool:
        if request.is_secure:
            return True
        if self.trust_forwarded_proto:
            return request.headers.get("X-Forwarded-Proto", "").lower() == "https"
        return False

    def has_recent_auth(self, principal: Principal) -> bool:
        if principal.auth_time is None:
            return False
        now = datetime.now(UTC)
        age = (now - principal.auth_time).total_seconds()
        return -30 <= age <= self.re_auth_age_seconds

    @property
    def re_auth_age_seconds(self) -> int:
        return self.reauth_max_age_seconds

    def principal_for_request(self) -> Principal | None:
        raw = request.headers.get("Authorization", "")
        if not raw.lower().startswith("bearer "):
            return None
        token = raw[7:].strip()
        if not token:
            return None
        try:
            payload = _decode_signed_token(token, self.signing_key)
            now = int(datetime.now(UTC).timestamp())
            if payload.get("iss") != self.issuer or payload.get("aud") != self.audience:
                return None
            issued_at = _int_claim(payload, "iat")
            expires_at = _int_claim(payload, "exp")
            if issued_at > now + 30 or expires_at <= now or expires_at <= issued_at:
                return None
            if expires_at - issued_at > self.max_ttl_seconds:
                return None
            subject = payload.get("sub")
            token_id = payload.get("jti")
            token_kind = payload.get("kind")
            if not isinstance(subject, str) or not 1 <= len(subject) <= MAX_SUBJECT_LENGTH:
                return None
            if not isinstance(token_id, str) or not 16 <= len(token_id) <= 256:
                return None
            if token_kind not in {"admin", "kiosk"}:
                return None
            if self.revocation_checker and self.revocation_checker(token_id):
                return None
            raw_roles = payload.get("roles")
            if not isinstance(raw_roles, list) or len(raw_roles) > MAX_SCOPE_ITEMS:
                return None
            try:
                roles = frozenset(Role(value) for value in raw_roles)
            except (TypeError, ValueError):
                return None
            if token_kind == "kiosk" and roles != frozenset({Role.KIOSK_SERVICE}):
                return None
            if token_kind == "admin" and not roles:
                return None
            if not roles_obey_separation(roles):
                return None
            auth_time = datetime.fromtimestamp(_int_claim(payload, "auth_time"), UTC)
            sites = _bounded_scope(payload.get("sites"))
            subjects = _bounded_scope(payload.get("subjects"))
            if not sites or (token_kind == "admin" and not subjects):
                return None
            return Principal.with_roles(
                subject,
                roles,
                site_ids=sites,
                subject_ids=subjects,
                auth_time=auth_time,
                token_id=token_id,
                token_kind=token_kind,
                authentication_method="signed-session",
            )
        except (TypeError, ValueError, KeyError, OverflowError, json.JSONDecodeError):
            return None


def issue_signed_token(
    signing_key: bytes | str,
    *,
    subject: str,
    roles: tuple[Role, ...] | list[Role] | frozenset[Role],
    issuer: str,
    audience: str,
    token_kind: str = "admin",
    ttl_seconds: int = 900,
    now: datetime | None = None,
    auth_time: datetime | None = None,
    sites: tuple[str, ...] | list[str] = (),
    subjects: tuple[str, ...] | list[str] = (),
    token_id: str | None = None,
) -> str:
    """Create a compact signed session for tests or an approved local adapter."""
    if token_kind not in {"admin", "kiosk"} or not subject.strip():
        raise ValueError("invalid signed-session subject or kind")
    if ttl_seconds <= 0:
        raise ValueError("signed-session lifetime must be positive")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    authentication = (auth_time or current).astimezone(UTC)
    payload = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "roles": [role.value for role in roles],
        "kind": token_kind,
        "iat": int(current.timestamp()),
        "exp": int((current + timedelta(seconds=ttl_seconds)).timestamp()),
        "auth_time": int(authentication.timestamp()),
        "jti": token_id or secrets.token_urlsafe(24),
        "sites": list(sites),
        "subjects": list(subjects),
    }
    key = signing_key.encode("utf-8") if isinstance(signing_key, str) else bytes(signing_key)
    if len(key) < 32:
        raise ValueError("signed-session key must contain at least 32 bytes")
    header = {"alg": "HS256", "typ": "LAS1"}
    encoded_header = _b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
    encoded_payload = _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = hmac.new(key, signing_input, hashlib.sha256).digest()
    return f"la1.{encoded_header}.{encoded_payload}.{_b64url(signature)}"


def protected(
    permission: Permission,
    *,
    token_kind: str = "admin",
    require_recent_auth: bool = False,
) -> Callable:
    """Protect a route and keep unauthorized details out of response bodies."""
    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapped(*args, **kwargs):
            boundary = current_app.extensions["lobby_token_boundary"]
            if not boundary.configured_for(token_kind):
                _record_denied(permission, None)
                return jsonify(error="configuration-error", message="authentication is not configured"), 503
            if boundary.requires_tls and not boundary.tls_is_valid():
                return jsonify(error="tls-required", message="secure transport is required"), 426
            limiter: AuthAttemptLimiter | None = current_app.extensions.get("lobby_auth_limiter")
            attempt_key = f"{request.remote_addr or 'unknown'}:{token_kind}"
            if limiter and not limiter.allow(attempt_key):
                _record_denied(permission, None)
                return jsonify(error="rate-limited", message="too many authentication failures"), 429
            principal = boundary.principal_for_request()
            if principal is None or principal.token_kind != token_kind:
                if limiter:
                    limiter.record_failure(attempt_key)
                _record_denied(permission, principal)
                return jsonify(error="forbidden", message="permission denied"), 403
            if boundary.signed_sessions and not principal.can_access_site(current_app.extensions["lobby_settings"].site_id):
                _record_denied(permission, principal)
                return jsonify(error="forbidden", message="permission denied"), 403
            if limiter:
                limiter.clear(attempt_key)
            if require_recent_auth and boundary.enforces_recent_auth and not boundary.has_recent_auth(principal):
                return jsonify(error="reauthentication-required", message="recent administrator authentication is required"), 401
            try:
                require_permission(principal, permission)
            except AuthorizationError:
                _record_denied(permission, principal)
                return jsonify(error="forbidden", message="permission denied"), 403
            g.lobby_principal = principal
            return view(*args, **kwargs)
        return wrapped
    return decorator


def authenticated_principal() -> Principal | None:
    """Return the principal established by ``protected`` for the current request."""
    return getattr(g, "lobby_principal", None)


def _record_denied(permission: Permission, principal: Principal | None) -> None:
    """Append bounded authorization telemetry without request data or credentials."""
    audit = current_app.extensions.get("lobby_audit")
    if audit is None:
        return
    occurred_at = datetime.now(UTC)
    endpoint = (request.endpoint or "unknown")[:128]
    audit_id = hashlib.sha256(
        f"authz-denied\x1f{request.method}\x1f{endpoint}\x1f{permission.value}\x1f{occurred_at.isoformat()}".encode()
    ).hexdigest()[:32]
    try:
        audit.append(AuditEvent(
            audit_id=audit_id,
            occurred_at=occurred_at,
            actor_id=principal.subject_id if principal else None,
            action="authorization:denied",
            outcome=AuditOutcome.DENIED,
            resource_type="http-route",
            resource_id=endpoint,
            metadata={"method": request.method, "permission": permission.value},
        ))
    except Exception:
        current_app.logger.warning("authorization denial audit append failed")


def _supplied_token() -> str | None:
    value = request.headers.get("Authorization", "")
    if value.lower().startswith("bearer "):
        return value[7:].strip() or None
    return request.headers.get("X-Lobby-Token") or None


def _decode_signed_token(token: str, key: bytes) -> dict[str, object]:
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != "la1":
        raise ValueError("invalid signed-session format")
    signing_input = f"{parts[1]}.{parts[2]}".encode("ascii")
    expected = hmac.new(key, signing_input, hashlib.sha256).digest()
    supplied = _b64url_decode(parts[3])
    if not hmac.compare_digest(expected, supplied):
        raise ValueError("invalid signed-session signature")
    header = json.loads(_b64url_decode(parts[1]))
    if header != {"alg": "HS256", "typ": "LAS1"}:
        raise ValueError("invalid signed-session header")
    payload = json.loads(_b64url_decode(parts[2]))
    if not isinstance(payload, dict):
        raise ValueError("invalid signed-session payload")
    return payload


def _int_claim(payload: Mapping[str, object], name: str) -> int:
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _bounded_scope(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_SCOPE_ITEMS:
        raise ValueError("scope is invalid")
    if not all(isinstance(item, str) and 1 <= len(item) <= 128 for item in value):
        raise ValueError("scope is invalid")
    return tuple(value)


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    if not isinstance(value, str) or len(value) > 16_384:
        raise ValueError("encoded token part is invalid")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
