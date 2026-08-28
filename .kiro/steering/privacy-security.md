---
inclusion: always
---

# Privacy and Security Guidance for Face-Based Attendance

Face recognition and face-derived templates can be highly sensitive personal or biometric data. Treat this project as privacy-sensitive from the first design decision. This guidance is engineering direction, not legal advice; the organization must obtain appropriate privacy, employment, and legal review for the deployment jurisdiction.

## Privacy by design
- Use an explicit purpose limitation: recognition-event logging for an RBAC-approved population only. Do not identify unregistered visitors or passers-by.
- The current owner position is that there will be no separate notice/consent flow because the system is for time capture only, and no non-biometric alternative is planned. This is a provisional risk decision, not a privacy approval. The organization must obtain jurisdiction-specific privacy, employment, and legal review before production; if that review requires notice, consent/lawful basis, or an alternative, implementation must add it.
- Default to local/on-device processing on the Raspberry Pi 4. Do not send frames, images, or templates to a third-party service unless an approved design and data-processing review explicitly permits it.
- Keep camera frames in memory only for the shortest practical duration. Do not store lobby video or snapshots by default.
- Store only the minimum representation needed for matching. Separate identity/profile data from biometric templates and recognition events where practical.
- The proposed retention period is three months for biometric-template and event records, subject to privacy/legal, operational, and deletion-policy confirmation. Define deletion on de-enrollment and propagation to backups/replicas before production.
- Do not use the system for emotion, demographic, health, productivity, or behavioral inference.

## RBAC and security controls
Use least privilege and separation of duties. The recommended role model is:
- **Kiosk service:** capture/recognition interaction and append-only event submission; no administration, browsing, template export, or policy editing.
- **Enrollment administrator:** create, verify, suspend, rotate, and de-enroll authorized users; no unrestricted event export unless separately granted.
- **Attendance administrator:** view attendance events and perform audited corrections; no raw template access.
- **Auditor:** read-only access to approved events and audit records; no modification or export unless explicitly granted.
- **System operator:** device health, deployment, model/configuration version, and queue operations; no routine access to biometric content.
- **RBAC administrator:** manage roles and permissions; use a separate, strongly protected account from routine enrollment/correction work.

- Require strong administrator authentication and re-authentication for enrollment, deletion, export, role changes, and corrections.
- Encrypt biometric templates, attendance records, the local offline queue, backups, and secrets at rest; use authenticated encrypted transport when synchronizing.
- Log security-sensitive actions without logging raw face images, templates, credentials, or unnecessary personal data.
- Protect enrollment, synchronization, and correction endpoints against unauthorized access, replay, CSRF, injection, mass assignment, and duplicate submissions.
- Keep dependencies and model files pinned, scanned, and provenance-documented. Do not download arbitrary models at runtime.
- Apply least privilege to the camera, local process, database, filesystem, and deployment identity.
- Secure the Raspberry Pi physically, disable unused services, restrict remote administration, use a watchdog/health service, and protect against power-loss corruption.
- Define backup access, deletion propagation, incident response, model rollback, and compromise procedures.

## Offline and queue safety
- If the remote database is unavailable but the Pi and local storage are healthy, persist only the minimum event payload in an encrypted, append-only local queue and synchronize later with idempotency keys.
- Never queue raw frames or unnecessary biometric data.
- Bound queue size and age. If the queue is full, storage is unavailable, or integrity cannot be verified, fail closed for recognition-event logging and alert the system operator.
- Synchronization must be authenticated, retry-safe, ordered where required, and auditable. A reconnect must not create duplicate events.

## Recognition safety and performance
- Calibrate thresholds on representative data from the actual webcam, lighting, distance, and authorized population.
- Require liveness or presentation-attack resistance appropriate to the threat model and require a stable match across the configured sample window; proposed starting point is 3 of 5 matching frames over approximately 1 second.
- Prefer a safe rejection over a false positive. Never create an event when identity or liveness is uncertain.
- Treat speed as a performance target, not a reason to lower safety thresholds. Measure a proposed decision target of under 2 seconds at the 95th percentile on the Raspberry Pi 4.
- Test demographic and environmental performance where lawful and appropriate, document limitations, and define an operator correction path.
- Do not expose raw confidence scores to kiosk users; present only an appropriate event/result state.

## Required privacy/security gates
Before production, complete a privacy impact/risk assessment, threat model, access review, retention/deletion verification, backup and queue review, incident plan, Raspberry Pi hardening review, model evaluation, and security review. The current no-notice/no-consent/no-alternative choice must be explicitly accepted by the authorized privacy/legal owner or changed before release. A feature with unresolved high-impact privacy or security findings cannot pass the release gate.