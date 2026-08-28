import hashlib
from datetime import datetime, timedelta, timezone

from lobby_attendance.application import (
    EnrollmentService,
    InMemoryEventSink,
    QueueSynchronizer,
    EventSubmission,
    RecognitionEventService,
    RecognitionPipeline,
    RetentionService,
)
from lobby_attendance.config import Settings
from lobby_attendance.domain import QueueState, RecognitionObservation, UserStatus
from lobby_attendance.storage import SQLiteStore
from lobby_attendance.storage.repositories import (
    AuditRepository,
    EventRepository,
    QueueRepository,
    SuppressionRepository,
    RetentionRepository,
    TemplateMetadataRepository,
    UserRepository,
)
from lobby_attendance.vision import MockVisionProvider, OpenCVVisionProvider, VisionStatus

UTC = timezone.utc
NOW = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)


def _service(store, *, events=None, queue=None):
    users = UserRepository(store)
    return RecognitionEventService(
        users,
        events or EventRepository(store),
        queue or QueueRepository(store),
        suppressions=SuppressionRepository(store),
        audit=AuditRepository(store),
        site_id="site-a",
        camera_id="cam-a",
        model_version="mock-1",
        compliance_approved=True,
    )


def test_recognition_is_fail_closed_without_compliance_approval(tmp_path):
    with SQLiteStore(tmp_path / "blocked-recognition.sqlite3") as store:
        users = UserRepository(store)
        users.create("synthetic-user", "Synthetic User")
        service = RecognitionEventService(
            users,
            EventRepository(store),
            QueueRepository(store),
            audit=AuditRepository(store),
            site_id="site-a",
            camera_id="cam-a",
            model_version="mock-1",
        )
        observations = [
            sample.observation
            for sample in MockVisionProvider(start_at=NOW).observe(until=NOW + timedelta(seconds=2))
        ]

        result = service.submit(observations, occurred_at=NOW)

        assert result == EventSubmission("rejected", "compliance-not-approved")
        assert EventRepository(store).list_events() == []
        assert any(row["action"] == "recognition:blocked" for row in AuditRepository(store).list_events())


def test_mock_provider_is_deterministic_and_synthetic():
    provider = MockVisionProvider(identity_id="synthetic-user", sample_count=5, start_at=NOW)
    samples = provider.observe(until=NOW + timedelta(seconds=2))
    assert len(samples) == 5
    assert [sample.observation.identity_id for sample in samples] == ["synthetic-user"] * 5
    assert all(sample.status is VisionStatus.RECOGNIZED for sample in samples)


def test_pipeline_caps_samples_and_records_one_event(tmp_path):
    class TooManySamples:
        def observe(self, *, until):
            return MockVisionProvider(start_at=NOW, sample_count=5).observe(until=until) * 2

    with SQLiteStore(tmp_path / "events.sqlite3") as store:
        users = UserRepository(store)
        users.create("synthetic-user", "Synthetic User")
        events = EventRepository(store)
        pipeline = RecognitionPipeline(
            TooManySamples(), _service(store, events=events),
            settings=Settings(capture_max_samples=5),
        )
        result = pipeline.process_interaction(occurred_at=NOW)
        assert result.state == "recognized-event-recorded"
        assert len(result.samples) == 5
        assert len(events.list_events()) == 1


def test_liveness_failure_is_rejected_without_event(tmp_path):
    with SQLiteStore(tmp_path / "events.sqlite3") as store:
        users = UserRepository(store)
        users.create("synthetic-user", "Synthetic User")
        result = RecognitionPipeline(
            MockVisionProvider(identity_id="synthetic-user", liveness_passed=False, start_at=NOW),
            _service(store),
            settings=Settings(),
        ).process_interaction(occurred_at=NOW)
        assert result.state == "liveness-failed"
        assert EventRepository(store).list_events() == []


def test_cooldown_suppression_records_audit_without_second_event(tmp_path):
    with SQLiteStore(tmp_path / "events.sqlite3") as store:
        users = UserRepository(store)
        users.create("synthetic-user", "Synthetic User")
        service = _service(store)
        first = service.submit(
            [s.observation for s in MockVisionProvider(start_at=NOW).observe(until=NOW + timedelta(seconds=2))],
            occurred_at=NOW,
        )
        second = service.submit(
            [s.observation for s in MockVisionProvider(start_at=NOW).observe(until=NOW + timedelta(seconds=2))],
            occurred_at=NOW + timedelta(seconds=100),
        )
        assert first.state == "recorded"
        assert second.state == "suppressed"
        assert EventRepository(store).list_events() and len(EventRepository(store).list_events()) == 1
        assert SuppressionRepository(store).latest_for_user_camera("synthetic-user", "cam-a")


def test_duplicate_retry_is_idempotent_before_cooldown(tmp_path):
    with SQLiteStore(tmp_path / "events.sqlite3") as store:
        UserRepository(store).create("synthetic-user", "Synthetic User")
        service = _service(store)
        observations = [s.observation for s in MockVisionProvider(start_at=NOW).observe(until=NOW + timedelta(seconds=2))]
        assert service.submit(observations, occurred_at=NOW).state == "recorded"
        retry = service.submit(observations, occurred_at=NOW)
        assert retry.state == "duplicate"
        assert len(EventRepository(store).list_events()) == 1


def test_queue_fallback_and_retry_safe_sync(tmp_path):
    class UnavailableEvents:
        def get_by_idempotency(self, key):
            return None

        def latest_for_user_camera(self, user_id, camera_id):
            return None

        def append(self, event):
            raise RuntimeError("sink unavailable")

    with SQLiteStore(tmp_path / "events.sqlite3") as store:
        users = UserRepository(store)
        users.create("synthetic-user", "Synthetic User")
        queue = QueueRepository(store)
        service = _service(store, events=UnavailableEvents(), queue=queue)
        observations = [s.observation for s in MockVisionProvider(start_at=NOW).observe(until=NOW + timedelta(seconds=2))]
        queued = service.submit(observations, occurred_at=NOW)
        assert queued.state == "queued"
        row = queue.get_by_idempotency(queued.idempotency_key)
        assert row and "payload_json" in row.keys()
        assert "frame" not in row["payload_json"] and "template" not in row["payload_json"]
        sink = InMemoryEventSink()
        sync = QueueSynchronizer(queue, sink)
        assert sync.synchronize(now=NOW) == 1
        assert queue.count(QueueState.SYNCED) == 1
        assert sync.synchronize(now=NOW) == 0
        assert len(sink.payloads) == 1


def test_inactive_user_cannot_match_and_enrollment_retires_metadata(tmp_path):
    with SQLiteStore(tmp_path / "events.sqlite3") as store:
        users = UserRepository(store)
        templates = TemplateMetadataRepository(store)
        enrollment = EnrollmentService(users, templates, compliance_approved=True)
        enrollment.create_user("u-1", "Synthetic User")
        enrollment.register_template_metadata(
            template_id="t-1", user_id="u-1", model_version="mock-1",
            template_version="1", protected_template_hash="synthetic-hash",
        )
        rejected = _service(store).submit(
            [s.observation for s in MockVisionProvider(identity_id="u-1", start_at=NOW).observe(until=NOW + timedelta(seconds=2))],
            occurred_at=NOW,
        )
        assert rejected.reason == "identity-not-authorized"
        enrollment.activate("u-1")
        assert users.get_status("u-1") is UserStatus.ACTIVE
        enrollment.de_enroll("u-1")
        assert users.get_status("u-1") is UserStatus.DEACTIVATED
        assert users.active_user_ids() == set()


def test_opencv_missing_assets_fails_closed(tmp_path):
    provider = OpenCVVisionProvider(model_path=tmp_path / "missing.xml", cv2_module=object())
    samples = provider.observe(until=NOW + timedelta(seconds=1))
    assert len(samples) == 1
    assert samples[0].status is VisionStatus.UNAVAILABLE
    assert samples[0].detail == "model-assets-unavailable"


def test_opencv_camera_unavailable_fails_closed(tmp_path):
    model = tmp_path / "local.xml"
    model.write_text("synthetic model path")

    class Detector:
        def empty(self):
            return False

    class FakeCV:
        def CascadeClassifier(self, path):
            return Detector()

        def VideoCapture(self, index):
            raise AssertionError("camera should not open after detector failure")

    # A detector that loads but a camera that cannot open is a safe unavailable state.
    class LoadedDetector(Detector):
        def empty(self):
            return False

    class LoadedCV(FakeCV):
        def CascadeClassifier(self, path):
            return LoadedDetector()

        def VideoCapture(self, index):
            return type("Capture", (), {"isOpened": lambda self: False})()

    samples = OpenCVVisionProvider(model_path=model, cv2_module=LoadedCV()).observe(until=NOW)
    assert samples[0].status is VisionStatus.UNAVAILABLE
    assert samples[0].detail == "camera-unavailable"


def test_opencv_model_digest_and_path_policy_fail_closed(tmp_path):
    model_dir = tmp_path / "approved"
    model_dir.mkdir()
    model = model_dir / "local.xml"
    model.write_bytes(b"synthetic model")
    digest = hashlib.sha256(model.read_bytes()).hexdigest()

    class LoadedDetector:
        def empty(self):
            return False

    class LoadedCV:
        def CascadeClassifier(self, path):
            return LoadedDetector()

        def VideoCapture(self, index):
            return type("Capture", (), {"isOpened": lambda self: False})()

    provider = OpenCVVisionProvider(
        model_path=model,
        approved_model_directory=model_dir,
        expected_model_sha256=digest,
        cv2_module=LoadedCV(),
    )
    assert provider.model_digest == digest
    assert provider.model_version == f"sha256:{digest}"
    assert provider.observe(until=NOW)[0].detail == "camera-unavailable"

    model.write_bytes(b"modified model")
    mismatch = OpenCVVisionProvider(
        model_path=model,
        approved_model_directory=model_dir,
        expected_model_sha256=digest,
        cv2_module=LoadedCV(),
    )
    assert mismatch.model_digest is None
    assert mismatch.observe(until=NOW)[0].detail == "model-assets-unavailable"


def test_opencv_rejects_symlink_model_asset_when_supported(tmp_path):
    target = tmp_path / "target.xml"
    target.write_text("synthetic")
    link = tmp_path / "link.xml"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        return
    provider = OpenCVVisionProvider(model_path=link, cv2_module=object())
    assert provider.model_digest is None
    assert provider.observe(until=NOW)[0].detail == "model-assets-unavailable"


def test_de_enrollment_cleanup_removes_local_sensitive_records_and_keeps_audit(tmp_path):
    with SQLiteStore(tmp_path / "de-enroll.sqlite3") as store:
        users = UserRepository(store)
        templates = TemplateMetadataRepository(store)
        audit = AuditRepository(store)
        retention = RetentionService(RetentionRepository(store), audit, users)
        enrollment = EnrollmentService(users, templates, audit, retention, compliance_approved=True)
        enrollment.create_user("u-delete", "Synthetic User", actor_id="enrollment-admin")
        enrollment.register_template_metadata(
            template_id="t-delete", user_id="u-delete", model_version="m",
            template_version="1", protected_template_hash="hash", actor_id="enrollment-admin",
        )
        enrollment.activate("u-delete", actor_id="enrollment-admin")
        service = _service(store)
        observations = [s.observation for s in MockVisionProvider(identity_id="u-delete", start_at=NOW).observe(until=NOW + timedelta(seconds=2))]
        assert service.submit(observations, occurred_at=NOW).state == "recorded"
        enrollment.de_enroll("u-delete", actor_id="enrollment-admin")
        assert EventRepository(store).list_events() == []
        assert SuppressionRepository(store).latest_for_user_camera("u-delete", "cam-a") is None
        assert store.connection.execute("SELECT COUNT(*) FROM biometric_template_metadata").fetchone()[0] == 0
        assert any(row["action"] == "retention:de-enrollment-cleanup" for row in audit.list_events())


def test_synchronizer_reclaims_expired_manual_claim_after_crash(tmp_path):
    with SQLiteStore(tmp_path / "queue-reclaim.sqlite3") as store:
        queue = QueueRepository(store)
        queue.enqueue("q-reclaim", "key-reclaim", {"event_id": "e-reclaim", "idempotency_key": "key-reclaim"}, enqueued_at=NOW)
        queue.claim_pending(now=NOW, lease_seconds=5, lease_owner="crashed-worker")
        sink = InMemoryEventSink()
        synchronizer = QueueSynchronizer(queue, sink, lease_seconds=5)
        assert synchronizer.synchronize(now=NOW + timedelta(seconds=5)) == 1
        assert queue.count(QueueState.SYNCED) == 1
        assert len(sink.payloads) == 1
