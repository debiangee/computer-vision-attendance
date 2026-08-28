# Pilot Authentication and Session Design

## Status

**Local engineering controls:** implemented and covered by `tests/test_pilot_auth.py`.

**Pilot identity-provider deployment:** pending. The repository provides a signed-session validation seam; it does not implement or approve an organizational SSO/OIDC provider.

**Pilot gate:** remains open until Security/Platform approve the issuer, audience, key custody, TLS termination, session issuance, and administrator re-authentication process.

## Authentication modes

### Legacy mode

`TokenBoundary` remains available for existing tests and the supervised local executive demo. It accepts configured static values and is not pilot-safe.

Legacy mode does not provide expiry, revocation, individual attribution, recent-auth enforcement, or TLS enforcement. It must not be used for participant enrollment or workplace pilot operation.

### Signed-session mode

Set `LOBBY_ATTENDANCE_AUTH_MODE=signed` or `pilot` to require signed sessions. In this mode:

- Static admin and kiosk tokens are not accepted.
- Requests must use `Authorization: Bearer <signed-session>`.
- Tokens use the repository's `la1` envelope and HMAC-SHA-256 signature.
- Claims include issuer, audience, subject, roles, token kind, issued-at, expiry, authentication time, token ID, site scope, and subject scope.
- The maximum session lifetime is configurable and defaults to 900 seconds.
- The recent-auth window defaults to 300 seconds.
- Revoked token IDs are persisted in SQLite until expiry.
- Sensitive operations require recent authentication.
- TLS is required unless the trusted reverse-proxy boundary explicitly supplies `X-Forwarded-Proto: https`.

The signing key must be at least 32 bytes and must be supplied through an approved secret/key-management boundary. It must not be committed, logged, displayed in the UI, or stored in a database row.

## Required environment configuration

```text
LOBBY_ATTENDANCE_AUTH_MODE=signed
LOBBY_ATTENDANCE_AUTH_SIGNING_KEY=<approved-secret-or-key-reference>
LOBBY_ATTENDANCE_AUTH_ISSUER=<approved-issuer>
LOBBY_ATTENDANCE_AUTH_AUDIENCE=lobby-attendance-api
LOBBY_ATTENDANCE_AUTH_MAX_TTL_SECONDS=900
LOBBY_ATTENDANCE_AUTH_REAUTH_MAX_AGE_SECONDS=300
LOBBY_ATTENDANCE_TRUST_FORWARDED_PROTO=false
```

A production or pilot deployment must obtain tokens from an approved IdP or identity gateway. The local `issue_signed_token()` helper exists for tests and approved local adapters only; it is not a replacement for organizational identity issuance.

## Sensitive operations requiring recent authentication

The API requires a signed token whose `auth_time` is within the configured recent-auth window for:

- user creation;
- enrollment activation/status changes;
- server-camera demo enrollment and reset;
- template metadata registration;
- attendance corrections;
- event export;
- role assignment;
- authentication-session revocation.

Expired, malformed, incorrectly signed, incorrectly scoped, revoked, wrong-audience, wrong-issuer, wrong-kind, and non-TLS requests are rejected without revealing token details.

## Revocation

`POST /api/admin/auth/revoke` requires the RBAC-management permission and recent authentication. It accepts a bounded token ID and an expiry timestamp. Revocations are stored in `auth_token_revocations`, audited, and automatically ignored after the token expiry time.

The pilot deployment must additionally define:

- IdP-side session revocation and account disablement;
- signing-key rotation and emergency revocation;
- compromised-token response;
- administrator account offboarding;
- clock synchronization and maximum clock skew;
- audit review and alerting for repeated authorization failures.

## TLS boundary

The application rejects signed-session requests unless Flask sees a secure request or a trusted reverse proxy is explicitly configured to pass `X-Forwarded-Proto: https`. `TRUST_FORWARDED_PROTO` must remain false unless the proxy network and header-stripping behavior are reviewed.

The development Flask server must not be exposed directly to an untrusted network. Pilot deployment must terminate TLS at an approved reverse proxy or service boundary, enforce certificate validation for synchronization, and document the trusted-hop topology.

## Security tests

The local regression suite covers:

- secure-transport enforcement;
- signed-session expiry;
- recent-auth rejection;
- signed admin/kiosk token-kind separation;
- durable revocation and audit;
- bounded authentication-failure rate limiting;
- legacy static-token compatibility for demo/tests only.

The process-local limiter is a defense-in-depth control. Pilot deployments must also enforce rate limits and account/session abuse detection at the approved identity gateway or reverse proxy.

These tests prove the local validation boundary, not the identity-provider, key-custody, TLS certificate, or reverse-proxy deployment.

## Decision

**P0-02 engineering controls:** prepared.

**P0-02 pilot gate:** OPEN until an approved IdP/identity gateway, secret/key custody, TLS deployment, session issuance, re-authentication policy, and operational revocation process are deployed and reviewed.
