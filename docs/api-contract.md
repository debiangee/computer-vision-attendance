# Lobby Attendance API Contract

This prototype contract documents the remediation endpoints. All timestamps persisted by the service are UTC ISO-8601 values. Protected admin routes use the authenticated principal established by the configured token boundary; permission checks are server-side and default deny.

## Compliance and health

`GET /api/health` returns readiness fields without secrets:

```json
{
  "status": "ready",
  "database": "ready",
  "queue": "ready",
  "queue_counts": {},
  "compliance_gate": "pending",
  "biometric_activation_enabled": false
}
```

`POST /api/admin/users/{user_id}/status` with `{"status":"active"}` returns `200` only when `LOBBY_ATTENDANCE_COMPLIANCE_APPROVED=true` (or the explicit test-only mock approval is enabled under `testing=True`). Otherwise it returns `409` with `{"error":"compliance-not-approved","message":"biometric activation is not approved"}`, leaves the user suspended, and appends a denied audit record.

## Corrections

`POST /api/admin/events/{event_id}/corrections` requires `attendance-events:correct` (attendance administrator). Request:

```json
{"reason":"operator verified timestamp","changes":{"occurred_at":"2026-08-27T01:02:03Z"}}
```

`reason` is required and bounded to 500 characters. `changes` is a bounded object containing only `user_id`, `site_id`, `camera_id`, or timezone-qualified `occurred_at`; unknown fields, invalid values, and missing users return `400` with the stable invalid-request response. Missing events return `404`. Success returns `201` with a correction containing `before`, `after`, actor, reason, and timestamp. The original recognition row is append-only and is never updated or deleted. The correction row and audit event preserve the history.

## Export

`GET /api/admin/events/export?limit=100` requires `attendance-events:export` (attendance administrator). It returns bounded JSON event rows containing identifiers, site/camera, event time, source, model/policy version, storage state, and correlation ID. Raw metadata, audit metadata, biometric templates, credentials, frames, and secrets are excluded. Every successful export is audited with the authenticated actor and row count. Unauthorized callers receive the standard `403` response.

## Queue operations

Queue operator routes require `queue:manage`. `GET /api/admin/queue` and queue mutation responses include counts, capacity, `active_count`, `operator_state`, and `action_required`; no queue payload or exception is returned. `operator_state` is one of:

- `ready`: no local operator condition is currently reported;
- `queue-full`: pending/in-flight/failed items meet the configured capacity;
- `synchronization-failure`: one or more items are failed after a sink error;
- `action-required`: expired items require operator attention.

Claim, synchronize, retry, expire, reclaim, success, and failure transitions produce bounded queue audit events attributed to the authenticated operator where an HTTP operator initiated the action. Synchronization remains local/prototype-only; an authenticated durable remote sink is not implemented by this remediation.

## Compatibility and limitations

Recognition event rows gained nullable/defaulted migration fields `storage_state`, `correlation_id`, and `audit_metadata_json`; existing rows remain readable with `recorded` and empty metadata defaults. These fields and queue/audit transitions do not change the recognized-person encounter boundary. Production authentication/RBAC separation, encryption at rest, TLS, durable remote synchronization, backup deletion propagation, and Raspberry Pi/model evaluation remain unresolved release gates.

## Executive demo enrollment contract

Executive demo routes are enabled only when `LOBBY_ATTENDANCE_EXECUTIVE_DEMO_MODE=true` and require the enrollment-management permission. They use the server-attached webcam; the browser does not send frames.

`GET /api/admin/demo/status` returns only safe readiness fields:

```json
{
  "enabled": true,
  "state": "ready",
  "compliance_gate": "approved",
  "liveness": "enabled",
  "templates": 1
}
```

`state` is `ready`, `unavailable`, or `disabled`. `templates` is the count of enabled in-memory demo templates, not a persistent template count. The endpoint never returns a frame, crop, template, hash, score, threshold, or liveness detail.

`POST /api/admin/demo/enrollment` accepts only bounded fields:

```json
{"user_id":"executive-demo-1","display_name":"Consenting Demo Participant"}
```

The server captures a bounded sample set, validates one face, quality, the enabled demonstration liveness/presence heuristic, and the local matcher, then creates an active user and server-derived template metadata. Success returns `201` with only `user_id`, `status`, and `matcher_version`. Camera/model/liveness/matcher/storage failures return a safe unavailable response; the user does not become matchable. Compliance approval is required. Existing metadata-only registration cannot activate a demo identity.

`POST /api/admin/demo/reset` requires `{"confirm":true}` and may include one bounded `user_id`. It revokes the selected demo lifecycle: the in-memory template is removed, the user is suspended, active demo metadata is retired, and an audit event is appended. Recognition event history is preserved. The response returns only `reset` and `removed`. Reset does not claim deletion from SQLite WAL files, backups, replicas, exports, or remote copies. Restarting the process removes all in-memory demo templates.

The demo matcher is a normalized grayscale crop heuristic and the liveness callback is a presence heuristic. They are not production recognition, identity proof, or presentation-attack detection. No raw frames, crops, arrays, scores, or liveness internals are persisted or returned. Production privacy/legal, authentication/RBAC, encryption, durable synchronization, deletion, model, and target-device gates remain open.

## P0-01 compliance and degraded-operation boundary

Recognition submission is fail-closed at the service boundary, not only at enrollment. When the effective technical compliance gate is false, `RecognitionEventService.submit()` returns `rejected` with reason `compliance-not-approved`; it does not append an event or enqueue one, and it records only a bounded `recognition:blocked` denial when audit storage is available. The default constructor value is deny. `LOBBY_ATTENDANCE_COMPLIANCE_APPROVED` is a technical/demo gate and must not be presented as privacy/legal approval.

Outage semantics are distinct:

- A remote database/synchronization outage with healthy local storage may return `event-queued-locally` after bounded local persistence. This does not claim remote acknowledgement, durable production synchronization, encryption, or deletion propagation.
- A local database, filesystem, queue, encryption/integrity, or capacity failure returns an operator-safe unavailable/rejected result and does not create or queue a recognition event.
- Camera, model, liveness, or compliance-gate failure is fail-closed and is not a non-biometric fallback. No participant-rights or fallback API is claimed until the relevant privacy/product decision is approved and implemented.

The P0-01 privacy package defines the required participant-rights, fallback, data-copy, retention/legal-hold, and stop/resume contract. No API in this prototype currently persists notice/consent/lawful-basis acknowledgement, withdrawal, access, deletion, or fallback-choice records; those remain explicit implementation gates rather than implied behavior.
