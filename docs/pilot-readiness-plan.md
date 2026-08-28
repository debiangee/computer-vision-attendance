# Pilot Readiness Plan

## Purpose

This plan defines the work required to move the Lobby Attendance system from a supervised executive demo to a narrowly scoped pilot. It is an engineering and delivery checklist, not legal advice or production approval.

The current implementation is **executive-demo ready** but remains **NEEDS_REWORK** for a workplace pilot or production deployment.

## Proposed pilot boundary

The first pilot should be deliberately narrow:

- One Raspberry Pi 4.
- One approved webcam and one approved local model asset.
- One physical site.
- A known, consented, RBAC-authorized participant population.
- Recognition-event logging only.
- No payroll, disciplinary, automated attendance, or access-control decisions.
- No continuous video recording or cloud frame/template processing.
- Human/operator fallback for every failed or disputed recognition.
- Written stop criteria, rollback procedure, pilot owner, and support contact.

## Priority definitions

- **P0 — Pilot blocker:** Must be complete and approved before participant enrollment or pilot launch.
- **P1 — Pilot hardening:** Must be complete before unattended or business-reliant operation.
- **P2 — Broader rollout:** Required before multiple sites, larger populations, or production use.

---

## P0 — Privacy, security, and authorization blockers

### P0-01: Approve privacy and legal basis

**Problem:** The current no-notice/no-consent/no-alternative position is provisional and cannot be treated as pilot approval.

- [ ] Complete a privacy impact/risk assessment.
- [ ] Confirm the lawful basis for face-based processing in the pilot jurisdiction.
- [ ] Approve participant notice and consent or another documented lawful basis.
- [ ] Define the non-biometric fallback, such as badge, PIN, or operator-assisted logging.
- [ ] Define the authorized participant population and purpose limitation.
- [ ] Approve the proposed retention period and deletion process.
- [ ] Document prohibited uses: surveillance, disciplinary decisions, emotion, demographic, health, productivity, or behavioral inference.
- [ ] Obtain written sign-off from privacy/legal and the business owner.

**Current status:** `ENGINEERING PACKAGE PREPARED / EXTERNAL APPROVAL PENDING` — Engineering packet prepared in `docs/pilot-privacy-and-data-governance.md` covering purpose limitation, data inventory and flow, participant notice draft, non-biometric fallback requirements, retention/deletion contract, pilot stop criteria, acceptance criteria, decision register, RACI placeholders, data-copy inventory, participant-rights workflow requirements, and outage semantics. Privacy/legal approval, participant notice/consent or lawful-basis decision, fallback approval/implementation, retention approval, deletion-propagation approval, named stop/resume authority, and target-device evidence remain external or unresolved pilot gates. The local recognition service now fails closed when the technical compliance gate is not approved; that gate is not legal approval.

**Done when:** Every pilot participant receives approved notice, has an approved fallback, and the privacy/legal decision is recorded.

**Evidence:** Approved privacy assessment, notice/consent artifact, fallback procedure, participant scope, retention/deletion policy, sign-off record.

### P0-02: Replace static-token authentication

**Current status:** `ENGINEERING COMPLETE` — Signed-session boundary implemented in `src/lobby_attendance/api/auth.py` with HMAC-SHA-256 signature validation, issuer/audience checks, token-kind enforcement, bounded expiry/issued-at lifetime, authentication-time claims, token-ID tracking, and site/subject scope claims. TLS fail-closed behavior rejects non-HTTPS requests in signed mode (with optional trusted-proxy forwarding). Durable token revocation persists in `auth_token_revocations` with an audited `POST /api/admin/auth/revoke` endpoint. Recent-auth enforcement requires fresh `auth_time` for sensitive mutations. A bounded process-local failed-auth rate limiter returns safe 429 responses. Configuration is environment-driven and documented in `docs/pilot-authentication-design.md`. Focused validation: **30 tests passed.**

- [x] Add token/session expiry and revocation.
- [x] Require TLS for administrative and synchronization traffic.
- [x] Separate kiosk/service credentials from administrator credentials.
- [x] Require re-authentication for enrollment, de-enrollment, reset, export, correction, and role changes.
- [x] Add authentication-failure monitoring and rate limiting.
- [ ] Integrate approved SSO/OIDC or an approved strong administrator identity provider. *(external gate)*
- [ ] Store secrets using an approved secret-management method. *(external gate — key custody)*

**Remaining external gates:** Approved IdP/identity-gateway issuance, key/secret custody, TLS termination and certificate operations, trusted-proxy review, account lifecycle integration, and edge-level abuse monitoring.

**Done when:** No pilot administrator operation depends on a shared static bearer token, and expired/revoked credentials cannot perform protected actions.

**Evidence:** Authentication design (`docs/pilot-authentication-design.md`), signed-session implementation, 30-test focused suite, expiry/revocation/TLS/rate-limit coverage, environment configuration.

### P0-03: Enforce effective RBAC and site boundaries

**Current status:** `ENGINEERING COMPLETE` — Signed sessions require both site scope and admin subject scope; protected routes enforce current-site scope and reject tokens from other sites; user and event queries apply parameterized scope filters; corrections cannot move records outside the authorized scope; kiosk token-kind/role separation is enforced; and conflicting operational/RBAC role combinations are rejected. See `docs/pilot-rbac-scope-design.md`. Focused validation: **44 tests passed.**

- [x] Enforce server-side site scope on every protected operation.
- [x] Enforce subject scope for enrollment administrators.
- [x] Restrict the kiosk service to capture/recognition and append-only event submission.
- [x] Prevent kiosk access to administration, templates, event browsing, exports, and policy changes.
- [x] Separate enrollment, attendance correction, audit, system-operator, and RBAC-administrator permissions.
- [x] Prevent raw template access for attendance administrators and auditors.
- [x] Audit authorization denials and all sensitive mutations.
- [x] Add separation-of-duties review for pilot accounts.
- [ ] Integrate approved IdP role/scope issuance. *(external gate)*
- [ ] Implement named-account separation and offboarding. *(external gate)*
- [ ] Conduct formal access review. *(external gate)*

**Remaining external gates:** Approved IdP role/scope mapping, named-account separation, operational offboarding, access review, and signed deployment.

**Done when:** Authorization tests prove that each role can perform only its approved actions within its assigned site and subject scope.

**Evidence:** Role/permission matrix, 44-test focused suite including cross-subject denial, cross-site denial, separation-of-duties rejection, kiosk isolation, and scope-filtered queries (`tests/test_pilot_auth.py`), design document (`docs/pilot-rbac-scope-design.md`).

### P0-04: Protect biometric and event data

**Current status:** `IN PROGRESS` — AES-GCM encrypted in-memory SQLite serialization to an authenticated file envelope is implemented in `src/lobby_attendance/storage/sqlite.py` and is now wired through `create_app()` using `LOBBY_ATTENDANCE_STORAGE_ENCRYPTION_KEY` and `LOBBY_ATTENDANCE_STORAGE_ENCRYPTION_REQUIRED`. Successful request teardown persists through `SQLiteStore.commit()`, and an owned-store close hook supports deterministic local shutdown. `cryptography==50.0.0` is pinned in `pyproject.toml`. Focused encrypted-storage coverage passes (35 tests), the full local suite passes (70 tests), and an encrypted Flask/mock kiosk smoke test persisted one synthetic event across close/reopen with no plaintext WAL. This is local engineering evidence only. Deletion-propagation manifest schema, repository, retention integration, production key custody, backup/replica controls, and recovery evidence remain pending.

- [x] Implement encrypted SQLite storage with AES-GCM authenticated envelope.
- [x] Define key validation (64-hex / 32-byte requirement).
- [x] Fail closed when encryption is required but key is absent.
- [x] Eliminate plaintext WAL for encrypted mode (journal_mode = MEMORY).
- [x] Atomic persist via temp file + fsync + rename.
- [ ] Add deletion-propagation manifest schema and repository.
- [ ] Integrate manifest creation with retention/de-enrollment operations.
- [x] Wire encrypted store instantiation into `create_app()`.
- [x] Add storage verification tests (encrypted round-trip, wrong-key rejection, plaintext absence).
- [x] Pin `cryptography==50.0.0` in `pyproject.toml`.
- [ ] Create `docs/pilot-storage-and-deletion-design.md`.
- [ ] Define key creation, rotation, access, backup, and revocation procedures. *(external gate)*
- [ ] Test device compromise and key-compromise response. *(external gate)*
- [ ] Verify deletion from WAL files, backups, and approved replicas. *(external gate)*

**Remaining external gates:** Key custody/rotation/revocation procedures, full-disk encryption, backup encryption, SQLCipher evaluation, remote deletion propagation approval, and recovery testing.

**Done when:** A security reviewer can trace where sensitive data is stored, how it is encrypted, who can access it, and how it is deleted.

**Evidence:** Data-flow diagram, encryption/key-management design, storage inspection, deletion test, backup/restore test, security approval.

### P0-05: Validate recognition and presentation-attack behavior

**Problem:** The current normalized crop matcher and presence heuristic are demonstration components, not pilot evidence.

- [ ] Test the actual Raspberry Pi, webcam, model, camera distance, lighting, and mounting position.
- [ ] Define and approve false-accept and false-reject targets.
- [ ] Measure enrolled-user recognition, unknown-person rejection, ambiguous matches, and lookalike behavior.
- [ ] Measure enrollment failure and retry rates.
- [ ] Test print, screen, replay, and static-image presentation attempts.
- [ ] Calibrate thresholds using an approved representative evaluation set.
- [ ] Measure decision latency, including p95 latency.
- [ ] Document environmental and population limitations.
- [ ] Decide whether the heuristic matcher/liveness check must be replaced with an evaluated model and PAD control.

**Done when:** Security, product, and privacy owners approve measured accuracy, rejection, liveness/PAD, and latency results for the exact pilot hardware and population.

**Evidence:** Evaluation protocol, consent/provenance record for test data, metrics report, threshold configuration, attack-test results, approval decision.

---

## P1 — Reliability and unattended-operation hardening

### P1-01: Implement durable offline queue and synchronization

**Problem:** Executive demo storage failure intentionally fails closed, and the synchronization sink is in memory.

- [ ] Implement an encrypted, append-only local event queue.
- [ ] Bound queue size and event age.
- [ ] Add authenticated remote synchronization.
- [ ] Preserve idempotency keys across retries and reconnects.
- [ ] Enforce lease ownership and safe retry behavior.
- [ ] Prevent duplicate events after reconnect.
- [ ] Add queue-full, storage-full, and synchronization-failure states.
- [ ] Alert the system operator when queued events cannot be delivered.
- [ ] Test restart, power loss, network outage, duplicate delivery, and remote failure.

**Done when:** A disconnected Pi can safely retain minimal events, recover after restart, synchronize exactly once from the system-of-record perspective, and alert on failure.

**Evidence:** Queue design, encryption configuration, synchronization tests, outage/restart rehearsal, duplicate/idempotency report, operator alert evidence.

### P1-02: Resolve SQLite threading and concurrency behavior

**Problem:** SQLite connection/threading limitations and process-local camera locking remain unresolved.

- [ ] Define supported service process and worker topology.
- [ ] Ensure database connections are owned and used safely per request/thread.
- [ ] Test concurrent kiosk interactions, enrollment, reset, retention, and synchronization.
- [ ] Enforce a single-worker deployment or implement external/device-level coordination.
- [ ] Decide whether SQLite remains appropriate for the pilot.
- [ ] Test WAL, backup, restore, corruption detection, and power-loss recovery.

**Done when:** The supported deployment topology is documented and concurrency/recovery tests pass without cross-request database errors or duplicate recognition events.

**Evidence:** Deployment topology, concurrency test results, recovery rehearsal, database backup/restore report.

### P1-03: Harden the Raspberry Pi deployment

- [ ] Create a repeatable installation or image-building process.
- [ ] Pin Python, OS, and system dependencies.
- [ ] Verify model provenance, checksum, license, and approved path.
- [ ] Run the service as a dedicated least-privilege account.
- [ ] Restrict camera, database, model, and filesystem permissions.
- [ ] Disable unused services and restrict remote administration.
- [ ] Configure firewall and local network boundaries.
- [ ] Add watchdog and automatic service recovery.
- [ ] Add disk-space, temperature, time-sync, camera, and model health checks.
- [ ] Define secure update and rollback procedures.
- [ ] Physically secure the Pi and webcam.

**Done when:** A new approved Pi can be provisioned repeatably, runs with least privilege, reports health, restarts safely, and can be rolled back.

**Evidence:** Installation/image artifact, hardening checklist, service configuration, health dashboard, update/rollback rehearsal.

### P1-04: Protect logs and operational telemetry

- [ ] Redact credentials, frames, templates, scores, and unnecessary personal data.
- [ ] Define log retention and access controls.
- [ ] Review generic exception logging and traceback handling.
- [ ] Add metrics for camera readiness, model readiness, latency, rejection states, storage failure, queue depth, and synchronization failure.
- [ ] Alert on disk-full, camera failure, service failure, repeated authorization failure, and queue age.
- [ ] Audit model/configuration changes and administrative actions.

**Done when:** Operators can diagnose pilot failures without exposing biometric data or credentials.

**Evidence:** Logging policy, redaction tests, sample sanitized logs, metrics/alert configuration, access review.

---

## P1 — Product, operator, and recovery workflows

### P1-05: Complete operator fallback and correction workflow

- [ ] Define the response to false rejection.
- [ ] Define the response to suspected false acceptance.
- [ ] Provide the approved non-biometric fallback.
- [ ] Allow only authorized, audited corrections.
- [ ] Preserve the original immutable event and correction history.
- [ ] Define escalation and incident handling.
- [ ] Document de-enrollment, reset, and participant removal.

**Done when:** An operator can resolve a failed or disputed interaction without bypassing audit, authorization, or privacy controls.

**Evidence:** Operator runbook, correction tests, fallback rehearsal, audit records, incident workflow.

### P1-06: Validate kiosk and admin user experience

- [ ] Test camera unavailable.
- [ ] Test no face, multiple faces, unknown, ambiguous, low-quality, and liveness-failure states.
- [ ] Test cooldown suppression and storage-unavailable behavior.
- [ ] Test queue-full and operator-action-required states.
- [ ] Test browser refresh, service restart, and recovery.
- [ ] Test accessibility, readability, keyboard operation, and neutral messaging.
- [ ] Confirm that confidence scores, templates, frames, and liveness internals are not exposed.

**Done when:** Every documented operational state has a clear, safe, and recoverable UI or operator-visible response.

**Evidence:** UI test matrix, accessibility review, screenshots or test recordings without personal biometric data, recovery results.

### P1-07: Create pilot operations and incident runbooks

- [ ] Enrollment and participant verification.
- [ ] De-enrollment and deletion request.
- [ ] Camera replacement and calibration.
- [ ] Model/configuration rollback.
- [ ] Storage-full and queue-full response.
- [ ] Network outage and synchronization recovery.
- [ ] Device theft or compromise.
- [ ] Suspected false acceptance or repeated false rejection.
- [ ] Backup restore and disaster recovery.
- [ ] Pilot shutdown and rollback.

**Done when:** An operator who did not build the system can follow the runbooks and complete each rehearsal successfully.

**Evidence:** Versioned runbooks, rehearsal records, support contacts, escalation matrix, rollback results.

---

## P2 — Broader rollout and production work

- [ ] Independent security review or penetration test.
- [ ] Formal threat-model refresh.
- [ ] Multi-site and multi-camera authorization model.
- [ ] Larger population and representative environmental evaluation.
- [ ] Signed model distribution and rollback governance.
- [ ] Formal disaster-recovery exercise.
- [ ] Backup access and deletion-propagation verification.
- [ ] Incident-response exercise.
- [ ] Long-term retention and legal review.
- [ ] Production monitoring, support, and service-level objectives.
- [ ] Business-owner acceptance of false-accept and false-reject tradeoffs.

---

## Pilot release gates

The pilot must not begin until all gates are marked complete and approved.

### Governance gate

- [ ] Pilot scope, owner, participants, site, dates, and stop criteria approved.
- [ ] Privacy impact assessment approved.
- [ ] Lawful basis and participant notice/consent approved.
- [ ] Non-biometric fallback approved.
- [ ] Retention and deletion policy approved.

### Identity and security gate

- [x] Strong authentication, TLS, expiry, and revocation implemented. *(P0-02 engineering complete)*
- [x] Effective RBAC and site scope tested. *(P0-03 engineering complete)*
- [x] Sensitive actions require re-authentication and are audited. *(P0-02/P0-03)*
- [ ] Templates, events, queue, backups, and secrets are encrypted and key-managed. *(P0-04 in progress)*
- [ ] Security review has no unresolved pilot-blocking findings.

### Recognition gate

- [ ] Actual Pi/webcam/model evaluation completed.
- [ ] Recognition thresholds calibrated and approved.
- [ ] Unknown-person rejection tested.
- [ ] Liveness/PAD tests completed.
- [ ] Latency and reliability targets met.
- [ ] Safe rejection remains the default for uncertainty.

### Reliability gate

- [ ] Offline queue and authenticated synchronization tested.
- [ ] Idempotency and lease ownership verified.
- [ ] Power-loss, storage-full, camera-failure, and network-outage rehearsals pass.
- [ ] Backup and restore verified.
- [ ] Supported single-process or multi-process topology documented.

### Operations gate

- [ ] Pi hardening completed.
- [ ] Watchdog and health monitoring operational.
- [ ] Operator, correction, fallback, deletion, and incident runbooks approved.
- [ ] Support owner and escalation path assigned.
- [ ] Pilot rollback rehearsal completed.

---

## Recommended implementation order

1. Complete privacy/legal scope and pilot boundaries.
2. Implement authentication, TLS, RBAC, and administrator re-authentication.
3. Implement encrypted storage and key management.
4. Evaluate the actual Pi, webcam, model, population, and environment.
5. Implement durable offline queue and synchronization.
6. Harden the Pi deployment and recovery process.
7. Complete fallback, correction, deletion, incident, and operator workflows.
8. Run security review and full pilot rehearsal.
9. Launch a small supervised pilot with explicit stop criteria.

## Current decision

**Executive demo:** Conditionally acceptable for a supervised, consenting, local presentation.

**Pilot:** Not approved until all P0 gates and the required P1 operational gates are complete. P0-01, P0-02, and P0-03 engineering controls are complete; P0-04 encrypted storage is wired and locally tested; P0-05 target-device evaluation harness is implemented and ready for transfer to the Raspberry Pi. External gates (IdP, key custody, TLS certificates, privacy/legal approval, physical device evaluation evidence, PAD/accuracy calibration) remain open.

**Production:** NEEDS_REWORK.

## P0-01 handoff clarification — 2026-08-27

P0-01 is **prepared for authorized review** and remains **OPEN/BLOCKED** for pilot release. The acceptance criteria, decision register, RACI placeholders, copy inventory, participant-rights requirements, fallback decision requirements, stop/resume authority, and remote-versus-local outage semantics are maintained in `docs/pilot-privacy-and-data-governance.md` §§10–11.

The local technical compliance gate is fail-closed: `RecognitionEventService` rejects recognition when approval is absent, does not write or queue an event, and records a bounded `recognition:blocked` denial when audit storage is available. This does not establish lawful basis, participant notice/consent, a fallback, retention approval, deletion propagation, named authority, or pilot approval.

P0-01 acceptance remains blocked by: privacy/legal and employment review; lawful-basis/notice/consent/withdrawal decision; participant-rights workflow; selected and implemented non-biometric fallback; retention/legal-hold schedule; deletion verification for every enabled copy; named RACI and stop/resume authority; and Raspberry Pi/webcam/model/PAD/latency evidence.
