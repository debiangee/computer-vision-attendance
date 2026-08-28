"""Optional local OpenCV adapter; it never downloads models or stores frames."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Any

from ..domain import RecognitionObservation
from .local_matcher import MatchResult, crop_frame
from .protocol import VisionSample, VisionStatus

UTC = timezone.utc
IdentityResolver = Callable[[Any, tuple[int, int, int, int]], str | None]
MatchResultResolver = Callable[[Any, tuple[int, int, int, int]], MatchResult]
LivenessChecker = Callable[[Any, tuple[int, int, int, int]], bool]


class OpenCVVisionProvider:
    """Use a caller-supplied OpenCV-compatible detector and local camera only.

    The optional demo liveness callback is a named presence heuristic and is
    never presented as production presentation-attack detection (PAD).
    """

    def __init__(
        self,
        *,
        camera_index: int = 0,
        model_path: str | Path | None = None,
        approved_model_directory: str | Path | None = None,
        expected_model_sha256: str | None = None,
        identity_resolver: IdentityResolver | None = None,
        match_result_resolver: MatchResultResolver | None = None,
        liveness_checker: LivenessChecker | None = None,
        min_face_size: int = 40,
        cv2_module: Any | None = None,
        capture_factory: Callable[[int], Any] | None = None,
    ) -> None:
        if camera_index < 0:
            raise ValueError("camera_index must be non-negative")
        self.camera_index = camera_index
        self.model_path = Path(model_path) if model_path else None
        self.approved_model_directory = Path(approved_model_directory) if approved_model_directory else None
        self.expected_model_sha256 = expected_model_sha256.strip().lower() if expected_model_sha256 else None
        self._model_digest: str | None = None
        self.identity_resolver = identity_resolver
        self.match_result_resolver = match_result_resolver
        self.liveness_checker = liveness_checker
        self.min_face_size = min_face_size
        self._cv2 = cv2_module
        self._capture_factory = capture_factory

    @property
    def model_digest(self) -> str | None:
        try:
            return self._verify_model_asset()
        except OSError:
            return None

    @property
    def model_version(self) -> str:
        digest = self.model_digest
        return f"sha256:{digest}" if digest else "unavailable"

    def _verify_model_asset(self) -> str:
        path = self.model_path
        if path is None or path.is_symlink() or not path.is_file():
            raise OSError("model asset is not a regular file")
        if self.approved_model_directory is not None:
            approved = self.approved_model_directory.resolve(strict=True)
            if not approved.is_dir():
                raise OSError("approved model directory is unavailable")
            resolved = path.resolve(strict=True)
            try:
                resolved.relative_to(approved)
            except ValueError as exc:
                raise OSError("model asset is outside approved directory") from exc
            path = resolved
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if self.expected_model_sha256 and not hmac.compare_digest(actual, self.expected_model_sha256):
            raise OSError("model asset digest mismatch")
        self._model_digest = actual
        return actual

    def observe(self, *, until: datetime, interval_seconds: float = 0.2) -> tuple[VisionSample, ...]:
        if interval_seconds < 0:
            raise ValueError("interval_seconds must be non-negative")
        observed_at = datetime.now(UTC)
        prepared = self._prepare_camera(observed_at)
        if prepared is None:
            return (self._unavailable(observed_at, self._last_failure),)
        cv2, detector, capture = prepared
        samples: list[VisionSample] = []
        deadline = _utc(until)
        try:
            while len(samples) < 5 and datetime.now(UTC) <= deadline:
                ok, frame = capture.read()
                now = datetime.now(UTC)
                if not ok or frame is None:
                    samples.append(self._unavailable(now, "camera-read-failed"))
                    break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = tuple(detector.detectMultiScale(gray, 1.1, 5))
                samples.append(self._sample(frame, gray, faces, now))
                if interval_seconds:
                    remaining = (deadline - datetime.now(UTC)).total_seconds()
                    if remaining > 0:
                        sleep(min(interval_seconds, remaining))
        except Exception:
            samples.append(self._unavailable(datetime.now(UTC), "camera-processing-failed"))
        finally:
            _release(capture)
        return tuple(samples)

    def capture_enrollment_samples(
        self,
        *,
        sample_count: int = 5,
        until: datetime,
        interval_seconds: float = 0.2,
    ) -> tuple[Any, ...]:
        """Capture only bounded, valid grayscale face crops for demo enrollment."""
        if not 1 <= sample_count <= 5 or interval_seconds < 0:
            raise ValueError("enrollment capture bounds are invalid")
        observed_at = datetime.now(UTC)
        prepared = self._prepare_camera(observed_at)
        if prepared is None:
            return ()
        cv2, detector, capture = prepared
        crops: list[Any] = []
        deadline = _utc(until)
        try:
            while len(crops) < sample_count and datetime.now(UTC) <= deadline:
                ok, frame = capture.read()
                if not ok or frame is None:
                    break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = tuple(detector.detectMultiScale(gray, 1.1, 5))
                if len(faces) != 1:
                    continue
                face = tuple(int(value) for value in faces[0])
                _, _, width, height = face
                if width < self.min_face_size or height < self.min_face_size:
                    continue
                if not self.liveness_checker or not self.liveness_checker(frame, face):
                    continue
                try:
                    crops.append(crop_frame(gray, face))
                except (TypeError, ValueError):
                    continue
                if interval_seconds:
                    remaining = (deadline - datetime.now(UTC)).total_seconds()
                    if remaining > 0:
                        sleep(min(interval_seconds, remaining))
        except Exception:
            return ()
        finally:
            _release(capture)
        return tuple(crops)

    def _prepare_camera(self, observed_at: datetime) -> tuple[Any, Any, Any] | None:
        self._last_failure = "camera-unavailable"
        cv2 = self._cv2
        if cv2 is None:
            try:
                import cv2 as cv2_import  # optional dependency, never installed here
                cv2 = cv2_import
            except ImportError:
                self._last_failure = "opencv-unavailable"
                return None
        try:
            self._verify_model_asset()
        except OSError:
            self._last_failure = "model-assets-unavailable"
            return None
        try:
            detector = cv2.CascadeClassifier(str(self.model_path))
            if detector.empty():
                self._last_failure = "model-assets-unavailable"
                return None
            capture = (self._capture_factory or cv2.VideoCapture)(self.camera_index)
            if not capture or not capture.isOpened():
                _release(capture)
                self._last_failure = "camera-unavailable"
                return None
            return cv2, detector, capture
        except Exception:
            self._last_failure = "camera-unavailable"
            return None

    def _sample(self, frame: Any, gray: Any, faces: tuple[Any, ...], observed_at: datetime) -> VisionSample:
        if not faces:
            return _sample(observed_at, None, False, False, VisionStatus.NO_FACE)
        if len(faces) > 1:
            return _sample(observed_at, None, False, True, VisionStatus.MULTIPLE_FACES)
        face = tuple(int(value) for value in faces[0])
        _, _, width, height = face
        quality = width >= self.min_face_size and height >= self.min_face_size
        if not quality:
            return _sample(observed_at, None, False, False, VisionStatus.LOW_QUALITY)
        if not self.liveness_checker or not self.liveness_checker(frame, face):
            return _sample(observed_at, None, False, True, VisionStatus.LIVENESS_FAILED)
        try:
            if self.match_result_resolver:
                result = self.match_result_resolver(gray, face)
                if result.status == "ambiguous":
                    return _sample(observed_at, None, True, True, VisionStatus.AMBIGUOUS)
                identity = result.identity_id
            else:
                identity = self.identity_resolver(frame, face) if self.identity_resolver else None
        except (TypeError, ValueError, IndexError):
            identity = None
        if not identity:
            return _sample(observed_at, None, True, True, VisionStatus.UNKNOWN)
        return _sample(observed_at, identity, True, True, VisionStatus.RECOGNIZED)

    def _unavailable(self, observed_at: datetime, detail: str) -> VisionSample:
        return _unavailable(observed_at, detail)


def demo_presence_liveness_checker(frame: Any, face: tuple[int, int, int, int]) -> bool:
    """Return true for a valid in-frame face presence; this is not production PAD."""
    try:
        x, y, width, height = (int(value) for value in face)
        shape = tuple(int(value) for value in frame.shape)
        return len(shape) >= 2 and x >= 0 and y >= 0 and width > 0 and height > 0 and x + width <= shape[1] and y + height <= shape[0]
    except (AttributeError, TypeError, ValueError, IndexError):
        return False


def _sample(observed_at: datetime, identity: str | None, liveness: bool, quality: bool, status: VisionStatus) -> VisionSample:
    observation = RecognitionObservation(observed_at, identity, liveness, quality)
    return VisionSample(observed_at, observation, status)


def _unavailable(observed_at: datetime, detail: str) -> VisionSample:
    return VisionSample(
        observed_at=observed_at,
        observation=RecognitionObservation(observed_at, None, False, False),
        status=VisionStatus.UNAVAILABLE,
        detail=detail,
    )


def _release(capture: Any) -> None:
    try:
        capture.release()
    except Exception:
        pass


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
