# UI/API contract (Phase 3)

## Kiosk

The kiosk calls `POST /api/kiosk/interaction` with the kiosk bearer token and an empty JSON object. The response body contains exactly a safe `state` and user-facing `message`; it must not contain confidence values, face images, biometric templates, or unrestricted user lists. The browser camera preview is local UI only and is not uploaded by this prototype.

Supported state codes are `recognized-event-recorded`, `duplicate-suppressed`, `cooldown-suppressed`, `event-queued-locally`, `unknown`, `ambiguous`, `liveness-failed`, `low-quality`, `no-face`, `multiple-faces`, and `unavailable`. The UI maps them to neutral, success, warning, or operator-attention/error presentation and resets to neutral automatically.

The kiosk route requires the explicit environment-configured kiosk token. Missing configuration returns `503` with `configuration-error`; an invalid token returns `403`. This token boundary is a development prototype and must be replaced with approved service authentication.

## Health

`GET /health` and `GET /api/health` are unauthenticated readiness endpoints. They return `status`, `camera`, `model`, `database`, `queue`, `queue_counts`, and `mock_mode`. They do not return secrets, model paths, identities, or biometric data. Camera/model values may be `configured`, `ready`, `unavailable`, or `degraded` depending on provider configuration; the endpoint does not probe or retain camera frames.

## Admin

Admin routes use the explicit bearer admin token plus permission derived from configured roles. The UI keeps the token in JavaScript memory only. It uses DOM `textContent` for returned values rather than injecting HTML.

- `GET /api/admin/users` and `POST /api/admin/users` / `/status` support enrollment lifecycle.
- `POST /api/admin/templates` accepts only template metadata and a protected hash; raw templates are not accepted or returned.
- `POST /api/admin/users/{user_id}/roles` assigns one enumerated RBAC role.
- `GET /api/admin/events` returns approved event metadata only.
- `GET /api/admin/queue`, plus claim/synchronize/retry/expire POST routes, exposes queue state and counts without payload data.
- `GET /api/admin/audit` returns sanitized audit metadata.

Unauthorized requests fail closed. An unset admin token makes admin mutations return `503 configuration-error`; a valid token with insufficient role returns `403 forbidden`. The kiosk principal has append-only recognition permission and cannot administer, list, or export.

## API boundary invariants

`POST /api/kiosk/interaction` must be sent with an empty JSON object. `occurred_at` is rejected with `400 invalid-request`; the server captures the event time. Direct pipeline callers may provide an explicit time for deterministic tests, but the HTTP route does not accept client-selected event times.

Admin tokens are authorized only by the explicitly configured `LOBBY_ATTENDANCE_ADMIN_ROLES` set. A real admin token without that setting fails closed during configuration; database role-assignment rows are enrollment metadata until an identity-provider adapter is integrated. Mutation audit records use the authenticated prototype subject, and denied requests record only bounded method/route/permission metadata.

Request bodies are limited to 64 KiB. User, display-name, role, and template metadata fields are bounded and invalid input returns the stable response `{"error":"invalid-request","message":"request fields are invalid"}`. Local responses include clickjacking and content-type protections (`X-Frame-Options: DENY`, CSP with `frame-ancestors 'none'`, and `X-Content-Type-Options: nosniff`).

## Queue recovery and retention operations

Queue claim responses expose state only; they do not expose payloads. A claim receives a configurable lease (`QUEUE_LEASE_SECONDS`, default 300 seconds). `POST /api/admin/queue/synchronize` reclaims expired `in-flight` claims before retrying failed items or claiming pending items. A process crash therefore returns an expired claim to `pending`; items older than `QUEUE_MAX_AGE_SECONDS` are marked `expired`, including stale in-flight items. The current `InMemoryEventSink` is test/prototype-only and is not an authenticated durable remote synchronization implementation.

Retention is intentionally not exposed as a general browser deletion route. The operations layer calls the audited `RetentionService.purge_expired(now, retention_days, actor_id)` and `cleanup_de_enrollment(user_id, actor_id, now)`. These explicit operations remove local recognition events, suppression records, local queue payloads, and retired template metadata according to the selected scope. They preserve audit evidence and temporarily bypass the append-only event delete trigger only inside the named purge transaction; ordinary event update/delete statements continue to fail. Backup, WAL, replica, and remote-sink deletion propagation must be implemented and verified by deployment owners.

## Model asset integrity

When OpenCV is enabled, the configured model must be a regular non-symlink file. `VISION_MODEL_DIRECTORY`, when configured, restricts the resolved asset to the approved directory tree. `VISION_MODEL_SHA256`, when configured, must match the locally computed SHA-256 before OpenCV loads the asset. Missing, modified, symlinked, non-file, or out-of-directory assets return the neutral `unavailable` state. A verified asset is identified in event metadata by `sha256:<digest>` rather than the generic `configured` label. Models are never downloaded at runtime; provenance, license, digest, and approved deployment source remain release-gate evidence.

## Executive demo UI

When `LOBBY_ATTENDANCE_EXECUTIVE_DEMO_MODE=true`, the admin page shows an **Executive demo enrollment** panel. It prominently states that the flow is demo-only, uses a heuristic matcher/liveness check, is not production biometric readiness, requires a consenting authorized participant, and loses enrollment on server restart.

The panel calls `GET /api/admin/demo/status`, `POST /api/admin/demo/enrollment`, and `POST /api/admin/demo/reset`. It uses the existing in-memory admin token and never uses `localStorage`, `sessionStorage`, browser `getUserMedia`, or frame uploads. Enrollment is a single-flight bounded action against the server-attached webcam. Reset requires an explicit confirmation checkbox.

The UI displays only safe readiness values: enabled/disabled, ready/unavailable/disabled state, compliance gate, liveness enabled/disabled, and in-memory template count. It never displays hashes, face crops, matcher scores, thresholds, raw exceptions, or liveness internals. Network/auth/model/camera/storage errors map to generic operator-safe messages.

The legacy metadata-only form is hidden in executive demo mode and remains available only under a collapsed label identifying it as a non-demo metadata contract. It must not be used to claim real face enrollment or recognition.

The kiosk still calls `POST /api/kiosk/interaction` and returns only neutral state/message output. Its browser preview is not the server recognition input; the executive demo must use the same webcam attached to the Flask process for both enrollment and recognition.

## P0-01 operator and participant-control boundary

The kiosk must not imply that a generic “operator help” message is an implemented non-biometric alternative. Until an approved fallback is selected and implemented, camera/model/liveness/compliance failures remain safe rejection or operator-escalation states only; no fallback event is created.

The UI must preserve these operational distinctions: `event-queued-locally` means the local store accepted a bounded payload while remote synchronization is unavailable and requires operator monitoring; `unavailable` means local storage, encryption/integrity, queue capacity, camera, model, or another required local dependency failed and recognition was fail-closed. The UI must never claim remote acknowledgement, deletion completion, participant consent, lawful basis, or legal approval from these states.

The participant-rights workflow is not implemented by this prototype. Before pilot release, an approved workflow must define notice delivery, acknowledgement/withdrawal or lawful-basis records, access/correction/deletion/objection intake, identity verification, escalation, legal holds, copy-by-copy deletion verification, and accessible participant messaging. The API/UI contract must be extended only after the privacy/legal and product decisions are recorded.

Stop/resume controls are operator/governance requirements, not a browser-only toggle. The UI may surface operator attention, but only the named stop authority may resume recognition after a documented trigger, containment, corrective verification, and dated approval.
