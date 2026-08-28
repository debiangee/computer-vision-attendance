# Pilot Privacy and Data Governance Package

## Status

**Engineering preparation:** complete for the controls currently implemented in this repository.

**Privacy/legal approval:** pending. This document is an approval packet and engineering specification; it is not legal advice and does not authorize biometric processing by itself.

**Pilot release status:** blocked until the authorized privacy/legal owner approves the decisions in the sign-off section.

## 1. Proposed pilot purpose and boundary

The sole proposed purpose is to record a minimal **recognized-person encounter event** for an authorized participant at an approved lobby site.

The system must not:

- infer Time In, Time Out, shifts, breaks, holidays, payroll status, or attendance sessions;
- identify unregistered visitors, passers-by, or background subjects;
- continuously monitor or retain lobby video;
- make employment, disciplinary, access-control, productivity, demographic, health, emotion, or behavioral decisions;
- send camera frames, face crops, or biometric templates to an unapproved third party or cloud service;
- expose recognition confidence, biometric scores, templates, or liveness internals to participants.

The initial pilot is limited to one approved site, one Raspberry Pi, one camera, one approved model, and a named participant population.

## 2. Data inventory and flow

| Data | Collection/use | Default retention | Storage boundary | Pilot control |
|---|---|---:|---|---|
| Camera frames | Transient detection and recognition only | Memory duration of the interaction | Process memory | Never write frames, snapshots, or video by default |
| Face crops during enrollment | Temporary normalization and template construction | Memory duration of enrollment | Process memory | Discard after enrollment; never return through API |
| Matching template | Recognition of an enrolled participant | Owner-approved period; proposed maximum 90 days | Protected local template store required before pilot | Encryption, key management, access control, de-enrollment deletion |
| Template metadata | Lifecycle, model version, template version, and protected identifier | Proposed maximum 90 days | Local database | No raw template vectors or reversible image data |
| Recognition event | Minimal recognized-person encounter observation | Proposed maximum 90 days | Local event store and approved synchronization target | UTC timestamp, site/camera, model/policy version, immutable history |
| Suppression record | Cooldown audit and duplicate prevention | Same as event policy | Local database | No frame or biometric payload |
| Audit record | Security-sensitive action accountability | Owner-approved audit retention | Local audit store and approved audit target | No credentials, frames, templates, or unnecessary personal data |
| Authentication secrets | Service and administrator authentication | Rotation policy | Approved secret/key store | Never store in source, UI storage, logs, or event payloads |
| Backups/WAL/replicas | Recovery and synchronization copies | Same approved retention and deletion policy | Encrypted approved storage | Deletion propagation must be verified |

### Data flow

1. The approved local camera provides a bounded interaction stream.
2. The vision provider detects a face and performs quality, recognition, and liveness/PAD checks.
3. The policy layer requires a stable configured sample window and an authorized active enrollment.
4. The service checks cooldown and writes one minimal encounter event.
5. If local storage or approved synchronization is unavailable, the system enters the documented safe failure state and alerts the operator.
6. No raw frame, face crop, template vector, or confidence score is returned to the browser or written to application logs.

## 3. Participant notice and consent requirements

The final participant-facing notice must be reviewed by privacy/legal and adapted to the pilot jurisdiction. The following is an engineering draft, not approved legal language:

> This pilot uses a local camera and face-based matching to record a recognized-person encounter at the approved lobby site. It is limited to authorized participants and is not used to infer work hours, payroll, performance, behavior, emotion, age, gender, health, or other attributes. Camera frames are processed locally for the immediate interaction and are not recorded as lobby video by default. Face-derived enrollment data and encounter events are retained only for the approved period and are deleted according to the approved deletion procedure. You may use the approved non-biometric alternative if you do not participate or if recognition does not succeed. For questions, access requests, deletion requests, or complaints, contact the named pilot owner/privacy contact.

Before enrollment, the operator must confirm:

- [ ] The participant received the approved notice.
- [ ] The participant understands the purpose and retention period.
- [ ] The participant accepted the approved consent/lawful-basis process.
- [ ] The participant knows the non-biometric alternative.
- [ ] The participant knows how to request access, correction, or deletion.
- [ ] The participant population is within the approved pilot scope.

## 4. Lawful-basis and governance decisions required

The authorized privacy/legal owner must complete and sign off on:

- [ ] Applicable jurisdiction and employment/privacy requirements.
- [ ] Lawful basis for face-based processing.
- [ ] Whether consent is required and how it is recorded or withdrawn.
- [ ] Notice content, delivery channel, language, and accessibility.
- [ ] Whether a non-biometric alternative is mandatory.
- [ ] Whether the proposed 90-day maximum retention is justified.
- [ ] Whether biometric templates and encounter events have different retention periods.
- [ ] Cross-border, cloud, vendor, or remote-synchronization restrictions.
- [ ] Data-subject access, correction, deletion, objection, and complaint handling.
- [ ] Approved participant population and prohibited secondary uses.
- [ ] Data controller/processor and incident-notification responsibilities.

Until these decisions are approved, `COMPLIANCE_APPROVED` must not be interpreted as legal approval. It is only an application gate for the controlled demonstration.

## 5. Non-biometric fallback

The pilot must provide an approved fallback that does not require face recognition. The business owner must select and document one option, for example:

- badge or access-card scan;
- PIN or kiosk code;
- operator-assisted event entry;
- approved manual attendance/event record.

Fallback requirements:

- [ ] The fallback is available when the camera, model, liveness/PAD check, storage, or recognition result is unavailable.
- [ ] The fallback does not silently create a face-recognition event.
- [ ] Fallback events use a distinct source and audit metadata.
- [ ] Fallback access is RBAC-controlled and audited.
- [ ] Participants are not penalized for choosing the fallback or receiving a safe rejection.

## 6. Retention and deletion contract

The proposed pilot maximum is **90 days**, subject to approval. The final policy must define separate periods, if any, for templates, events, suppressions, audit records, backups, WAL files, exports, and synchronized copies.

Required deletion behavior:

1. De-enrollment suspends or deactivates the participant according to the approved lifecycle policy.
2. Active matching material is disabled immediately.
3. Local template metadata and protected template data are retired or deleted according to policy.
4. Recognition events and suppression records are handled according to the approved legal and operational policy.
5. Deletion requests propagate to WAL files, backups, replicas, exports, and approved remote sinks where required.
6. A minimal deletion audit record remains only if approved and must not contain raw biometric data.
7. Deletion completion is verifiable through an operator report.

The current repository has local retention/de-enrollment service seams, but it does not yet prove deletion from WAL files, backups, replicas, exports, or remote synchronization targets. That verification remains a P0 implementation and approval gate.

## 7. Privacy and security pilot stop criteria

Pause the pilot and notify the pilot owner if any of the following occurs:

- unauthorized person is recognized or an identity cannot be explained;
- a participant reports an unhandled privacy, access, correction, or deletion issue;
- raw frames, crops, templates, credentials, or unnecessary personal data appear in logs or exports;
- an authentication or authorization bypass is suspected;
- storage encryption, key integrity, or deletion verification fails;
- the camera/model/liveness behavior changes from the approved configuration;
- the system operates outside the approved site, participant, or purpose scope;
- the non-biometric fallback is unavailable;
- the event store, queue, or synchronization state cannot be trusted;
- the measured false-accept, false-reject, latency, or presentation-attack results exceed approved limits.

## 8. Required approval record

| Role | Name | Decision | Date | Signature/reference |
|---|---|---|---|---|
| Privacy/legal owner | TBD | Pending | TBD | TBD |
| Security owner | TBD | Pending | TBD | TBD |
| Business/product owner | TBD | Pending | TBD | TBD |
| Site owner | TBD | Pending | TBD | TBD |
| Pilot operator | TBD | Pending | TBD | TBD |

## 9. Engineering evidence attached to this package

- `README.md` — local executive-demo boundary and limitations.
- `docs/pilot-readiness-plan.md` — P0/P1/P2 checklist and release gates.
- `docs/qa-report.md` — local validation and unresolved release findings.
- `docs/security-review.md` — security findings and demo-specific residual risks.
- `src/lobby_attendance/application/retention.py` — local retention/de-enrollment seam.
- `src/lobby_attendance/vision/opencv.py` — transient camera processing and safe failure boundary.
- `src/lobby_attendance/application/pipeline.py` — bounded recognition-event policy boundary.

## Decision

**P0-01 engineering package:** prepared.

**P0-01 pilot gate:** OPEN until privacy/legal approval, participant notice/consent or lawful-basis decision, fallback approval, retention approval, and deletion-propagation approval are recorded by authorized owners.

## 10. P0-01 acceptance and handoff register

The following criteria define engineering readiness for review; a checked engineering item is not legal, privacy, product, or pilot approval.

| ID | Acceptance criterion | Required evidence | Current state |
|---|---|---|---|
| P0-01-A | Purpose, authorized population, site, camera, and prohibited uses are fixed | Approved scope record with version, owner, and effective date | Open — owner and population are not named |
| P0-01-B | Privacy impact/risk assessment and jurisdiction-specific lawful-basis decision are complete | Approved assessment and decision reference | Open — no external approval supplied |
| P0-01-C | Participant notice, consent/lawful-basis process, withdrawal/objection path, and accessibility/language requirements are approved | Versioned notice/process artifact and delivery evidence | Open — draft text only; no persistence or delivery workflow |
| P0-01-D | Participant rights workflow is operational for access, correction, deletion, objection, and complaint escalation | Intake, identity verification, SLA, owner, audit, legal-hold, and completion evidence | Open — no end-to-end workflow implemented |
| P0-01-E | A non-biometric fallback is selected, approved, implemented, and rehearsed | Decision record, distinct event source, RBAC/audit tests, operator rehearsal | Open — no fallback route or policy selected |
| P0-01-F | Retention periods, legal holds, deletion scope, and deletion propagation are approved and verified | Retention schedule, hold procedure, copy-by-copy deletion report | Open — local cleanup exists; nonlocal propagation is unverified |
| P0-01-G | Stop/resume authority and escalation contacts are named | Signed authority matrix, trigger thresholds, notification and resume checklist | Open — placeholders only |
| P0-01-H | Exact Raspberry Pi/webcam/model/PAD/latency evidence meets approved thresholds | Target-device evaluation, provenance, attack tests, p95 result, approval | Open — no hardware or evaluation evidence supplied |
| P0-01-I | Local fail-closed behavior is enforced when compliance approval is absent | Code review and regression evidence for service/API gate | Prepared — default-deny recognition gate and audited block are implemented |

### Decision register template

Every unresolved decision must be recorded before pilot approval. The record must include: `decision_id`, question, jurisdiction/site, options considered, selected option or `PENDING`, rationale, privacy/legal impact, data affected, owner, RACI participants, decision date, effective date/expiry, evidence reference, implementation change required, and review/reversal trigger.

| Decision ID | Question | Owner | Status | Evidence/reference |
|---|---|---|---|---|
| D-01 | Is face-based recognition permitted for this purpose and population, and on what lawful basis? | Privacy/legal owner TBD | PENDING | TBD |
| D-02 | Is notice, consent, another lawful-basis record, withdrawal, or objection handling required? | Privacy/legal owner TBD | PENDING | TBD |
| D-03 | Which non-biometric fallback is approved? | Product + privacy/legal owner TBD | PENDING | TBD |
| D-04 | What are retention periods, legal holds, and deletion obligations for each copy? | Privacy/data governance owner TBD | PENDING | TBD |
| D-05 | Who may stop and resume the pilot, and what evidence is required to resume? | Pilot owner + privacy/security owners TBD | PENDING | TBD |
| D-06 | Which hardware, model, PAD, accuracy, and latency thresholds are accepted? | ML/QA/platform owners TBD | PENDING | TBD |

### RACI and authority placeholders

Names, accounts, delegation dates, and signatures must be completed; role labels alone do not authorize processing.

| Activity | Responsible | Accountable | Consulted | Informed |
|---|---|---|---|---|
| Purpose, lawful basis, notice, participant rights | Privacy/legal owner TBD | Privacy/legal owner TBD | Product, employment, security TBD | Site/operator TBD |
| Participant enrollment and withdrawal | Enrollment owner TBD | Product/privacy owner TBD | Site/operator, support TBD | Participant TBD |
| Fallback operation and correction | Attendance/operator owner TBD | Product owner TBD | Privacy, security, QA TBD | Participant TBD |
| Retention, legal hold, and deletion propagation | Data/platform owner TBD | Privacy/data-governance owner TBD | Security, backup/remote-sink owners TBD | Pilot owner TBD |
| Stop/resume and incident escalation | Pilot operator TBD | Named stop authority TBD | Privacy, security, product, QA TBD | Participants/site TBD |
| Hardware/model/PAD evaluation | ML/QA/platform owners TBD | Security/product owner TBD | Privacy, site operator TBD | Pilot owner TBD |

### Data-copy inventory and deletion verification

Before approval, inventory every copy actually enabled in the deployment. `Not applicable` must be justified and signed; it must not be inferred from the local SQLite cleanup code.

| Copy/boundary | Data classes | Location/system owner | Encryption/key owner | Retention/hold | Delete mechanism | Verification evidence |
|---|---|---|---|---|---|---|
| Process memory | Frames/crops/transient observations | Device owner TBD | Device owner TBD | Interaction only | Process release | Capture/release test and deployment review |
| Local SQLite/database file | Events, metadata, audit, lifecycle rows | Platform owner TBD | Key owner TBD | TBD | Approved purge/de-enrollment | File/WAL inspection and restore test |
| Local queue | Minimal queued event payload | Platform owner TBD | Key owner TBD | Queue age limit/TBD | Queue purge/tombstone | Restart, full, and deletion test |
| WAL/journal/temp files | Database recovery material | Platform owner TBD | Key owner TBD | TBD | Rotation/expiry procedure | Filesystem inspection |
| Backups/snapshots | Database and queue copies | Backup owner TBD | Key owner TBD | TBD/legal hold | Backup expiry/delete request | Restore and deletion report |
| Exports/reports | Approved event extracts | Attendance owner TBD | Key owner TBD | TBD | Export registry/delete workflow | Inventory and deletion evidence |
| Remote synchronization/replica | Synchronized event payload | Remote owner TBD | Key owner TBD | TBD/legal hold | Authenticated remote delete/tombstone | Acknowledgement and reconciliation report |

### Participant-rights workflow requirements

Until the owner decision is recorded, the system must not claim that the draft notice is delivered or that rights requests are supported. The approved workflow must provide: a documented intake channel; identity verification that does not require unnecessary biometric disclosure; request classification; access to the relevant event/template metadata; correction with immutable history; deletion/withdrawal handling; objection/alternative handling; legal-hold exception handling; response owner and deadline; escalation/complaint contact; copy-by-copy propagation; and an auditable completion or reasoned exception record. No raw frames, templates, credentials, or unnecessary personal data may appear in the request or response.

### Fallback decision requirements

The product/privacy owners must choose one approved non-biometric method before pilot enrollment. Engineering must then add a distinct source and route/service, authorization and audit controls, operator and participant messaging, duplicate/idempotency behavior, retention/deletion treatment, and tests for camera/model/liveness/recognition failure, local-storage failure, and disputed events. Until that decision is made, “ask an operator for help” is an escalation message only and is not an implemented fallback or release control.

### Stop/resume authority

The pilot must have one named stop authority and one named delegate, with a contact path available at the site. Stop triggers include an unexplained recognition, privacy/rights complaint, suspected data exposure, untrusted queue/storage/synchronization state, model/camera/configuration drift, unavailable approved fallback, or failed accuracy/PAD/latency threshold. Resume requires the trigger to be documented, affected data contained, corrective action verified, privacy/security review completed where applicable, and the named authority's dated approval recorded. No environment flag alone can resume the pilot.

### Outage semantics

- **Remote database or synchronization outage with healthy local storage:** no remote acknowledgement is claimed. The service may persist only the approved minimal event payload to the bounded local queue, preserve idempotency, expose `event-queued-locally`, and alert the operator. Queue encryption, restart durability, authenticated synchronization, and remote deletion remain deployment gates.
- **Local database, encrypted storage, queue, filesystem, or integrity failure/full condition:** fail closed; do not create or queue a recognition event, return an operator-safe unavailable state, and alert the system operator. Do not silently switch to an unapproved fallback.
- **Camera/model/liveness/compliance gate failure:** fail closed with a neutral safe state and operator escalation. This is not a participant fallback until the approved fallback decision and implementation exist.

## 11. Engineering status clarification

The repository now contains a local fail-closed recognition compliance gate and regression evidence. This is an engineering control only. The P0-01 package is **prepared for authorized review**, not approved for participant enrollment or pilot release. All P0-01 acceptance criteria marked Open above remain release blockers.
