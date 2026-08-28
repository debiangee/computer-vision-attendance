from datetime import datetime, timedelta, timezone

from lobby_attendance.api import create_app
from lobby_attendance.api.auth import TokenBoundary
from lobby_attendance.application import InMemoryEventSink, RecognitionEventService, RecognitionPipeline
from lobby_attendance.config import Settings
from lobby_attendance.domain import RecognitionObservation, UserStatus
from lobby_attendance.rbac import Role
from lobby_attendance.storage import SQLiteStore
from lobby_attendance.storage.repositories import (
    AuditRepository,
    EventRepository,
    QueueRepository,
    SuppressionRepository,
    UserRepository,
)
from lobby_attendance.vision import MockVisionProvider, OpenCVVisionProvider, VisionSample, VisionStatus
from lobby_attendance.vision.local_matcher import LocalMatcher
from lobby_attendance.vision.opencv import demo_presence_liveness_checker

UTC = timezone.utc


class FakeFrame:
    def __init__(self, rows):
        self.rows = tuple(tuple(row) for row in rows)
        self.shape = (len(self.rows), len(self.rows[0]))

    def __iter__(self):
        return iter(self.rows)

    def __getitem__(self, item):
        if isinstance(item, tuple):
            row_slice, column_slice = item
            return tuple(tuple(row[column_slice]) for row in self.rows[row_slice])
        return self.rows[item]


class FakeCapture:
    def __init__(self, frames, opened=True):
        self.frames = list(frames)
        self.opened = opened
        self.released = False

    def isOpened(self):
        return self.opened

    def read(self):
        if not self.frames:
            return False, None
        return True, self.frames.pop(0)

    def release(self):
        self.released = True


class FakeDetector:
    def __init__(self, faces=(1, 1, 8, 8)):
        self.faces = faces

    def empty(self):
        return False

    def detectMultiScale(self, gray, _scale, _neighbors):
        return [self.faces]


class FakeCV:
    COLOR_BGR2GRAY = 0

    def __init__(self, capture):
        self.capture = capture

    def CascadeClassifier(self, _path):
        return FakeDetector()

    def VideoCapture(self, _index):
        return self.capture

    def cvtColor(self, frame, _code):
        return frame


def _frame():
    return FakeFrame([[float((row * 3 + column) % 17) for column in range(12)] for row in range(12)])


def _model(tmp_path):
    path = tmp_path / "model.xml"
    path.write_bytes(b"local-demo-model")
    return path


def test_opencv_enrollment_uses_same_detector_and_releases_camera(tmp_path):
    capture = FakeCapture([_frame(), _frame(), _frame()])
    provider = OpenCVVisionProvider(
        model_path=_model(tmp_path), cv2_module=FakeCV(capture), min_face_size=4,
        liveness_checker=demo_presence_liveness_checker,
    )
    crops = provider.capture_enrollment_samples(
        sample_count=3, until=datetime.now(UTC) + timedelta(seconds=1), interval_seconds=0,
    )
    assert len(crops) == 3
    assert capture.released is True


def test_opencv_camera_and_liveness_failures_release_and_return_no_crops(tmp_path):
    failed_capture = FakeCapture([], opened=True)
    provider = OpenCVVisionProvider(
        model_path=_model(tmp_path), cv2_module=FakeCV(failed_capture), min_face_size=4,
        liveness_checker=lambda _frame, _face: False,
    )
    assert provider.capture_enrollment_samples(
        sample_count=1, until=datetime.now(UTC) + timedelta(seconds=1), interval_seconds=0,
    ) == ()
    assert failed_capture.released is True

    unavailable = FakeCapture([], opened=False)
    unavailable_provider = OpenCVVisionProvider(model_path=_model(tmp_path), cv2_module=FakeCV(unavailable))
    assert unavailable_provider.observe(until=datetime.now(UTC))[0].status is VisionStatus.UNAVAILABLE
    assert unavailable.released is True


def test_demo_api_auth_bounds_safe_responses_reset_and_restart_non_matchability(tmp_path):
    store = SQLiteStore(tmp_path / "demo.sqlite3")
    boundary = TokenBoundary(
        admin_token="admin-secret",
        admin_roles=frozenset({Role.ENROLLMENT_ADMINISTRATOR}),
    )

    class DemoProvider:
        model_version = "demo-model-v1"

        def capture_enrollment_samples(self, *, sample_count, until, interval_seconds):
            assert sample_count == 3
            return [_frame()[1:9, 1:9]] * sample_count

        def observe(self, *, until, interval_seconds=0.2):
            return ()

    settings = Settings(
        database_path=tmp_path / "demo.sqlite3", executive_demo_mode=True,
        demo_liveness_enabled=True, enrollment_sample_count=3,
        compliance_approved=True, sampling_interval_seconds=0,
    )
    app = create_app(settings, store=store, provider=DemoProvider(), token_boundary=boundary, testing=True)
    client = app.test_client()
    assert client.get("/api/admin/demo/status").status_code == 403
    invalid = client.post("/api/admin/demo/enrollment", headers={"Authorization": "Bearer admin-secret"}, json={"user_id": "bad id", "display_name": "x"})
    assert invalid.status_code == 400
    enrolled = client.post(
        "/api/admin/demo/enrollment", headers={"Authorization": "Bearer admin-secret"},
        json={"user_id": "demo-user", "display_name": "Demo User"},
    )
    assert enrolled.status_code == 201
    body = enrolled.get_json()
    assert body == {"user_id": "demo-user", "status": "active", "matcher_version": "local-gray-crop-v1"}
    assert "hash" not in str(body).lower() and "score" not in str(body).lower()
    assert app.extensions["lobby_demo_matcher"].template_count == 1

    reset_missing = client.post("/api/admin/demo/reset", headers={"Authorization": "Bearer admin-secret"}, json={})
    assert reset_missing.status_code == 400

    # A fresh process cannot safely infer which persisted user is the demo
    # enrollment because matcher arrays are intentionally RAM-only.
    store2 = SQLiteStore(tmp_path / "demo.sqlite3")
    app2 = create_app(settings, store=store2, provider=DemoProvider(), token_boundary=boundary, testing=True)
    client2 = app2.test_client()
    status = client2.get("/api/admin/demo/status", headers={"Authorization": "Bearer admin-secret"})
    assert status.status_code == 200
    assert status.get_json()["templates"] == 0
    assert "hash" not in status.get_data(as_text=True).lower()
    restart_reset = client2.post(
        "/api/admin/demo/reset", headers={"Authorization": "Bearer admin-secret"},
        json={"confirm": True},
    )
    assert restart_reset.status_code == 409
    assert restart_reset.get_json() == {
        "error": "operator-action-required",
        "message": "user_id is required after a process restart",
    }
    explicit_reset = client2.post(
        "/api/admin/demo/reset", headers={"Authorization": "Bearer admin-secret"},
        json={"confirm": True, "user_id": "demo-user"},
    )
    assert explicit_reset.status_code == 200 and explicit_reset.get_json() == {"removed": True, "reset": True}
    assert UserRepository(store2).get_status("demo-user") is UserStatus.SUSPENDED
    assert store2.connection.execute(
        "SELECT COUNT(*) FROM biometric_template_metadata WHERE user_id = ? AND retired_at IS NULL",
        ("demo-user",),
    ).fetchone()[0] == 0
    assert any(row["action"] == "enrollment:demo-reset" for row in AuditRepository(store2).list_events())
    store2.close()
    store.close()


def test_demo_metadata_only_registration_cannot_activate(tmp_path):
    store = SQLiteStore(tmp_path / "metadata.sqlite3")
    boundary = TokenBoundary(admin_token="admin", admin_roles=frozenset({Role.ENROLLMENT_ADMINISTRATOR}))
    app = create_app(
        Settings(database_path=tmp_path / "metadata.sqlite3", executive_demo_mode=True, compliance_approved=True),
        store=store, provider=object(), token_boundary=boundary, testing=True,
    )
    client = app.test_client()
    headers = {"Authorization": "Bearer admin"}
    assert client.post("/api/admin/users", headers=headers, json={"user_id": "u-1", "display_name": "User"}).status_code == 201
    assert client.post(
        "/api/admin/templates", headers=headers,
        json={"template_id": "t-1", "user_id": "u-1", "model_version": "m", "template_version": "1", "protected_template_hash": "metadata"},
    ).status_code == 201
    response = client.post("/api/admin/users/u-1/status", headers=headers, json={"status": "active"})
    assert response.status_code == 409
    assert UserRepository(store).get_status("u-1") is UserStatus.SUSPENDED
    store.close()


def test_mixed_invalid_window_rejects_without_event(tmp_path):
    now = datetime.now(UTC)

    class SequenceProvider:
        def observe(self, *, until, interval_seconds=0.2):
            return tuple(
                VisionSample(
                    now,
                    RecognitionObservation(now, "u-1", True, True),
                    status=status,
                )
                for status in (VisionStatus.RECOGNIZED, VisionStatus.NO_FACE, VisionStatus.RECOGNIZED, VisionStatus.RECOGNIZED, VisionStatus.RECOGNIZED)
            )

    with SQLiteStore(tmp_path / "mixed.sqlite3") as store:
        UserRepository(store).create("u-1", "User", status=UserStatus.ACTIVE)
        service = RecognitionEventService(
            UserRepository(store), EventRepository(store), QueueRepository(store),
            suppressions=SuppressionRepository(store), site_id="site", camera_id="camera", model_version="demo",
            compliance_approved=True,
        )
        result = RecognitionPipeline(
            SequenceProvider(), service,
            settings=Settings(executive_demo_mode=True),
        ).process_interaction(occurred_at=now)
        assert result.state == "no-face"
        assert EventRepository(store).list_events() == []


def test_executive_demo_storage_failure_is_unavailable_without_queue_fallback(tmp_path):
    class UnavailableEvents:
        def get_by_idempotency(self, _key):
            return None

        def latest_for_user_camera(self, _user_id, _camera_id):
            return None

        def append(self, _event):
            raise RuntimeError("demo storage unavailable")

    with SQLiteStore(tmp_path / "demo-storage.sqlite3") as store:
        UserRepository(store).create("u-1", "User", status=UserStatus.ACTIVE)
        service = RecognitionEventService(
            UserRepository(store), UnavailableEvents(), None,
            suppressions=SuppressionRepository(store),
            audit=AuditRepository(store), site_id="site", camera_id="camera", model_version="demo",
            compliance_approved=True,
        )
        result = RecognitionPipeline(
            MockVisionProvider(identity_id="u-1"), service,
            settings=Settings(executive_demo_mode=True),
        ).process_interaction()
        assert result.state == "unavailable"
        assert result.submission is not None
        assert result.submission.reason == "event-storage-unavailable"
        assert QueueRepository(store).count() == 0
