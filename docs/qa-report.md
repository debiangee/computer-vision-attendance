# QA / Release-Gate Report — Lobby Attendance MVP

**Validation date:** 2026-08-27 17:43 +08:00 (environment clock)  
**Baseline:** Current working tree after the QA-010 enrollment-lifecycle remediation. QA made no production-source or test changes; this report is the QA artifact update.  
**Environment:** Windows 11 host, Python 3.12.10, pytest 8.3.4.  
**Scope:** Existing REQ-001 through REQ-015 acceptance criteria, product/privacy-security/engineering guidance, current source/tests, and the prior QA report.

## Release decisions

**Local MVP code gate — status: `PASS`**  
**reentry: `false` for QA-010**

QA-010 is resolved at the application boundary. With compliance approval and no template metadata, activation returns stable HTTP `409` (`template-lifecycle-incomplete`), leaves the user suspended, and records a denied `enrollment:activate` audit event. With valid active/versioned protected-template metadata, activation returns HTTP `200` and the user becomes active. The focused activation tests and full local suite pass.

This is a local code-gate decision only. It is **not** a production approval and does not establish recognition accuracy, hardware readiness, privacy/legal approval, secure deployment, or production identity assurance.

**Overall / production release decision — status: `NEEDS_REWORK`**  
**reentry: `true` for unresolved production/deployment findings**

Production remains blocked by unresolved authentication and subject/site-scoped RBAC, encryption/key management, secure transport, durable authenticated synchronization, deletion propagation, target Raspberry Pi/webcam/model/liveness evaluation, browser/device recovery evidence, and privacy/legal governance. These limitations remain explicitly open below.

## Acceptance-criteria matrix

| Criterion | Status | Evidence / check | Result and limitation |
|---|---|---|---|
| REQ-001 compliance mode and privacy/legal gate | **PASS locally; production evidence missing** | Compliance-denied activation test and approved-health test pass. QA-010 explicit run confirms the application gate is enabled only in approved test configuration. | Local fail-closed behavior passes. Privacy/legal owner approval, PIA, lawful-basis/notice decision, and the provisional no-notice/no-consent/no-alternative decision remain production blockers (QA-011). |
| REQ-002 RBAC-controlled enrollment and lifecycle | **PASS locally for tested lifecycle; production partial** | `tests/test_phase3_api.py` activation/template tests and explicit negative/positive API run pass. QA-010 no-template activation is `409`, persisted status `suspended`, audit outcome `denied`; valid template activation is `200`, persisted status `active`, audit outcome `success`. | The protected-template lifecycle invariant is enforced. Production subject identity, role revocation, separation of duties, and site/data scope are not implemented by the static-token prototype (QA-002). |
| REQ-003 bounded ephemeral capture and camera fail-closed | **PASS locally; hardware skipped** | Phase-2 pipeline/OpenCV tests pass; capture is bounded to the configured sample window and releases the capture on failure. | No raw frame persistence path was found. Actual Raspberry Pi camera permissions, device initialization, and physical failure recovery were not available. |
| REQ-004 stable safe recognition | **PASS locally; evaluation skipped** | Policy and pipeline tests pass for stable identity, liveness, quality, ambiguity, inactive users, and 3-of-5 sampling behavior. | No representative production model/liveness evaluation or threshold calibration was available. |
| REQ-005 recognized-person encounter semantics | **PASS locally** | Pipeline tests pass for one eligible interaction and `RECOGNIZED_ENCOUNTER` / `face-encounter` event semantics. | The implementation does not infer Time In/Out, shifts, payroll, holidays, or sessions. |
| REQ-006 event data and idempotency | **PASS locally; deployment protection skipped** | Storage/API tests pass for UTC/server-owned time, event source, site/camera, model/policy versions, idempotency, correlation, storage state, and bounded audit metadata. | Encryption, tamper protection, backup protection, and durable remote delivery remain unverified. |
| REQ-007 cooldown and suppression | **PASS locally** | Cooldown and clock-boundary tests pass; the original event is retained and suppression is audited. | The five-minute value is configurable and still requires owner confirmation before production. |
| REQ-008 administrative correction | **PASS locally; deployment identity scope skipped** | Correction tests pass for role protection, bounded input, immutable original event, before/after history, reason, actor, timestamp, and audit. | Strong re-authentication and production subject/site scope remain open. |
| REQ-009 access control and data protection | **PARTIAL — engineering progress** | Local default-deny route tests pass. P0-02 adds signed-session authentication with expiry/revocation/TLS/re-auth (30 tests). P0-03 adds effective site/subject RBAC with scope filters and separation-of-duties (44 tests). P0-04 adds AES-GCM encrypted storage (in progress). | Production SSO/IdP issuance, key custody, backup encryption, and remote deletion propagation remain external gates (QA-002/QA-003). |
| REQ-010 retention and deletion | **PARTIAL** | Local retention purge and de-enrollment cleanup tests pass for events, suppressions, queue rows, and retired template metadata. | Backup, WAL, replica, export, and remote-sink deletion propagation is not implemented or verified (QA-006). |
| REQ-011 offline queue and synchronization | **PASS locally; production sink/encryption skipped** | Queue lease/reclaim/retry/expiry, minimal payload, idempotency, audit, and failure-state tests pass. | The default in-memory sink is not a durable authenticated remote sink; queue-at-rest encryption and crash/restart delivery evidence are missing (QA-003/QA-005). |
| REQ-012 kiosk/operator states | **PASS locally; browser skipped** | API/static UI tests and startup/page smoke cover neutral output, queue-full, synchronization-failure, and action-required states without sensitive diagnostics. | Browser camera permissions, accessibility, and live recovery were not exercised. |
| REQ-013 degraded operation | **PARTIAL** | Camera/model/storage failure paths fail closed in local adapter/API tests. | Pi power-loss recovery, network recovery, encrypted-storage integrity, watchdog behavior, and real remote database failure were not verified. |
| REQ-014 audit and observability | **PASS locally; deployment assurance skipped** | Enrollment/compliance, event/suppression, correction/export, queue, retention, and authorization-denial audit tests pass with bounded records and actor attribution. | Production identity assurance, model/configuration governance, tamper monitoring, and operational alert delivery remain open. |
| REQ-015 recognition quality/performance | **SKIPPED / RELEASE BLOCKER** | No target Raspberry Pi 4/webcam/model evaluation set or p95 measurement was available. | FAR/FRR, liveness presentation-attack resistance, environmental limitations, threshold calibration, rollback, and under-2-second p95 evidence are missing (QA-007). |

## QA-010 evidence

The exact explicit validation script created isolated SQLite stores and used compliance-approved test configuration with an enrollment-administrator token.

**Negative case — compliance approved, no template metadata:**

- User creation: HTTP `201`.
- Template registration: not performed; `has_active_versioned_template: false`.
- Activation: HTTP `409`.
- Response: `{"error":"template-lifecycle-incomplete","message":"biometric activation requires a protected template"}`.
- Persisted user status: `suspended`.
- Audit: action `enrollment:activate`, actor `configured-admin`, outcome `denied`, metadata reason `template-lifecycle-incomplete`.

**Positive case — valid active/versioned protected-template metadata:**

- User creation: HTTP `201`.
- Template registration: HTTP `201` with model version `mock-1`, template version `1`, and nonblank protected hash.
- `has_active_versioned_template: true`.
- Activation: HTTP `200`.
- Response: `{"status":"active","user_id":"qa010-valid-template"}`.
- Persisted user status: `active`.
- Audit: action `enrollment:activate`, actor `configured-admin`, outcome `success`.

The regression test `test_compliance_approved_activation_requires_protected_template` covers the negative branch, and `test_compliance_approved_activation_and_health_state` covers the positive branch.

## Findings and remediation matrix

| ID / severity | Failed criterion | Evidence / expected behavior | Actual behavior / owner | Validation required |
|---|---|---|---|---|
| **QA-002 Major** | REQ-002, REQ-009 | Authorization must use authenticated subjects with revocation, separation of duties, and site/data scope. | **P0-02/P0-03 engineering remediation applied.** Signed sessions validate HMAC signatures, enforce expiry/revocation/TLS/re-auth, carry site/subject scopes, reject cross-site/cross-subject access, separate kiosk/admin tokens, and reject conflicting roles. Static `TokenBoundary` remains demo/test-only. **External gates remain:** approved IdP issuance, key custody, named-account separation, offboarding, and access review. **Owner:** Solutions Architect + Security/RBAC. | Approved IdP/service identity deployment, operational revocation, and signed deployment evidence. |
| **QA-003 Major** | REQ-009, REQ-011 | Templates, events, queue, backups, and secrets require approved authenticated encryption and key controls. | **P0-04 local engineering progress applied.** AES-GCM encrypted in-memory SQLite serialization is wired through `create_app()`; encrypted request commits, owned-store shutdown, fail-closed configuration, no-plaintext-WAL behavior, round-trip/wrong-key/plaintext-rejection/rollback tests, and `cryptography==50.0.0` are covered. Remaining: deletion manifests, key custody, backup encryption, remote propagation, recovery, and queue-at-rest/deployment controls. **Owner:** Security + Platform. | Reviewed encryption/key/ACL design plus tamper, recovery, backup, and queue-at-rest tests. |
| **QA-005 Major** | REQ-011 | Synchronization must be durable, authenticated, TLS-protected, retry-safe, and idempotent. | Default `InMemoryEventSink` loses delivery on process restart and is not a production remote contract. **Owner:** Platform + Solutions Architect + Security. | Durable sink, TLS/authentication/replay controls, crash/restart/duplicate/rejection tests, and deployment evidence. |
| **QA-006 Major** | REQ-010 | Deletion must propagate across applicable active, queue, WAL, backup, replica, export, and remote copies. | Only local cleanup is implemented/verified. **Owner:** Privacy/Data Governance + Platform. | Retention/legal-hold policy and propagation/recovery evidence for every copy. |
| **QA-007 Major** | REQ-015 | Target-device accuracy, liveness, threshold, latency, and rollback limits must be measured. | No Raspberry Pi/webcam/model evaluation artifact or p95 measurement is available. **Owner:** ML + QA + Platform. | Approved representative evaluation and target-hardware performance report. |
| **QA-011 Major** | REQ-001 and production privacy gate | Privacy/legal owner must approve or change the provisional notice/consent/lawful-basis/alternative position. | No PIA, jurisdiction-specific decision, or authorized owner evidence was supplied. **Owner:** Privacy/Legal + Product. | Signed decision, PIA/risk assessment, and implementation evidence for any required notice, consent/lawful basis, or alternative. |

**QA-010 is closed locally.** No QA-010 remediation re-entry is required after this run. The previous report's QA-010 finding and local `NEEDS_REWORK` decision were stale and have been corrected in this report.

## Checks run and exact results

1. `python -m pytest tests/test_phase3_api.py -k "activation or template" -q` — **PASS**, `3 passed, 16 deselected in 0.51s`.
2. Explicit QA-010 negative/positive API script — **PASS**, outputs and persisted/audit evidence recorded above.
3. `python -m pytest -q` — **PASS**, `70 passed in 4.25s`.
4. `python -m pytest tests/test_phase2_pipeline.py tests/test_policy.py tests/test_config_rbac.py -q` — **PASS**, `22 passed in 0.81s`.
5. `python -m compileall -q src tests` — **PASS**, exit code 0.
6. `python -m pip check` — **PASS**, `No broken requirements found.`
7. `python -m flask --app lobby_attendance.api:create_app routes` — **PASS**, route discovery includes activation/template, correction/export, queue operations, audit, health, kiosk, and admin routes.
8. Startup/page smoke using an in-memory database — **PASS**, `{'health': 200, 'health_status': 'ready', 'kiosk': 200, 'admin': 200}`.
9. QA inspected the existing `docs/qa-report.md`, confirmed its QA-010 failure text was stale, and updated it with the current evidence. No source or test files were changed by QA.

## Skipped / untestable checks and environment assumptions

- No Raspberry Pi 4, target OS, supported webcam, physical kiosk, target lighting/distance setup, thermal/power/watchdog setup, or production network was available. Camera permission/device initialization, p95 latency, and power-loss recovery remain skipped.
- No approved representative/lawfully sourced biometric evaluation set or production model was available. FAR/FRR, demographic/environmental performance, liveness presentation-attack resistance, threshold calibration, and rollback remain skipped.
- No authenticated durable remote sink/database, TLS/reverse proxy, SSO/IdP, encrypted filesystem/database, key-management service, backup/replica system, or queue-integrity monitor was available. These deployment controls remain untestable and release-blocking.
- No PIA, threat-model sign-off, employment/privacy/legal approval, retention/backup deletion verification, or authorized owner decision for the provisional no-notice/no-consent/no-alternative position was supplied.
- Browser UI automation and accessibility testing were unavailable. Flask page/static contract checks are not browser-level evidence.
- The mock vision provider is synthetic and deterministic; passing tests are not production recognition-accuracy or liveness evidence.

## Handoff contract

- **status:** `NEEDS_REWORK` for the overall/production release gate; local MVP code gate is `PASS`.
- **reentry:** `true` for the unresolved production/deployment findings; `false` for QA-010.
- **objective:** Validate the current Raspberry Pi lobby-attendance MVP against the established requirements and local implementation checks, with explicit QA-010 lifecycle evidence.
- **acceptance_criteria:** REQ-001 through REQ-015 are mapped above; local QA-010 negative/positive behavior, full suite, focused suites, compile/configuration, route, and startup checks are evidenced; skipped production checks and blockers are explicit.
- **artifacts:** `docs/qa-report.md`; no QA changes to production source or tests.
- **decisions:** QA-010 passes. Local policy, stable matching, inactive-user rejection, cooldown/idempotency, bounded capture, safe failure, queue lifecycle, retention/de-enrollment, compliance gate, correction/export immutability/redaction, audit/operator states, neutral kiosk, health/startup, and model path/digest checks remain locally passing as covered by the suite. Production is not approved.
- **open_questions:** Which approved IdP and subject/site-scoped RBAC model will replace shared tokens? What encryption/key/backup/deletion design will protect SQLite/WAL/queue and replicas? Which durable authenticated sink will be deployed? What privacy/legal decision applies? What exact Pi/webcam/model/evaluation target will be accepted?
- **findings:** QA-002, QA-003, QA-005, QA-006, QA-007, and QA-011 remain Major production blockers with owners and required validation above. QA-010 is closed.
- **validation:** Exact commands and results are listed above; all available local automated checks passed.
- **next_action:** Solutions Architect routes the remaining production blockers to Security, Privacy/Legal, Platform, ML, and RBAC owners. After those controls and target-device evidence are supplied, QA must rerun the deployment/release matrix. Do not treat this local PASS as production readiness.


## Executive-demo vertical-slice addendum — 2026-08-27

The supervised executive-demo slice is locally implemented and covered by additional tests. The local functional/code gate remains **PASS for the demo contract**, while the overall production release remains **NEEDS_REWORK**.

New local evidence:

- `python -m pytest -q` — **PASS**, 64 tests.
- `python -m compileall -q src tests` — **PASS**.
- `node --check src/lobby_attendance/ui/static/admin.js` — **PASS**.
- `python -m pip check` — **PASS**, no broken requirements.
- Matcher tests cover normalized crops, finite/shape/variance validation, unknown/ambiguous matches, server-derived hash, removal, and metadata-only non-matchability.
- Provider/API tests cover bounded server-camera enrollment, camera/liveness failure, capture release, protected demo routes, safe responses, lifecycle reset, restart-time reset-all refusal with explicit-user recovery and audit, no queue fallback on demo storage failure, restart-empty matcher state, and mixed-invalid-window rejection.
- Admin UI integration keeps the token in page memory, uses no browser frame upload, provides one-flight enrollment/reset controls, renders only allowlisted safe status fields, and tolerates absent status elements without throwing.

The demo can create a real in-memory local template from the server-attached webcam and use it for the existing stable 3-of-5 encounter pipeline. Enrollment and kiosk recognition are serialized by one in-process camera lock; this is not cross-process protection. This is not evidence of recognition accuracy, liveness/PAD performance, Raspberry Pi compatibility, or a production biometric control. Enrollment disappears on process restart. The local normalized crop matcher is sensitive to pose, lighting, camera/crop changes, and lookalikes; the liveness callback is only a presence heuristic.

The following remain release blockers and are not changed by this demo slice: privacy/legal approval and lawful-basis/notice/alternative decision; static-token authentication and effective subject/site RBAC; plaintext SQLite/WAL/queue and key management; non-durable in-memory synchronization and queue lease ownership; correction/de-enrollment retention edge cases; deletion propagation; signed model provenance; real Raspberry Pi/webcam/model/liveness/latency evaluation; browser accessibility/device recovery; and the existing SQLite threading limitation.


## P0 engineering progress summary — 2026-08-27

The following P0 engineering controls have been implemented since the original QA run:

| P0 Item | Status | Test Evidence | Key Files |
|---|---|---|---|
| P0-01 Privacy/legal package | Prepared for authorized review / external approval pending | 26 targeted runtime tests; full local suite 70 passed | `docs/pilot-privacy-and-data-governance.md` |
| P0-02 Authentication/TLS/revocation | Engineering complete | 30 focused tests | `src/lobby_attendance/api/auth.py`, `docs/pilot-authentication-design.md` |
| P0-03 RBAC/scope/separation | Engineering complete | 44 focused tests | `src/lobby_attendance/api/auth.py`, `src/lobby_attendance/rbac.py`, `docs/pilot-rbac-scope-design.md` |
| P0-04 Encrypted storage/deletion | In progress | Pending | `src/lobby_attendance/storage/sqlite.py`, `src/lobby_attendance/config.py` |
| P0-05 Recognition/PAD evaluation | Not started | N/A | Blocked on physical hardware |

**Note:** The static `TokenBoundary` is retained for the executive demo and tests only. All pilot-mode protected routes use `SignedTokenBoundary`. The prior QA-002 finding about static tokens is partially remediated by P0-02/P0-03 engineering work but remains open pending external IdP deployment.

**Current validation reconciliation (2026-08-27):** `python -m pytest -q` — **PASS**, `70 passed in 4.25s`; `python -m compileall -q src tests` — **PASS**; `python -m pip check` — **PASS**; diagnostics and `git diff --check` — **PASS**. Earlier 47/57 full-suite counts in this historical report are superseded by the current run. These local results do not establish privacy/legal approval, participant rights, fallback approval, deletion propagation, target-device evidence, or pilot release.
