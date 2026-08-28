# Lobby Computer-Vision Attendance Design

**Status:** Baseline revision for automatic recognized-person encounter logging on Raspberry Pi 4 and a simple webcam. Technology selection remains deferred until the hardware/runtime spike.

## 1. Design goals

- Log one safe, recognized-person encounter rather than one row per frame or an arbitrary face sighting.
- Keep camera/model observations separate from deterministic cooldown and event policy.
- Prefer local/on-device processing, ephemeral frames, and a durable encrypted local queue.
- Make uncertain identity, failed liveness, and dependency failure safe rejections.
- Keep biometric recognition replaceable and event records auditable.
- Test stable matching, cooldown, synchronization, and policy independently from the live camera/model.

## 2. Proposed component boundaries

```text
              +---------------------------+
              | Neutral Kiosk UI          |
              | camera status / event      |
              | result / operator state    |
              +-------------+-------------+
                            |
                            v
              +---------------------------+
              | Local Attendance Service   |
              | capture + orchestration    |
              +--+----------+----------+---+
                 |          |          |
                 v          v          v
          +----------+ +--------+ +----------+
          | Capture  | | Stable | | RBAC /   |
          | adapter  | | match  | | admin    |
          +----+-----+ | +      | +----+-----+
               |       | policy |      |
               v       +---+----+      v
          +----------+     |       +----------+
          | Detect / |     v       | Admin /  |
          | recognize| +--------+  | audit    |
          | + liveness| | Event  |  +----------+
          +----------+ | writer |
                       +---+----+
                           |
              +------------+-------------+
              |                          |
              v                          v
       +-------------+            +-------------+
       | Remote DB / |            | Encrypted   |
       | API         |<--sync---->| local queue |
       +-------------+            +-------------+
```

The MVP may be one local application with a remote database or a local service plus protected API. Interfaces must remain stable either way.

### 2.1 Capture adapter
Owns webcam permission, device selection, resolution, frame sampling, timeout, and disposal. It returns short-lived frames or capture errors and never stores images or creates events.

### 2.2 Recognition and liveness adapter
Owns detection, quality, feature extraction/matching, model version, threshold, and liveness. It returns observations such as:

```text
RecognitionObservation {
  interaction_id
  camera_id
  face_count
  candidate_user_id | null
  match_state: accepted | unknown | ambiguous | rejected
  liveness_state: passed | failed | unavailable
  quality_state
  frame_index
  model_version
  observed_at
  expires_at
}
```

It must not write events, expose templates to the UI, or treat a single frame as a decision.

### 2.3 Stable-match aggregator
Collects short-lived observations during one bounded interaction. It accepts a candidate only when the configured identity is stable—proposed starting point: the same identity in at least 3 of 5 sampled frames over about 1 second—and liveness/quality gates pass. It discards temporary frames and rejected observations.

### 2.4 Encounter policy engine
A deterministic, testable module that receives a stable recognition observation, camera/site context, current policy configuration, current time, and recent event state. It returns:

```text
EncounterDecision {
  decision: eligible | cooldown_suppressed | rejected | queue_required
  reason_code
  normalized_event
  idempotency_key
  policy_version
}
```

It owns per-person/per-camera cooldown, idempotency, timezone conversion, event metadata, and safe rejection. It does not infer Time In/Time Out, sessions, shifts, holidays, or payroll meaning.

### 2.5 Event writer and local queue
Writes an eligible event transactionally to the configured database when available. If the database is unavailable, it writes the minimum encrypted event payload to a bounded append-only local queue. Synchronization uses authenticated, idempotent requests and records each outcome.

The queue must never contain raw frames, full templates, or unnecessary profile data. Queue age, capacity, checksum/integrity, and synchronization status are observable to operators.

### 2.6 Administration and RBAC service
Provides protected enrollment, authorization verification, suspension/deletion, template rotation, role assignment, policy configuration, event correction, reports, exports, queue operations, retention jobs, and audit review. The neutral kiosk surface cannot browse people, templates, reports, or audit data.

### 2.7 Audit and operations
Captures role changes, enrollment lifecycle, compliance-state changes, model/configuration versions, recognition outcomes needed for operations, event creation/suppression, queue synchronization, corrections, exports, deletion, and failures. It redacts frames, templates, secrets, and raw confidence values.

## 3. Automatic recognition-event flow

1. Kiosk stays in a neutral camera state; no Time In/Time Out action is shown.
2. Capture adapter samples a bounded webcam interaction.
3. Detection identifies no face, multiple faces, or candidate face observations.
4. Recognition/liveness adapter evaluates sampled observations.
5. Stable-match aggregator requires the configured repeated-identity window and liveness/quality gates.
6. If no safe identity is established, no event is created and the kiosk returns to a neutral/error state.
7. Encounter policy checks the active user, camera/site, five-minute proposed cooldown, event version, and idempotency key.
8. If eligible, event writer persists immediately to the database or to the encrypted local queue.
9. Kiosk shows a minimal result such as recorded, already recorded, queued, or operator attention required.
10. Frames and temporary recognition artifacts are discarded; no continuous video is retained.
11. When connectivity returns, the sync worker sends queued events with retry-safe idempotency and updates queue/audit status.

## 4. Administrative flows

### Enrollment
Authenticate with the RBAC administrator/enrollment role → verify authorized population and site scope → apply the approved compliance gate → capture controlled enrollment samples → quality/liveness checks → create versioned protected template → verify test match → activate only after approval → audit each step.

If the current no-notice/no-consent/no-alternative position is not approved for the deployment, activation must remain blocked until the required notice, consent/lawful basis, or alternative is implemented.

### De-enrollment/deletion
Authenticate → verify role, scope, retention/legal-hold rule → deactivate matching immediately → delete or de-identify template/profile/queue copies as policy permits → propagate to database, backups, replicas, and exports → record outcome and exceptions.

### Correction/export/audit
Authenticate the appropriate Attendance Administrator, Auditor, or RBAC Administrator role → enforce site/data scope → require reason and approval when applicable → preserve original event/history → audit before/after representation and actor. Raw templates are never included in ordinary exports.

## 5. Data model baseline

- **Person:** internal ID, minimum profile, authorization state, site scope, compliance-state reference, lifecycle timestamps.
- **BiometricTemplate:** internal ID, person ID, protected template/reference, model/version metadata, enrollment quality metadata, created/rotated/deleted timestamps. Never expose in kiosk APIs or logs.
- **RecognitionEvent:** event ID, person ID, type `RECOGNIZED_ENCOUNTER`, UTC observed/created timestamps, site/camera, source, policy/model versions, idempotency key, storage state, sync metadata.
- **EventSuppression:** person/camera, suppression reason, cooldown reference, observed time, minimal audit/metric data; do not create an event row for every frame.
- **LocalQueueItem:** queue ID, event payload reference/minimal encrypted payload, created/expiry time, checksum, retry count, sync state, last error code, and audit correlation.
- **AttendanceCorrection:** correction ID, original event ID, before/after representation, reason, actor, approval if required, timestamp.
- **AuditEvent:** event ID, actor/service, action, target type/ID, outcome, timestamp, correlation ID, redacted metadata.
- **PolicyConfig:** camera/site scope, cooldown, stable-frame window, thresholds/model references, retention, queue limits, version, effective time, approver.
- **RBACAssignment:** principal, role, site/data scope, grant/revoke timestamps, actor, and audit reference.

Separate access paths and encryption keys for templates, event data, and queue data where the deployment allows it.

## 6. Security, privacy, and Raspberry Pi boundaries

- The kiosk service may recognize and append events only; it cannot administer users, export data, or change policy.
- Enrollment, deletion, export, role changes, policy changes, queue purge, and corrections require protected administrator access and re-authentication where appropriate.
- Run local processing on the Raspberry Pi 4, disable unused services, restrict remote administration, physically secure the device, and use watchdog/health monitoring.
- Store only the minimum event payload in the local queue; never queue raw frames or full templates.
- Network, database, and storage failure must not cause a guessed identity or silent loss. If the queue is full or integrity fails, fail closed and alert an operator.
- Model and policy versions are included in internal audit context without retaining images.

## 7. Error handling

| Failure | Kiosk/operator behavior | System behavior |
|---|---|---|
| Camera unavailable | Show camera unavailable; alert operator | No biometric attempt or event |
| No/multiple faces | Show neutral guidance; retry bounded interaction | Do not match or persist an event |
| Unknown/ambiguous | Show unable-to-verify result | Do not reveal raw scores; record safe operational outcome |
| Liveness/quality failure | Retry or show operator state | Reject event; rate-limit repeated attempts if needed |
| Remote DB unavailable | Show queued result if local queue is healthy | Encrypt and queue minimum event; sync later idempotently |
| Local queue full/unavailable | Show operator attention required | Fail closed; do not silently drop or store raw frames |
| Duplicate/cooldown | Show already-recorded result | Suppress duplicate; preserve minimal suppression metric/audit |
| Model unavailable | Show operator attention required | Fail closed for biometric identity |
| Clock/storage integrity failure | Show operator attention required | Do not create an event until safe time/storage is restored |

## 8. Technology and deployment decision gates

The implementation team must select and document:
- Raspberry Pi OS/runtime, camera API, supported webcam, resolution, frame rate, and thermal/power constraints;
- recognition/liveness library or service, model license, provenance, checksum, threshold, and Pi performance;
- local database/queue and encryption/key-management approach;
- remote database API and authentication, if a remote database is used;
- administrator identity provider and RBAC implementation;
- packaging, secure update, rollback, watchdog, and offline synchronization topology;
- monitoring, backup, deletion propagation, and physical support model.

Do not add a model or cloud service merely because it is convenient. The selected solution must satisfy the privacy/security steering gates and the approved deployment jurisdiction.

## 9. Testing strategy

- Pure policy tests cover stable 3-of-5 matching, liveness outcomes, cooldown, idempotency, UTC/timezone conversion, queue decisions, expiry, and safe rejection.
- Recognition adapter tests use approved representative evaluation fixtures and verify threshold behavior, model versioning, and false-match limitations.
- Integration tests cover persistence, RBAC, enrollment/deletion, audit, retention/deletion, queue synchronization, retry/idempotency, and failure recovery.
- UI tests cover neutral kiosk states, camera/recognition outcomes, queued/suppressed/operator states, and accessibility.
- Security tests cover unauthorized enrollment/template access, role escalation, injection, replay, duplicate submissions, secret exposure, queue tampering, exports, and audit tampering.
- Pilot tests use the actual Raspberry Pi 4, webcam, lighting, distance, kiosk placement, network, storage, and support process. Results must document limitations, p95 latency, and rollback criteria.
