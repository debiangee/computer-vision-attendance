---
inclusion: always
---

# Lobby Attendance Product Guidance

## Product intent
Build a lobby kiosk that helps authorized people record attendance using face recognition. The system must optimize for correct, explainable attendance events and respectful user control—not maximum surveillance or automatic identification of everyone in view.

## Conservative MVP boundary
- Recognize only enrolled users who are authorized through RBAC and have an active enrollment status. Do not identify unregistered visitors or passers-by.
- Automatically create a **recognized-person encounter event** after a stable match and liveness check. This system records recognition events; it does not infer Time In, Time Out, shifts, or attendance sessions.
- Require identity stability across a short sample window—proposed default: the same identity in at least 3 of 5 frames over approximately 1 second—before creating an event.
- Process the camera feed for the immediate interaction; do not continuously record or retain lobby video by default.
- Unknown, ambiguous, low-confidence, or failed-liveness matches must never create an event automatically.
- Do not create one row per frame. Suppress repeated events for the same person using a configurable cooldown—proposed default: 5 minutes per person per camera—and retain the original event rather than silently overwriting it.
- The owner currently requests no separate notice/consent flow and no non-biometric alternative. This is recorded as a provisional product decision and remains subject to privacy/legal approval before production; it is not a release approval.

## Attendance/event behavior defaults
These are proposed defaults for the MVP and require owner confirmation before production:
- Store event time in UTC and display it in the configured site timezone.
- Record the source (`face-encounter`) plus camera/site, model version, policy version, and audit metadata.
- Treat events as immutable observations. Do not infer shifts, holidays, missing check-outs, overnight sessions, or payroll status in this system.
- Keep a local durable queue on the Raspberry Pi when the database is temporarily unavailable; synchronize later with idempotency keys. If local storage is unavailable or full, fail closed and alert the operator.
- Permit only authorized administrators to suspend, delete, correct, export, or audit records through audited RBAC workflows.

## Recommended automatic-event flow
1. Detect a face near the lobby camera.
2. Run quality, recognition, and liveness checks.
3. Require the stable-match window before accepting an identity.
4. Check the per-person cooldown.
5. Write one minimal event to the local/database store.
6. Return to a neutral camera state without exposing raw confidence or biometric data.

## User experience and operational states
Every interaction must have visible or operator-visible states for:
- camera unavailable or permission denied;
- no face detected;
- multiple faces detected;
- unknown or low-confidence person;
- liveness failure;
- recognized event recorded;
- duplicate/cooldown suppression;
- event queued locally while the database is unavailable;
- local queue full or storage failure;
- operator/admin action required.

The Raspberry Pi kiosk should use a lightweight model and bounded frame sampling. Target fast feedback—proposed target: recognition event decision within 2 seconds at the 95th percentile—but never lower safety thresholds merely to improve speed.

## Out of scope until explicitly approved
- Inferring Time In/Time Out, shifts, holidays, breaks, missing events, or overnight sessions.
- Identifying unregistered visitors or passers-by.
- Emotion, gender, age, health, productivity, or behavioral inference.
- Continuous surveillance, background watchlists, or automated disciplinary decisions.
- Sharing face images or biometric templates with third parties or cloud services by default.
- Treating recognition confidence as proof of identity without liveness, threshold calibration, and a fallback.

## Product decisions required before production
Confirm the RBAC population and role owners, the privacy notice/consent or lawful-basis position, whether a non-biometric alternative is required, the cooldown, site/timezone, three-month retention proposal, local queue limits, supported Raspberry Pi/webcam setup, recognition accuracy targets, and administrator correction/export rules. Keep the requested “no notice/consent/alternative” position visible as an unresolved privacy/legal risk rather than embedding it as an unquestioned assumption.