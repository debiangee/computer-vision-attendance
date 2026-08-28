# Security Review — QA-010 Remediation

**Scope:** Current working tree for the Raspberry Pi lobby-attendance MVP after QA-010 remediation. This review covers the activation lifecycle, denial stability/audit behavior, regressions introduced by the remediation, and the previously identified production security/privacy gates. Security did not modify production source or tests.

## 1. Decision summary

- **Local code gate:** `PASS` for QA-010 and the reviewed local activation boundary. Activation now requires both explicit compliance approval and an active, non-retired protected-template metadata record with nonblank model version, template version, and protected hash. The negative path is stable, leaves the user suspended, and writes a bounded denied audit event.
- **Production/security gate:** `NEEDS_REWORK`. This is not production approval. The unresolved major findings below remain release blockers.
- **New QA-010 security/privacy regressions:** None found in the reviewed code and tests. The remediation does not accept raw face images, templates, confidence values, or caller-controlled event timestamps.

## 2. QA-010 evidence

### Confirmed local controls

| Control | Evidence | Result |
|---|---|---|
| Compliance approval is required | `src/lobby_attendance/application/enrollment.py:59-69` checks `compliance_approved` before the lifecycle check and raises `ComplianceApprovalError`; `src/lobby_attendance/api/app.py:254-255` maps it to the stable `compliance-not-approved` response. | Pass. Approval remains fail-closed by default. |
| Template lifecycle is required after approval | `src/lobby_attendance/storage/repositories.py:109-123` requires `retired_at IS NULL`, nonblank trimmed `model_version`, `template_version`, and `template_hash`. | Pass. A missing, retired, or incomplete metadata record cannot activate a user. |
| Denial is stable and safe | `src/lobby_attendance/api/app.py:256-261` returns HTTP 409 with `error=template-lifecycle-incomplete` and the neutral message `biometric activation requires a protected template`. | Pass. No exception details, biometric data, or template values are returned. |
| Denial preserves suspended status | `EnrollmentService.activate()` only calls `set_status(...ACTIVE)` after both gates; the API test asserts the user remains `SUSPENDED`. | Pass. |
| Denial is audited | `enrollment.py:70-78` appends `enrollment:activate` with outcome `denied` and bounded reason `template-lifecycle-incomplete`; the test verifies the denied audit record. | Pass. |
| Valid lifecycle permits activation | `tests/test_phase3_api.py::test_compliance_approved_activation_and_health_state` registers valid metadata and verifies HTTP 200/active status. | Pass. |

### Validation results

- `python -m pytest tests/test_phase3_api.py -k "activation" -q` — **PASS**, 3 passed, 16 deselected.
- `python -m pytest -q` — **PASS**, 70 passed in 4.25s.
- Supplemental API smoke — **PASS** for compliance-precedence denial, no-template denial, retired-template denial, valid-template activation, suspended status preservation, and denied audit evidence.
- `python -m compileall -q src tests` — **PASS**.
- `python -m pip check` — **PASS**, no broken requirements.

The focused test and supplemental smoke are local application evidence only; they do not establish privacy/legal approval, production identity assurance, encrypted deployment, target-device safety, or model accuracy.

## 3. Regression review

No new local security/privacy regression was identified from QA-010. The implementation:

- checks compliance before revealing the separate lifecycle state;
- stores only metadata and a protected hash at this boundary, not raw images or face templates;
- uses parameterized SQL for the lifecycle lookup;
- rejects retired metadata and whitespace-only lifecycle values;
- preserves the existing neutral API messages and audit boundary; and
- does not alter the HTTP rule that the server owns recognition-event time.

Residual design limitation: `has_active_versioned_template()` accepts any qualifying non-retired metadata row rather than proving a separately signed/current model registry state. This is consistent with the current local lifecycle contract, but provenance, model governance, and deployment evaluation remain blocked under SEC-06/SEC-07 below.

## 4. Confirmed unresolved production findings

These findings are retained from the prior security gate. QA-010 closure does not reduce their severity.

### SEC-01 — Major (in progress) — Sensitive local data lacks encryption and key management
- **Affected files:** `src/lobby_attendance/storage/sqlite.py:14-31`, `src/lobby_attendance/storage/schema.py`, `src/lobby_attendance/application/events.py`, `.env.example`.
- **Precondition/reproduction:** Run with a normal filesystem SQLite database and inspect the database, WAL, or `local_queue_items.payload_json`. The store uses ordinary SQLite/WAL and no authenticated encryption, external key provider, rotation, ACL, or backup-encryption boundary is configured.
- **Impact:** Filesystem, WAL, backup, or queue disclosure can expose attendance identifiers, event metadata, audit metadata, and queued payloads; tampering/rollback is not cryptographically detectable.
- **Evidence:** Local encrypted-storage tests cover authenticated envelope round-trip, wrong-key and plaintext-database rejection, rollback, factory wiring, request commit persistence, and no plaintext WAL in the encrypted path. Production key custody, rotation/revocation, backup/replica encryption, deletion recovery, and deployment ACL evidence are not present.
- **P0-04 engineering progress (2026-08-27):** AES-GCM encrypted in-memory SQLite serialization is implemented and wired through `create_app()` using explicit `LOBBY_ATTENDANCE_STORAGE_ENCRYPTION_KEY` and `LOBBY_ATTENDANCE_STORAGE_ENCRYPTION_REQUIRED` settings. Successful request teardown calls `SQLiteStore.commit()`, owned stores expose a deterministic close hook, and `cryptography==50.0.0` is pinned. The full local suite passes 70 tests and the encrypted mock kiosk smoke test persisted a synthetic event across close/reopen without plaintext WAL. Deletion-propagation manifests, key custody, backup controls, and recovery evidence remain pending.
- **Remaining:** Add deletion manifests and remote propagation/reconciliation, obtain key custody/rotation/revocation procedures, complete backup encryption and recovery testing, and review queue-at-rest/deployment ACL controls.
- **Owner:** Security + Platform.

### SEC-02 — Major (partially remediated) — Static bearer authentication is not production identity, revocation, or TLS enforcement
- **Affected files:** `src/lobby_attendance/api/auth.py:19-91`, `src/lobby_attendance/api/app.py:323-345`, `README.md` token/startup examples.
- **Precondition/reproduction:** Configure the admin or kiosk bearer token and replay the same long-lived value. The boundary compares one configured secret and creates a fixed principal; there is no expiry, revocation, re-authentication, audience, replay protection, or enforced TLS boundary.
- **Impact:** Token theft/replay grants the configured privileges until rotation; shared credentials weaken attribution and individual revocation. Plain-HTTP deployment examples permit interception without an approved transport boundary.
- **Evidence:** Tests cover constant-time comparison and missing-token denial, not production identity, expiry/revocation, or TLS enforcement.
- **P0-02 engineering remediation (2026-08-27):** A signed-session boundary (`SignedTokenBoundary`) now validates HMAC-SHA-256 signatures, issuer/audience, bounded lifetime, auth-time, token kind, role/site/subject claims, and enforces TLS in signed mode. Durable revocation, recent-auth enforcement, and rate limiting are implemented. The static `TokenBoundary` remains only for the executive demo and tests. **30 focused tests passed.**
- **Remaining:** Approved IdP/identity-gateway issuance, key custody, TLS termination/certificates, trusted-proxy review, edge abuse monitoring.
- **Owner:** Solutions Architect + Security/Platform.

### SEC-03 — Major (partially remediated) — Authorization is not effective per-subject or site-scoped RBAC
- **Affected files:** `src/lobby_attendance/api/auth.py:20-56`, `src/lobby_attendance/rbac.py`, `src/lobby_attendance/storage/repositories.py:65-84`, `src/lobby_attendance/api/app.py:303-320`.
- **Precondition/reproduction:** Assign a database role and authenticate with the configured admin token. `principal_for_request()` authorizes from globally configured token roles and a fixed subject; it does not load the authenticated subject's database assignments. Routes also lack a site-scope authorization predicate.
- **Impact:** Shared credentials can receive broad cross-domain privileges and cannot be individually revoked or reliably attributed; valid principals may access records outside an intended site.
- **Evidence:** Current tests prove configured-role default denial, but role rows are not the authentication/authorization source and no cross-subject/site policy exists.
- **P0-03 engineering remediation (2026-08-27):** Signed sessions now carry site scope (`site_ids`) and subject scope (`subject_ids`) claims that are validated at the API boundary. Protected routes reject tokens outside the configured site. User/event queries apply parameterized scope filters. Corrections cannot move records outside scope. Kiosk token-kind/role separation is enforced. Conflicting role combinations (enrollment + attendance, RBAC + enrollment, RBAC + attendance, RBAC + system operator) are rejected. **44 focused tests passed** including cross-subject denial, cross-site denial, and separation-of-duties rejection.
- **Remaining:** Approved IdP role/scope issuance, named-account separation, operational offboarding, access review, and signed deployment.
- **Owner:** Solutions Architect + Security/RBAC.

### SEC-04 — Major — Synchronization is not durable/authenticated by default and queue ownership is not fully enforced
- **Affected files:** `src/lobby_attendance/api/app.py:81-103`, `src/lobby_attendance/application/queue_sync.py`, `src/lobby_attendance/storage/repositories.py:245-344`.
- **Precondition/reproduction:** Start `create_app()` without an injected sink: it selects `InMemoryEventSink`, whose contents disappear on restart. `QueueRepository.set_state()` updates a queue row by ID without requiring the current lease owner.
- **Impact:** Offline events can be lost on restart; remote delivery/authentication/acknowledgement is unspecified; concurrent or compromised workers can cause incorrect state transitions or duplicates.
- **Evidence:** Queue fallback, retry, lease/reclaim, and audit tests run against SQLite plus an in-memory/failing test sink only. The sink protocol is not a durable remote implementation.
- **Remediation:** Deploy an authenticated durable sink with TLS, service identity, idempotency, durable acknowledgement, retry/rejection semantics, and audit. Add atomic owner/lease predicates and crash, replay, concurrent-worker, restart, and outage tests.
- **Owner:** Platform + Solutions Architect + Security.

### SEC-05 — Major (in progress) — Deletion does not propagate beyond active local SQLite rows
- **Affected files:** `src/lobby_attendance/application/retention.py`, `src/lobby_attendance/storage/repositories.py:347-410`, `src/lobby_attendance/storage/sqlite.py`, queue/sink deployment boundary.
- **Precondition/reproduction:** Run retention or de-enrollment cleanup, then inspect WAL files, backups, replicas, exports, or remote sink copies. The repository deletes local rows only and has no tombstone, remote-delete, backup lifecycle, or verification contract.
- **Impact:** Event and biometric-related metadata can remain accessible after retention/de-enrollment, conflicting with approved deletion obligations and increasing incident scope.
- **Evidence:** Local purge tests pass; no nonlocal storage or deletion propagation integration is present.
- **P0-04 engineering progress (2026-08-27):** Deletion-propagation manifest schema and repository are planned as part of the P0-04 encrypted-storage work. The manifest will create auditable records for each nonlocal copy that requires deletion, track request/completion status, and integrate with retention and de-enrollment operations. Implementation is pending.
- **Remediation:** Inventory copies and retention/legal holds; implement authenticated deletion/tombstone propagation, WAL/backup expiry, remote deletion, retry/reconciliation, and auditable completion/exception evidence.
- **Owner:** Privacy/Data Governance + Platform.

### SEC-06 — Major — Model integrity is local hash-checked but provenance and governance are incomplete
- **Affected files:** `src/lobby_attendance/vision/opencv.py:20-88`, `src/lobby_attendance/config.py`, `README.md`, `tests/test_phase2_pipeline.py`.
- **Precondition/reproduction:** Configure a model path and optional SHA-256. The adapter checks path/regular-file/digest properties, but there is no signature verification, trusted provenance/distribution record, license validation, permission policy, signed rollback metadata, or model registry.
- **Impact:** A compromised provisioning/operator path can supply an untrusted model; behavior, licensing, and rollback cannot be independently trusted. QA-010 metadata does not establish model provenance.
- **Evidence:** Path/digest tests pass, but no signed distribution or approved model-evaluation artifact exists.
- **Remediation:** Establish signed model provenance and trusted distribution, license/permission review, controlled rollback, model/config audit, and an approved evaluation set with documented limitations.
- **Owner:** ML + Platform + Security/QA.

### SEC-07 — Major — Raspberry Pi, camera, model, liveness, and performance evidence is absent
- **Affected files:** `README.md`, `src/lobby_attendance/vision/opencv.py`, `tests/test_phase2_pipeline.py`.
- **Precondition/reproduction:** No Raspberry Pi 4 target, supported webcam, production model, representative lawful evaluation fixture, or measured deployment artifact is available in the workspace.
- **Impact:** False accepts/rejects, presentation attacks, camera/permission failures, thermal/power-loss recovery, and the proposed under-2-second p95 decision target are unknown. Synthetic mock tests cannot support a production biometric decision.
- **Evidence:** README and tests identify synthetic deterministic vision and mocked camera/model paths; no target-hardware evaluation is supplied.
- **Remediation:** Run approved exact-device/webcam/lighting evaluation covering FAR/FRR, liveness limitations, threshold rationale, p95 latency, watchdog/power/network recovery, fail-closed behavior, and rollback criteria.
- **Owner:** ML + QA + Platform.

### SEC-08 — Major — Privacy/legal approval and lawful-basis decision remain unresolved
- **Affected files:** `src/lobby_attendance/config.py`, `src/lobby_attendance/application/enrollment.py`, `.env.example`, `README.md`.
- **Precondition/reproduction:** Set `LOBBY_ATTENDANCE_COMPLIANCE_APPROVED=true`; the application permits activation after the local lifecycle check, but the flag does not verify an authorized privacy/legal decision or deployment evidence. No notice/consent/non-biometric-alternative implementation or approval artifact is present.
- **Impact:** Production activation could occur without jurisdiction-specific lawful-basis, employment/privacy, notice/consent, alternative, retention, or impact-assessment decisions. QA-010 adds a technical prerequisite but does not cure this governance risk.
- **Evidence:** Tests prove the technical compliance gate is false-by-default and that both activation and recognition submission are denied and audited when approval is absent; product/privacy guidance marks the no-notice/no-consent/no-alternative position provisional and no approval artifact is available.
- **Remediation:** Obtain documented privacy/legal owner approval and impact/threat assessments; implement any required notice, consent/lawful-basis, alternative, retention/deletion, and worker-rights controls before production activation. Bind deployment approval to auditable evidence rather than an unverified environment flag.
- **Owner:** Privacy/Legal + Product, with Security.

## 5. Handoff contract

- **status:** `NEEDS_REWORK`
- **objective:** Review the current MVP after QA-010 remediation and determine the local activation security result without granting production approval.
- **acceptance_criteria:** Confirm compliance approval plus current protected-template lifecycle enforcement; verify stable safe denial, suspended status, and audit evidence; run relevant tests/checks; identify regressions; preserve unresolved production blockers with severity, evidence, remediation, and owner.
- **artifacts:** `docs/security-review.md`; QA-010 implementation in `src/lobby_attendance/application/enrollment.py`, `src/lobby_attendance/storage/repositories.py`, and `src/lobby_attendance/api/app.py`; regression tests in `tests/test_phase3_api.py`.
- **decisions:** QA-010 is closed at the local code boundary. The local gate passes for this remediation. Production remains blocked by SEC-01 through SEC-08, especially effective subject/site RBAC, encryption/key management, authenticated durable synchronization, deletion propagation, model/device evaluation, and privacy/legal approval.
- **open_questions:** Which approved IdP and site-scoped RBAC model will be deployed? What encryption/key/backup/deletion design protects SQLite/WAL/queue and copies? Which durable authenticated sink and lease protocol will be used? What signed model provenance and exact Pi/webcam evaluation will be accepted? What privacy/legal decision governs notice, lawful basis, and a non-biometric alternative?
- **findings:** No new QA-010 regression found. SEC-01 Major encryption/key management; SEC-02 Major static authentication/TLS; SEC-03 Major effective subject/site RBAC; SEC-04 Major authenticated durable synchronization/lease ownership; SEC-05 Major deletion propagation; SEC-06 Major model provenance; SEC-07 Major model/device/liveness evaluation; SEC-08 Major privacy/legal approval. Owners and evidence are above.
- **validation:** Current local validation: `python -m pytest -q` — **PASS**, 70 passed in 4.25s; targeted P0-01 runtime suite — **PASS**, 26 passed; `python -m compileall -q src tests` — **PASS**; `python -m pip check` — **PASS**; diagnostics and `git diff --check` — **PASS**. Physical Raspberry Pi/webcam/model, encryption, key management, SSO/TLS, effective RBAC, durable sink, deletion propagation, signed model distribution, liveness, and privacy/legal approval evidence were not available and remain unresolved.
- **next_action:** Remediation owners must provide design and evidence for SEC-01–SEC-08. Security should re-review the deployment controls; QA should rerun the full suite and target hardware/remote-sink/deletion/model/security evidence. No production release until all major findings are remediated or explicitly accepted by the authorized risk owner under the required release process.

## Documentation decision

`docs/security-review.md` required an update: it records the QA-010 closure plus the preserved production blockers. `docs/qa-report.md` has been reconciled by the QA validator and now records the local code gate as `PASS`, QA-010 as closed, and the overall production decision as `NEEDS_REWORK`.


## Executive-demo security addendum — 2026-08-27

The executive-demo vertical slice was reviewed as a controlled local demonstration, not a production security approval. It adds an explicit opt-in mode, protected server-camera enrollment/status/reset routes, a thread-safe in-memory normalized crop matcher, bounded capture, mixed-invalid-window rejection, and safe UI/API output. It does not remove the prior production findings SEC-01 through SEC-08.

Additional demo-specific controls:

- Actual normalized matcher arrays remain in process memory and are not serialized, logged, returned, or stored in SQLite. SQLite receives only server-derived lifecycle metadata and ordinary event/audit fields.
- Metadata-only template registration cannot activate or match a demo user. Activation requires the in-memory registry plus the existing compliance gate.
- Suspension and de-enrollment remove the in-memory matcher entry. Restart loses all demo templates.
- Enrollment is bounded and single-flight; capture uses the same server-attached camera/detector path as recognition and releases the camera in failure paths.
- Demo responses expose no crops, arrays, scores, thresholds, hashes, or liveness internals. The admin UI does not upload browser frames or persist the token in browser storage.
- Any mixed recognition window containing unavailable, no-face, multiple-face, low-quality, liveness-failed, unknown, or ambiguous samples is rejected before event submission.

Demo-specific residual risks:

- The normalized crop matcher is a demonstration heuristic, not an evaluated biometric recognition model and not identity proof.
- `demo_presence_liveness_checker` verifies bounded in-frame presence only; it is not presentation-attack resistance.
- In-memory enrollment is exposed to process memory/core/swap risks and is lost on restart; no approved encryption/key-management design was added.
- The demo still uses the prototype static bearer-token boundary, ordinary SQLite/WAL, and the existing in-memory synchronization sink.
- No representative consented evaluation set, target Pi/webcam benchmark, replay/print attack test, threshold calibration, signed model governance, or browser accessibility evidence exists.

Security decision: **conditionally acceptable for a supervised, consenting, local executive demonstration only; NEEDS_REWORK for any pilot, workplace decision, or production deployment.** The prior unresolved privacy/legal, authentication/RBAC, encryption, durable synchronization, deletion propagation, model/device, correction-retention, queue-ownership, and SQLite-threading findings remain open.


### Demo remediation note — 2026-08-27

The final demo remediation adds an admin status element/null-safe status writer, serializes enrollment and kiosk camera interactions behind one shared in-process lock, disables local queue fallback for executive-demo recognition storage failures, and makes demo reset a lifecycle revocation that suspends the user, retires active demo metadata, removes the RAM matcher entry, preserves event history, audits the reset, and requires an explicit `user_id` after restart when RAM state cannot identify the enrollment. These changes narrow the supervised-demo boundary only; they do not resolve cross-process synchronization, cooldown/replay, queue lease ownership, keyed/encrypted template metadata, production authentication/RBAC, or target-device/PAD evidence.


## P0-02 authentication remediation note — 2026-08-27

The P0-02 engineering remediation adds a signed-session boundary in `src/lobby_attendance/api/auth.py`. Signed sessions validate an issuer, audience, HMAC signature, token kind, role claims, issued-at/expiry lifetime, authentication time, token ID, and bounded site/subject scope claims. Sensitive mutations require recent authentication; signed requests require TLS; token IDs can be durably revoked in `auth_token_revocations`; and a bounded process-local failed-auth limiter returns a safe `429` response without returning token details. The existing static `TokenBoundary` remains only for compatibility with the supervised demo and tests.

Focused P0-02 validation: `30 passed` across signed-session, TLS, expiry, recent-auth, token-kind, revocation, environment configuration, rate-limiting, API regression, and demo compatibility tests. This is local engineering evidence only. The pilot gate remains open pending approved IdP/identity-gateway issuance, secret/key custody, TLS termination and certificate operations, account lifecycle/revocation integration, trusted-proxy review, and edge-level abuse monitoring.


## P0-03 RBAC/scope remediation note — 2026-08-27

The P0-03 engineering remediation makes signed site and subject claims effective at the API boundary. Signed sessions require a site scope and admin subject scope; protected routes reject tokens outside the configured site; user and event queries apply parameterized scope filters; corrections cannot move an event outside the authorized scope; and conflicting operational/RBAC role combinations are rejected. Kiosk sessions remain limited to the kiosk role and token kind. See `docs/pilot-rbac-scope-design.md`.

Focused scope evidence is included in `tests/test_pilot_auth.py` for cross-subject denial, cross-site denial, and separation-of-duties role rejection. The pilot gate remains open pending approved IdP role/scope issuance, named-account separation, access review, offboarding, and operational revocation. Legacy static-token mode remains demo/test-only.
