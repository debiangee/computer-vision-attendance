# Lobby attendance MVP (Phase 3 prototype)

This repository contains a local-first lobby recognition-event prototype. It records authorized recognized-person encounter events only; it does not infer Time In/Time Out, shifts, holidays, breaks, payroll, or attendance sessions. The Flask factory, protected API, neutral kiosk, and admin prototype are included. No Raspberry Pi camera/model validation is claimed.

## Install

The project requires Python 3.11+ and pinned dependencies. Create a virtual environment, then install the development or optional OpenCV extra.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
# Optional local OpenCV adapter (model files are supplied by the operator):
python -m pip install -e ".[dev,vision]"
```

Raspberry Pi/Linux:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
# Optional local OpenCV adapter:
python -m pip install -e ".[dev,vision]"
```

The OpenCV extra is never downloaded or installed at runtime. Model assets must be provisioned by an operator from an approved, documented source. When configured, `LOBBY_ATTENDANCE_VISION_MODEL_DIRECTORY` restricts the asset to that directory and `LOBBY_ATTENDANCE_VISION_MODEL_SHA256` verifies its SHA-256 before loading. The provider rejects missing, non-regular, symlinked, out-of-directory, or digest-mismatched assets and records `sha256:<digest>` as the model version. Record model provenance, checksum, license, thresholds, liveness behavior, and performance in the deployment change record.

## Local token setup and startup

The prototype uses explicit bearer tokens as a temporary service boundary, not production SSO. Tokens are read from the process environment and are never returned by the API or persisted by the UI. Use long random values locally and replace this boundary with the approved identity/session integration before production.

Windows PowerShell, development-only synthetic vision:

```powershell
$env:LOBBY_ATTENDANCE_DATABASE_PATH = "data\lobby_attendance.sqlite3"
$env:LOBBY_ATTENDANCE_ADMIN_TOKEN = "replace-with-a-long-random-admin-token"
$env:LOBBY_ATTENDANCE_KIOSK_TOKEN = "replace-with-a-long-random-kiosk-token"
$env:LOBBY_ATTENDANCE_DEVELOPMENT_MOCK_VISION = "true"
python -m flask --app lobby_attendance.api:create_app run --host 127.0.0.1 --port 5000
```

Raspberry Pi/Linux, development-only synthetic vision:

```bash
export LOBBY_ATTENDANCE_DATABASE_PATH=data/lobby_attendance.sqlite3
export LOBBY_ATTENDANCE_ADMIN_TOKEN='replace-with-a-long-random-admin-token'
export LOBBY_ATTENDANCE_KIOSK_TOKEN='replace-with-a-long-random-kiosk-token'
export LOBBY_ATTENDANCE_DEVELOPMENT_MOCK_VISION=true
python -m flask --app lobby_attendance.api:create_app run --host 0.0.0.0 --port 5000
```

## Local encrypted-storage smoke test

For a local encrypted-storage smoke test, use a temporary database path and a freshly generated key. This verifies local authenticated persistence only; it does not provide production key custody, backup encryption, deletion propagation, or deployment approval.

Windows PowerShell:

```powershell
$env:LOBBY_ATTENDANCE_DATABASE_PATH = "data\\local-encrypted.sqlite3"
$env:LOBBY_ATTENDANCE_STORAGE_ENCRYPTION_KEY = (python -c "import secrets; print(secrets.token_hex(32))")
$env:LOBBY_ATTENDANCE_STORAGE_ENCRYPTION_REQUIRED = "true"
$env:LOBBY_ATTENDANCE_DEVELOPMENT_MOCK_VISION = "true"
python -m flask --app lobby_attendance.api:create_app run --host 127.0.0.1 --port 5000
```

Linux:

```bash
export LOBBY_ATTENDANCE_DATABASE_PATH=data/local-encrypted.sqlite3
export LOBBY_ATTENDANCE_STORAGE_ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export LOBBY_ATTENDANCE_STORAGE_ENCRYPTION_REQUIRED=true
export LOBBY_ATTENDANCE_DEVELOPMENT_MOCK_VISION=true
python -m flask --app lobby_attendance.api:create_app run --host 127.0.0.1 --port 5000
```

Open the kiosk locally:

```powershell
Start-Process "msedge" "http://127.0.0.1:5000/kiosk"
```

```bash
chromium-browser --kiosk http://127.0.0.1:5000/kiosk
# Some distributions use: chromium --kiosk http://127.0.0.1:5000/kiosk
```

The kiosk prompts for the configured kiosk token and keeps it in JavaScript memory only. The admin page is at `/admin`; it accepts the configured admin token in memory only. The browser UI does not send camera frames to the API; the current server pipeline uses the configured local provider.

For a local OpenCV configuration, unset mock vision and provide a local model path, for example:

```powershell
$env:LOBBY_ATTENDANCE_DEVELOPMENT_MOCK_VISION = "false"
$env:LOBBY_ATTENDANCE_VISION_MODEL_PATH = "C:\approved-models\face.xml"
$env:LOBBY_ATTENDANCE_VISION_MODEL_DIRECTORY = "C:\approved-models"
$env:LOBBY_ATTENDANCE_VISION_MODEL_SHA256 = "replace-with-the-reviewed-64-character-sha256"
python -m flask --app lobby_attendance.api:create_app run --host 127.0.0.1 --port 5000
```

```bash
export LOBBY_ATTENDANCE_DEVELOPMENT_MOCK_VISION=false
export LOBBY_ATTENDANCE_VISION_MODEL_PATH=/opt/lobby-attendance/models/approved-face.xml
export LOBBY_ATTENDANCE_VISION_MODEL_DIRECTORY=/opt/lobby-attendance/models
export LOBBY_ATTENDANCE_VISION_MODEL_SHA256=replace-with-the-reviewed-64-character-sha256
python -m flask --app lobby_attendance.api:create_app run --host 0.0.0.0 --port 5000
```

## Environment variables

All settings use the `LOBBY_ATTENDANCE_` prefix: `DATABASE_PATH`, `STORAGE_ENCRYPTION_KEY`, `STORAGE_ENCRYPTION_REQUIRED`, `SITE_ID`, `CAMERA_ID`, `TIMEZONE`, `COOLDOWN_SECONDS`, `STABLE_WINDOW_SIZE`, `STABLE_REQUIRED_COUNT`, `QUEUE_MAX_AGE_SECONDS`, `QUEUE_MAX_SIZE`, `QUEUE_LEASE_SECONDS`, `RETENTION_DAYS`, `CAPTURE_MAX_SAMPLES`, `SAMPLING_INTERVAL_SECONDS`, `INTERACTION_TIMEOUT_SECONDS`, `VISION_MODEL_PATH`, `VISION_MODEL_DIRECTORY`, `VISION_MODEL_SHA256`, `DEVELOPMENT_MOCK_VISION`, `COMPLIANCE_APPROVED`, and `DEVELOPMENT_MOCK_COMPLIANCE_APPROVAL`. `STORAGE_ENCRYPTION_KEY` is a 64-hex-character key; `STORAGE_ENCRYPTION_REQUIRED=true` fails closed without it. `QUEUE_LEASE_SECONDS` defaults to 300 seconds.
`VISION_MODEL_DIRECTORY` is an optional approved-root restriction; without it, the explicitly configured model path is still required to be a regular non-symlink file. A SHA-256 value is strongly recommended and must be required by the production model-provenance procedure.

API boundary settings are `AUTH_MODE`, `AUTH_SIGNING_KEY`, `AUTH_ISSUER`, `AUTH_AUDIENCE`, `AUTH_MAX_TTL_SECONDS`, `AUTH_REAUTH_MAX_AGE_SECONDS`, and `TRUST_FORWARDED_PROTO`. Pilot mode uses signed short-lived sessions from an approved identity provider or identity gateway; it rejects static tokens, requires TLS, validates issuer/audience/expiry/authentication time/token kind, supports durable token revocation, and requires recent authentication for enrollment, reset, export, correction, template, user, role, and revocation mutations. The static `ADMIN_TOKEN`, `KIOSK_TOKEN`, and `ADMIN_ROLES` boundary remains only for the supervised demo/tests and is not pilot-safe. `COMPLIANCE_APPROVED` defaults to false and is the explicit application privacy/legal gate; it is not legal approval. Do not put real tokens, signing keys, or secret-manager credentials in source control, `.env` files committed to the repository, logs, screenshots, or test fixtures.

## API and UI behavior

- `GET /health` and `GET /api/health` expose only readiness state for camera, model, database, queue, and the non-secret compliance gate (`approved` or `pending`); they contain no secrets.
- `POST /api/kiosk/interaction` requires the kiosk token and returns only a safe state/message pair such as `recognized-event-recorded`, `duplicate-suppressed`, `event-queued-locally`, `unknown`, `liveness-failed`, `unavailable`, `no-face`, or `multiple-faces`.
- Admin API routes require the admin token plus the role-derived permission: enrollment lifecycle/template metadata, events, immutable corrections, redacted export, role assignment, queue operations, and sanitized audit viewing are separate protected operations. Corrections append before/after history and never update or delete the original event. Exports contain only bounded event fields and are audited.
- Queue claims, synchronization, retries, expiry, and sink failures create bounded audit records attributed to the authenticated operator. Queue responses expose only counts and safe operator states (`ready`, `queue-full`, `synchronization-failure`, or `action-required`); payloads and raw exceptions are never returned.
- Queue claims use a 300-second configurable lease by default. Synchronization reclaims expired in-flight claims before retrying or claiming pending items; stale claims therefore do not strand events after a crash. Manual claim is an operator action, not delivery, and a real deployment must use an authenticated durable remote sink with idempotency.
- Retention is an operations-layer `RetentionService`, not an unaudited public deletion route. `purge_expired` removes records older than the configured period from recognition events, suppression records, local queue items, and retired template metadata; de-enrollment cleanup removes those local records for the deactivated user. Each operation is audited, and ordinary event updates/deletes remain blocked by SQLite triggers.
- The kiosk is a neutral full-screen camera/status view with no Time In/Time Out controls. Unknown, ambiguous, low-quality, liveness-failed, duplicate, queue, storage, and operator-attention states reset to neutral automatically.

## Validation

Run the validation suite after installing the declared development dependencies:

```text
python -m pytest
python -m compileall -q src tests
python -m pip check
```

The remediation handoff records the exact results for these commands. Local encrypted-storage round-trip, wrong-key, plaintext-rejection, factory-wiring, and encrypted kiosk smoke checks are covered by automated tests. No production key custody, backup/replica encryption, deletion propagation, webcam, Raspberry Pi, authenticated remote sink, network service, or production SSO validation is claimed.

Recognition rows now carry an immutable storage state, correlation identifier, and bounded audit metadata; queued/rejected transitions are represented by minimal queue/audit records without frames or templates. This is an application contract, not evidence that the queue is encrypted or that a remote sink is durable.

The mock provider is synthetic and deterministic. The optional OpenCV adapter fails closed when camera/model assets are unavailable, unapproved, symlinked, or digest-mismatched; its passive liveness behavior is not a security guarantee. The local queue synchronizer uses an in-process sink in this prototype, even though leases/reclaim and idempotency are implemented. Authenticated remote synchronization, encrypted storage/transport, queue integrity, backup/replica deletion propagation, and device hardening require a reviewed deployment design. Retention purges are local database operations only; they do not claim deletion from backups, replicas, WAL copies, or remote sinks.

Before production, complete privacy/legal review (including the unresolved notice/consent/non-biometric-alternative decision), a privacy impact assessment, threat model, RBAC/access review, retention/deletion verification, model evaluation and threshold calibration, representative environmental testing, Raspberry Pi camera/latency validation, incident/recovery plan, dependency/model provenance review, and Security approval. Do not store lobby video, raw face images, raw templates, or unnecessary biometric data.

## Executive demo mode (local supervised demonstration)

The repository includes an explicit, opt-in executive demo flow for a consenting authorized participant. This is the only supported path for demonstrating real local enrollment and recognition in this workspace; it is not a production biometric system.

The flow uses the **server-attached webcam** for both enrollment and recognition. The browser does not upload camera frames. The OpenCV detector captures a bounded enrollment sample set, and the local normalized grayscale crop matcher keeps the normalized template only in process memory. SQLite receives only server-generated lifecycle metadata and an immutable recognition event if the event is accepted. Raw frames, crops, matcher arrays, scores, and liveness details are not returned by the API or written by the application. Enrollment is lost when the process restarts and must be repeated. Within one process, enrollment and kiosk recognition share a single-flight camera lock; multi-worker or cross-process deployments are not covered.

The matcher and liveness behavior are demonstration heuristics. They are not evaluated face-recognition accuracy, presentation-attack detection, or identity proof. Use one consenting participant, one approved local detector asset, one attached webcam, and a local-only binding for the presentation. Do not use this mode for workplace decisions or production attendance.

Windows PowerShell demo setup:

```powershell
$env:LOBBY_ATTENDANCE_DATABASE_PATH = "data\executive-demo.sqlite3"
$env:LOBBY_ATTENDANCE_ADMIN_TOKEN = "replace-with-a-long-random-local-token"
$env:LOBBY_ATTENDANCE_ADMIN_ROLES = "enrollment-administrator"
$env:LOBBY_ATTENDANCE_KIOSK_TOKEN = "replace-with-a-long-random-local-kiosk-token"
$env:LOBBY_ATTENDANCE_EXECUTIVE_DEMO_MODE = "true"
$env:LOBBY_ATTENDANCE_DEMO_LIVENESS_ENABLED = "true"
$env:LOBBY_ATTENDANCE_COMPLIANCE_APPROVED = "true"
$env:LOBBY_ATTENDANCE_VISION_MODEL_PATH = "C:\approved-models\face.xml"
$env:LOBBY_ATTENDANCE_VISION_MODEL_DIRECTORY = "C:\approved-models"
$env:LOBBY_ATTENDANCE_VISION_MODEL_SHA256 = "replace-with-the-reviewed-64-character-sha256"
python -m flask --app lobby_attendance.api:create_app run --host 127.0.0.1 --port 5000
```

For Raspberry Pi/Linux, use the same variables with `export` and bind to a reviewed local interface. Do not expose the development Flask server directly to an untrusted network.

Demo sequence:

1. Open `/admin` and enter the configured admin token.
2. Refresh demo status and confirm that mode, model, compliance gate, and heuristic liveness are ready.
3. Enter a non-sensitive demo ID and consenting participant name, then select **Enroll consenting participant**. Keep one face in view of the webcam while the server captures the bounded samples.
4. Open `/kiosk`, enter the kiosk token, and present the same participant to the **server-attached** webcam. The browser preview is not the recognition input.
5. Use `/api/admin/events` or the admin event view to show the resulting recognized-person encounter event. Repeated recognition during the cooldown is suppressed.
6. Use **Reset demo enrollment** after the presentation. If the server restarted since enrollment, provide the demo user ID explicitly; reset-all refuses to claim success when the RAM registry cannot identify the persisted demo user. The reset suspends the user, retires active demo metadata, removes the RAM matcher entry, and preserves event history.

Demo routes:

- `GET /api/admin/demo/status` — safe readiness and in-memory template count only.
- `POST /api/admin/demo/enrollment` — accepts only bounded `user_id` and `display_name`; the server captures the webcam samples.
- `POST /api/admin/demo/reset` — requires `{"confirm":true}`; an optional `user_id` resets that user. After a process restart, `user_id` is required and reset-all returns `409 operator-action-required` rather than claiming that no enrollment was removed.
- `POST /api/kiosk/interaction` — existing neutral recognition-event endpoint.

`LOBBY_ATTENDANCE_EXECUTIVE_DEMO_MODE` defaults to false. The demo does not silently fall back to mock recognition, metadata-only activation, or browser-frame uploads. Missing model assets, camera access, liveness configuration, malformed samples, ambiguous matches, and storage failures fail closed.

The demo remains subject to all existing production blockers: privacy/legal approval, effective authenticated subject/site RBAC, TLS and encryption/key management, durable authenticated synchronization, deletion propagation, signed model provenance, target Raspberry Pi/webcam evaluation, real presentation-attack resistance, browser/device testing, and the existing SQLite/threading, correction-retention, and queue-lease limitations. `COMPLIANCE_APPROVED=true` is an application setting for a controlled demonstration, not legal approval.


Demo reset is a lifecycle revocation: it suspends the demo user, retires active demo metadata, removes the in-memory matcher entry, and preserves the recognition event history. It does not claim deletion from SQLite WAL files, backups, replicas, exports, or remote copies. Demo recognition storage failures fail closed without the normal local queue fallback; the presentation must retry after the operator resolves storage.

## Raspberry Pi transfer and USB camera testing

Transfer this entire project directory to your Raspberry Pi (e.g. via `scp`, USB drive, or `git clone`). Then run the deployment helper script:

```bash
chmod +x scripts/deploy-pi.sh
./scripts/deploy-pi.sh
```

The script will:
1. Create a Python virtual environment.
2. Install the project with the OpenCV vision extra.
3. Download the Haar Cascade face detection model.
4. Run the device evaluation harness (camera diagnostics + provider benchmark).
5. Print configuration instructions for starting the Flask server.

Alternatively, run the evaluation harness directly:

```bash
source .venv/bin/activate
python -m lobby_attendance evaluate \
    --camera-index 0 \
    --model-path models/haarcascade_frontalface_default.xml \
    --iterations 20 \
    --output data/evaluation-report.json
```

The evaluation report (`data/evaluation-report.json`) contains:
- Host metadata: platform, CPU, memory, temperature, disk.
- Camera diagnostics: resolution, FPS, backend, first-frame success.
- Provider benchmark: per-interaction latency, p95, status distribution.
- No frames, embeddings, identities, or biometric data are stored.

Review the report to confirm camera availability, acceptable latency (target: p95 under 2000ms), and status distribution before starting the full server.

### Important limitations

- The Haar Cascade model is a demonstration face detector. It is not an evaluated biometric recognition model and not identity proof.
- `demo_presence_liveness_checker` verifies bounded in-frame presence only; it is not presentation-attack detection.
- `COMPLIANCE_APPROVED=true` is a technical/demo gate, not privacy/legal approval.
- No real recognition or attendance enrollment should be treated as production evidence until the privacy/legal, PAD/accuracy, key custody, and fallback gates are resolved.
- The evaluation report is local engineering evidence for P0-05 only; it does not approve the pilot.
