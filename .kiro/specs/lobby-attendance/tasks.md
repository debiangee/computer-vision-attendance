# Lobby Computer-Vision Attendance Implementation Tasks

**Execution rule:** Do not skip Task 1. Production-facing implementation is blocked until the business/privacy decision gate is approved. Tasks may run in dependency waves only when they do not share write targets. Every completed task must report changed files, acceptance evidence, validation commands/results, unresolved risks, and next action.

## Phase 0 — Decisions and foundations

- [ ] **Task 1 — Confirm automatic-event, RBAC, and privacy rules**
  - **Owner:** Solutions Architect + Business Analyst
  - **Depends on:** None
  - **Outcome:** Approved authorized population and sites, RBAC owners/scopes, automatic recognized-person event meaning, stable-frame rule, cooldown, UTC/site timezone, three-month retention proposal, queue limits, Raspberry Pi hardware, performance target, database boundary, and the legal/privacy decision on no notice/consent/alternative.
  - **Acceptance:** Each decision is approved, assigned, or explicitly marked pilot-only. No implementation task hides an unresolved rule. The no-notice/no-consent/no-alternative position is explicitly accepted by the responsible privacy/legal owner or is converted into an implementation requirement.

- [ ] **Task 2 — Validate Raspberry Pi 4 and webcam runtime**
  - **Owner:** Solutions Architect + DevOps/Infra
  - **Depends on:** Task 1
  - **Outcome:** Architecture decision record for Raspberry Pi OS/runtime, webcam, resolution/frame rate, thermal/power, local process model, database topology, admin access, packaging, and supported operating conditions.
  - **Acceptance:** A clean device can capture frames, run a representative model benchmark, restart safely, and expose health status without downloading arbitrary runtime code.

- [ ] **Task 3 — Create threat model and privacy data-flow assessment**
  - **Owner:** Security/Code Review + Solutions Architect
  - **Depends on:** Task 1, Task 2
  - **Outcome:** Threat model, trust boundaries, data inventory, RBAC matrix, retention/deletion plan, local-queue risk assessment, physical-device risks, incident assumptions, and privacy/legal review inputs.
  - **Acceptance:** Frames, templates, events, queue items, logs, backups, exports, and deletion paths are explicit; no high-impact risk is unowned.

- [ ] **Task 4 — Establish repository skeleton and delivery checks**
  - **Owner:** DevOps/Infra
  - **Depends on:** Task 2
  - **Outcome:** Minimal application structure, pinned dependency/model management, configuration strategy, local development instructions, formatting/lint/type/test commands, secret handling, and Pi packaging baseline.
  - **Acceptance:** A clean checkout/device can run documented checks without secrets or arbitrary runtime model downloads.

## Phase 1 — Domain, RBAC, and event policy

- [ ] **Task 5 — Implement domain model and migrations**
  - **Owner:** Backend/API Developer
  - **Depends on:** Task 1, Task 4
  - **Outcome:** Person, authorization/compliance state, biometric template metadata, recognition event, suppression/audit event, correction, policy configuration, RBAC assignment, and local queue metadata models.
  - **Acceptance:** Constraints prevent invalid lifecycle states and duplicate identifiers; event timestamps are UTC; queue state is recoverable; sensitive fields have an approved protection strategy; migration and rollback are tested.

- [ ] **Task 6 — Implement RBAC and administrator authorization**
  - **Owner:** Backend/API Developer + Security/Code Review
  - **Depends on:** Task 1, Task 5
  - **Outcome:** Kiosk Service, Enrollment Administrator, Attendance Administrator, Auditor, System Operator, and RBAC Administrator roles with least-privilege site/data scopes.
  - **Acceptance:** Every sensitive operation is denied by default; role escalation and cross-site access tests fail safely; grants/revokes and administrator actions are audited; kiosk service cannot administer or export.

- [ ] **Task 7 — Implement deterministic encounter policy engine**
  - **Owner:** Backend/API Developer
  - **Depends on:** Task 1, Task 5
  - **Outcome:** Pure/testable policy module for stable recognition, liveness/quality acceptance, five-minute configurable cooldown, UTC/site timezone, idempotency, event metadata, queue decision, and safe rejection. It must not model Time In/Time Out or sessions.
  - **Acceptance:** Unit tests cover 3-of-5 stable match, liveness/quality failures, unknown/multiple faces, cooldown suppression, retries, event expiry, timezone conversion, queue-full rejection, and no camera dependency.

- [ ] **Task 8 — Define versioned recognition, liveness, and stable-match interfaces**
  - **Owner:** Backend/API Developer + Security/Code Review
  - **Depends on:** Task 2, Task 3, Task 7
  - **Outcome:** Replaceable contracts for capture observations, frame sampling, recognition/liveness results, stable-match aggregation, model/version metadata, thresholds, expiration, and safe rejection.
  - **Acceptance:** Interfaces do not expose templates to UI callers, never create events directly, support unavailable states, and carry audit correlation/model version.

## Phase 2 — Computer vision and enrollment

- [ ] **Task 9 — Implement bounded webcam capture adapter**
  - **Owner:** Backend/API Developer or Frontend/UI Developer, per selected runtime
  - **Depends on:** Task 2, Task 4, Task 8
  - **Outcome:** Permission-aware Raspberry Pi webcam capture with configured resolution/frame rate, bounded sampling, timeout, frame disposal, and health reporting.
  - **Acceptance:** Camera unavailable, permission denied, timeout, no face, and multiple-face states are testable; frames are discarded after the interaction; Pi resource use is measured.

- [ ] **Task 10 — Integrate recognition, liveness, and stable-frame aggregation**
  - **Owner:** Backend/API Developer + Security/Code Review
  - **Depends on:** Task 3, Task 8, Task 9
  - **Outcome:** Pinned, licensed, provenance-documented model integration with conservative thresholds, liveness, quality checks, 3-of-5 starting stability rule, and safe unknown/ambiguous outcomes.
  - **Acceptance:** Evaluation runs on approved representative data and actual Pi/webcam conditions; false-acceptance/false-rejection limits, model checksum/version, threshold rationale, liveness limitations, and fail-closed criteria are documented.

- [ ] **Task 11 — Implement protected enrollment lifecycle**
  - **Owner:** Backend/API Developer + Frontend/UI Developer
  - **Depends on:** Task 1, Task 3, Task 5, Task 6, Task 10
  - **Outcome:** RBAC-protected authorization verification, compliance gate, controlled enrollment capture, quality checks, template creation/versioning, activation, suspension, replacement, and deletion.
  - **Acceptance:** Unauthorized/suspended/de-enrolled people cannot activate or match; unresolved compliance requirements block activation; templates are protected; every lifecycle action is audited.

## Phase 3 — Automatic kiosk events and storage

- [ ] **Task 12 — Implement local event writer and encrypted queue**
  - **Owner:** Backend/API Developer + DevOps/Infra
  - **Depends on:** Task 5, Task 7, Task 8
  - **Outcome:** Transactional event writes, minimum encrypted local queue payload, bounded capacity/age, integrity checks, idempotency keys, retry state, and safe queue-full behavior.
  - **Acceptance:** Database outage queues without raw frames/templates; reconnect synchronization cannot duplicate events; queue corruption/full/storage failure fails closed and alerts an operator.

- [ ] **Task 13 — Implement recognition-event service/API**
  - **Owner:** Backend/API Developer
  - **Depends on:** Task 5, Task 6, Task 7, Task 12
  - **Outcome:** Protected service boundary for event submission, cooldown policy, idempotent persistence/queueing, synchronization, health/readiness, and kiosk-safe responses.
  - **Acceptance:** Only eligible observations create events; unknown/unsafe observations cannot write; unauthorized calls fail; retries are safe; audit metadata and storage state are persisted.

- [ ] **Task 14 — Implement neutral automatic-event kiosk experience**
  - **Owner:** Frontend/UI Developer
  - **Depends on:** Task 9, Task 10, Task 13
  - **Outcome:** Neutral lobby camera screen with bounded capture, minimal recorded/already-recorded/queued results, safe failure states, operator attention state, and no Time In/Time Out controls.
  - **Acceptance:** No background auto-identification outside bounded interactions or one event per frame; raw confidence/templates are never shown; camera, unknown, liveness, duplicate, queue, and storage states are reachable and tested.

- [ ] **Task 15 — Implement administrator correction, reports, export, and retention**
  - **Owner:** Backend/API Developer + Frontend/UI Developer
  - **Depends on:** Task 1, Task 5, Task 6, Task 13
  - **Outcome:** RBAC-protected event review/correction, approved reports/exports, three-month configurable retention, deletion verification across database/queue/backups/replicas/exports, and audit views.
  - **Acceptance:** Original events remain auditable; raw templates are excluded from ordinary exports; retention/deletion is enforced and verified; access scope is tested.

## Phase 4 — Security, operations, and release

- [ ] **Task 16 — Harden Raspberry Pi and secure updates**
  - **Owner:** DevOps/Infra + Security/Code Review
  - **Depends on:** Task 2, Task 3, Task 4, Task 12, Task 13
  - **Outcome:** Physical/device hardening, disabled unused services, restricted administration, encrypted storage/queue, secret handling, watchdog, power-loss recovery, dependency/model scanning, update, and rollback controls.
  - **Acceptance:** Device recovery and queue integrity survive restart/power-loss drills; no secrets/biometric payloads appear in logs; model/dependency provenance and rollback are verified.

- [ ] **Task 17 — Add observability and operator runbook**
  - **Owner:** DevOps/Infra
  - **Depends on:** Task 12, Task 13, Task 14, Task 16
  - **Outcome:** Redacted logs, health checks, metrics, p95 latency measurement, queue alerts, camera/model/storage/network diagnostics, synchronization procedure, and operator support runbook.
  - **Acceptance:** Operators can distinguish failures; kiosk messaging remains privacy-safe; failure drills confirm no guessed or silently lost event; latency is measured on target Pi hardware.

- [ ] **Task 18 — Execute final security/privacy review, QA, and pilot**
  - **Owner:** Security/Code Review + QA/Validator + Solutions Architect
  - **Depends on:** Tasks 1–17 as applicable
  - **Outcome:** Requirements matrix, RBAC/security review, privacy/legal decision evidence, recognition evaluation, retention/deletion evidence, actual lobby pilot, accessibility check, and release recommendation.
  - **Acceptance:** Every confirmed requirement has evidence; the no-notice/no-consent/no-alternative position is approved or remediated; failures return `NEEDS_REWORK`; no unresolved blocker/major security or privacy finding remains.

- [ ] **Task 19 — Controlled rollout and operations handoff**
  - **Owner:** Solutions Architect + DevOps/Infra
  - **Depends on:** Task 18
  - **Outcome:** Versioned release, approved support ownership, RBAC administration process, rollback plan, retention/deletion procedure, device maintenance schedule, and staged pilot-to-production rollout.
  - **Acceptance:** Authorized approvers sign off on business rules, privacy/legal review, security, accuracy limitations, operations, and queue recovery; rollout can be reversed without uncontrolled biometric-data loss.
