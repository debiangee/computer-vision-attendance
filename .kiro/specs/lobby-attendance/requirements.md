# Lobby Computer-Vision Attendance Requirements

**Status:** Draft revision — automatic recognized-person event logging for Raspberry Pi 4 and webcam. Production remains blocked until the privacy/legal position and technical acceptance targets are approved.

## 1. Goal and scope

The system is a local-first lobby kiosk that detects and recognizes enrolled, RBAC-approved people and writes a timestamped recognition event to a database. It records **recognized-person encounters**; it does not infer Time In, Time Out, shifts, payroll status, or attendance sessions.

### In scope for the MVP
- RBAC-controlled enrollment and user lifecycle management.
- Camera-assisted recognition with liveness or presentation-attack protection.
- Automatic event logging after a stable, safe recognition result.
- Duplicate suppression using a configurable per-person/per-camera cooldown.
- Local-first processing on Raspberry Pi 4 with a simple webcam.
- Database persistence plus a protected local queue when the database is unavailable.
- Audit history, retention/deletion controls, operator health status, and administrator correction.
- No external HR, payroll, or other integrations.

### Out of scope unless separately approved
- Identifying unregistered visitors or passers-by.
- Inferring Time In/Time Out, shifts, holidays, breaks, missing events, overnight sessions, or payroll status.
- Continuous video storage, background watchlists, or automated disciplinary decisions.
- Emotion, gender, age, health, productivity, or behavioral inference.
- Third-party biometric processing or cloud model calls by default.

## 2. Actors and RBAC

- **Kiosk service:** Captures/recognizes and appends events; cannot administer users, browse reports, export templates, or change policy.
- **Enrollment administrator:** Creates, verifies, suspends, rotates, and de-enrolls authorized users.
- **Attendance administrator:** Views events and performs audited corrections; cannot access raw templates by default.
- **Auditor:** Read-only access to approved attendance and security audit data.
- **System operator:** Maintains Raspberry Pi health, application, model/configuration version, storage, and queue synchronization.
- **RBAC administrator:** Assigns roles and permissions; separate from routine enrollment/correction work.
- **Authorized person:** An enrolled, active person who may be recognized by the system.

Every sensitive operation SHALL be denied by default and granted only through an explicit role and site scope.

## 3. Confirmed and proposed business decisions

| Decision | Current decision/default | Status |
|---|---|---|
| Authorized population | Only enrolled users approved through RBAC | Confirmed direction; population owner still required |
| User action | No Time In/Time Out action; automatic recognized-person event | Confirmed direction |
| Event meaning | A safe recognized encounter, not a shift/session or in/out status | Confirmed direction |
| Stable match | Same identity in at least 3 of 5 sampled frames over about 1 second | Recommended starting point; must be calibrated |
| Duplicate cooldown | Five minutes per person per camera, configurable | Recommended starting point |
| Time storage | UTC persistence; configured site timezone for display | Recommended |
| Shifts/holidays/overnight | Not modeled; only raw recognized events are stored | Confirmed direction |
| Retention | Three months for templates and attendance events, with deletion verification | Proposed; privacy/legal/operational approval required |
| Notice/consent | Owner currently requests no separate flow because this is time capture | Provisional risk decision; production blocker until reviewed |
| Non-biometric alternative | None currently planned | Provisional risk decision; production blocker if required by review |
| Offline behavior | Encrypted local durable queue, then idempotent synchronization | Recommended |
| Hardware | Raspberry Pi 4 and simple webcam | Confirmed target; compatibility testing required |
| Performance | Fast decision, proposed under 2 seconds at p95 on target hardware | Recommended target; must be measured |
| Integrations | Database logging only; no HR/payroll integration yet | Confirmed MVP scope |

## 4. Functional requirements

### REQ-001 — Compliance mode and privacy decision
**THE SYSTEM SHALL** support a configurable compliance gate for the approved purpose, notice, consent or other lawful-basis record, retention, deletion, and any required non-biometric alternative.

The current owner decision is to provide no separate notice/consent flow and no alternative. This mode SHALL remain development/pilot-only until the authorized privacy/legal owner confirms that position is acceptable for the deployment. If review requires notice, consent/lawful basis, or an alternative, the system SHALL block biometric operation until that requirement is implemented.

### REQ-002 — RBAC-controlled enrollment
**WHEN** an Enrollment Administrator creates or updates a person, **THE SYSTEM SHALL** verify the administrator's role and site scope, verify the person is authorized, capture only minimum profile data, and create a versioned biometric template lifecycle record.

**THE SYSTEM SHALL** support active, suspended, and de-enrolled states. Suspended or de-enrolled people SHALL NOT match or create events.

**WHEN** a person is enrolled without an approved compliance state, **THE SYSTEM SHALL** prevent production activation and record the reason in the audit trail.

### REQ-003 — Ephemeral camera capture
**WHEN** the kiosk is running, **THE SYSTEM SHALL** use the webcam only for bounded recognition interactions and SHALL NOT persist continuous video, snapshots, or raw frames by default.

**WHEN** camera permission, device initialization, or capture fails, **THE SYSTEM SHALL** fail closed for recognition-event creation, show a safe kiosk state, and alert the System Operator.

### REQ-004 — Safe and stable recognition
**WHEN** a face is detected, **THE SYSTEM SHALL** perform quality, recognition, and liveness checks using the configured model and threshold.

**WHEN** the same authorized identity is accepted in the proposed stable sample window of at least 3 of 5 frames over approximately 1 second, and liveness passes, **THE SYSTEM SHALL** produce an eligible recognition observation.

**WHEN** no face, multiple faces, an unknown person, an ambiguous/low-confidence match, poor quality, or liveness failure is detected, **THE SYSTEM SHALL** reject automatic event creation.

**THE SYSTEM SHALL NOT** show raw confidence values or treat a single-frame match as sufficient proof of identity.

### REQ-005 — Automatic recognized-person event
**WHEN** an eligible recognition observation is produced and the person is outside the configured cooldown, **THE SYSTEM SHALL** create one immutable recognized-person encounter event without requiring a Time In/Time Out selection.

**THE SYSTEM SHALL NOT** infer that the event is a clock-in, clock-out, shift, presence duration, or payroll decision.

### REQ-006 — Event data and idempotency
**WHEN** an event is created, **THE SYSTEM SHALL** persist at least: event ID, person ID, event type `RECOGNIZED_ENCOUNTER`, UTC timestamp, site/camera context, source, model/version metadata, policy version, idempotency key, storage state, and audit metadata.

**THE SYSTEM SHALL** protect writes against retries, reconnect synchronization, and duplicate submissions. One camera frame SHALL NOT create multiple event rows.

### REQ-007 — Cooldown and event suppression
**WHEN** an eligible recognition for a person occurs within the configured per-person/per-camera cooldown, **THE SYSTEM SHALL** suppress the duplicate event, retain suitable audit/metric information, and not overwrite the earlier event.

The recommended initial cooldown is five minutes. The value SHALL be configurable, documented, and validated against the actual lobby traffic pattern.

### REQ-008 — Administrative correction
**WHEN** an Attendance Administrator corrects or deletes an event, **THE SYSTEM SHALL** require authenticated RBAC authorization, a reason, affected event, before/after representation, actor, timestamp, and audit history.

Corrections SHALL preserve the original event and SHALL NOT alter the original model observation or raw audit history.

### REQ-009 — Access control and data protection
**THE SYSTEM SHALL** enforce the role matrix for enrollment, template management, event access, reports, exports, corrections, configuration, queue operations, synchronization, and audit logs.

**THE SYSTEM SHALL** protect templates, events, local queue data, backups, and secrets using approved encryption and SHALL NOT place biometric data or secrets in application logs.

### REQ-010 — Retention and deletion
**WHEN** the approved retention period expires or an authorized deletion/de-enrollment request is processed, **THE SYSTEM SHALL** delete or irreversibly de-identify applicable templates and event data, including applicable queue, backup, replica, and export copies.

The proposed retention period is three months. The final value and deletion obligations require privacy/legal/operational approval and SHALL be auditable.

### REQ-011 — Offline queue and synchronization
**WHEN** the database is unavailable but the Raspberry Pi and protected local storage are healthy, **THE SYSTEM SHALL** encrypt and append the minimum event payload to a bounded local queue.

**WHEN** connectivity returns, **THE SYSTEM SHALL** synchronize queued events using authenticated, retry-safe, idempotent requests and mark each result audibly as synchronized, rejected, or requiring operator action.

**WHEN** local storage is unavailable, full, expired, or integrity verification fails, **THE SYSTEM SHALL** fail closed and SHALL NOT guess, drop silently, or write raw frames to recover.

### REQ-012 — Kiosk and operator states
**THE SYSTEM SHALL** provide states for camera unavailable, no face, multiple faces, unknown/low confidence, liveness failure, recognized event recorded, duplicate suppressed, event queued locally, synchronization failure, local queue full, storage failure, and operator action required.

The kiosk SHALL return to a neutral state after each bounded interaction and SHALL not expose raw confidence, templates, or sensitive diagnostics.

### REQ-013 — Degraded operation
**WHEN** the camera, model, local database, remote database, network, clock, or required dependency is unavailable, **THE SYSTEM SHALL** fail closed for unsafe recognition and show an appropriate operator-safe state.

The system SHALL not create a synthetic event merely because a face was seen, a previous event exists, or a dependency later recovers.

### REQ-014 — Audit and observability
**THE SYSTEM SHALL** audit enrollment, role changes, consent/compliance state changes, template replacement/deletion, recognition outcomes needed for operations, event creation/suppression, synchronization, corrections, exports, configuration changes, authentication, model/version changes, and security failures.

Operational metrics SHALL be privacy-minimized and SHALL not retain unnecessary images, templates, or raw model scores.

### REQ-015 — Recognition quality and performance
**BEFORE** production use, **THE TEAM SHALL** evaluate recognition and liveness performance with representative, lawfully sourced data and the actual Raspberry Pi/webcam environment.

The evaluation SHALL document false-acceptance and false-rejection limitations, stable-frame behavior, liveness limitations, threshold rationale, and rollback/fail-closed criteria. The proposed target is an eligible-event decision within 2 seconds at the 95th percentile without weakening safety thresholds.

## 5. Non-functional requirements

- **Privacy:** Purpose limitation, privacy/legal review, data minimization, retention/deletion, and the current no-notice/no-consent/no-alternative decision are release gates.
- **Security:** Least privilege, RBAC, strong administrator authentication, encryption, secure updates, model/dependency provenance, auditability, and threat-model findings are release gates.
- **Reliability:** Device/model/database/network failure must not create false events or silently lose queued events.
- **Performance:** Measure capture, detection, stable-frame aggregation, recognition, policy, persistence, and synchronization separately on Raspberry Pi 4.
- **Maintainability:** Camera and recognition providers must be replaceable without rewriting event policy.
- **Testability:** Stable-match, cooldown, queue, synchronization, and event policy must be testable without a live camera.

## 6. Acceptance gate

The MVP is not production-ready until:
1. RBAC roles and scopes are implemented and tested;
2. the privacy/legal owner has approved or rejected the no-notice/no-consent/no-alternative position;
3. three-month retention and deletion are verified across active data, queue, backups, replicas, and exports;
4. recognition/liveness evaluation documents limitations and safe thresholds on the target hardware;
5. cooldown, idempotency, queue recovery, and failure-closed behavior have evidence;
6. security review has no unresolved blocker or major finding; and
7. an actual lobby pilot confirms the target performance without storing unauthorized video or templates.

## 7. Remaining decisions

1. Which people and sites are eligible, and who owns RBAC approval?
2. Which identity/authentication system protects administrator roles?
3. Is the proposed five-minute cooldown correct for lobby traffic?
4. What site timezone and clock-synchronization source apply?
5. Is three-month retention approved for templates and events, and how must backups be handled?
6. What local queue capacity, maximum age, and operator alert process are required?
7. What exact Raspberry Pi 4 model/OS/webcam/resolution and physical security setup will be used?
8. What false-acceptance/false-rejection limits and latency target are acceptable?
9. Does privacy/employment law require notice, consent/lawful basis, or a non-biometric alternative despite the current owner position?
10. Which database will receive synchronized events, and what authentication protects it?
