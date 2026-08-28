---
inclusion: always
---

# Engineering and Delivery Standards

## Architecture principles
- Prefer a modular, local-first design with separable camera capture, face detection/recognition, liveness, attendance rules, persistence, kiosk UI, administration, and audit components.
- Keep recognition/model code behind a replaceable interface so model or vendor changes do not rewrite attendance policy.
- Keep attendance decisions deterministic and testable outside the camera loop. The camera layer should produce observations; the policy layer decides whether an event is eligible.
- Make site timezone, thresholds, cooldowns, retention, and feature flags explicit configuration with safe defaults and auditability.
- Design degraded operation deliberately: camera unavailable, model unavailable, database unavailable, network unavailable, and manual fallback must have defined behavior.
- Avoid storing images or biometric data in logs, test fixtures, screenshots, crash dumps, or sample commits.

## Implementation standards
- Inspect the repository and preserve existing conventions before adding frameworks or dependencies.
- Use pinned dependency versions and record model provenance, version, checksum, and license information.
- Validate all external input at system boundaries. Enforce authorization on the server/service boundary, not only in the UI.
- Use UTC for persisted timestamps and an explicit configured timezone for display and reporting.
- Make attendance event writes idempotent where possible and protect against duplicate submissions.
- Use migrations for schema changes and document rollback or data-compatibility behavior.
- Keep biometric enrollment, deletion, attendance correction, export, and administrative actions auditable.

## Testing standards
Test policy logic independently of computer-vision models. Include:
- unit tests for matching outcomes, thresholds, liveness outcomes, cooldowns, shifts, timezone conversion, and in/out state transitions;
- integration tests for persistence, authentication/authorization, audit records, retention/deletion, and API contracts;
- UI tests for every camera and fallback state, confirmation, accessibility behavior, and failure recovery;
- representative computer-vision evaluation sets with documented consent/provenance, avoiding real personal data in the repository;
- security tests for authorization boundaries, injection, replay/duplicate requests, secrets, and data exposure;
- deployment and recovery checks for camera, storage, model, and network failures.

## Delivery and handoffs
Every implementation task must state its acceptance criteria, changed files, validation commands, unresolved risks, and next action. Specialists must not silently change cross-domain contracts. The Solutions Architect owns integration decisions; Security reviews sensitive changes; QA validates the requirements matrix and returns `NEEDS_REWORK` with evidence when criteria fail.

Do not claim a feature is complete because the process starts or a demo works. Completion requires acceptance evidence, privacy/security gates, failure-state coverage, and an explicit decision about operational limitations.