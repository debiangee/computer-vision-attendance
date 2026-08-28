"""Dependency-free, in-memory normalized grayscale crop matcher for the demo.

This is deliberately a small demonstration adapter, not a production biometric
matcher or presentation-attack detector. Templates are process memory only and
are never serialized or included in logs or API responses.
"""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from threading import RLock
from typing import Any, Iterable

MATCHER_VERSION = "local-gray-crop-v1"


@dataclass(frozen=True, slots=True)
class MatcherTemplateMetadata:
    """Safe metadata returned after server-side template creation."""

    matcher_version: str
    protected_template_hash: str


@dataclass(frozen=True, slots=True)
class MatchResult:
    identity_id: str | None
    status: str


class LocalMatcher:
    """Thread-safe registry of normalized grayscale templates kept only in RAM."""

    def __init__(
        self,
        *,
        matcher_version: str = MATCHER_VERSION,
        crop_size: int = 32,
        threshold: float = 0.35,
        margin: float = 0.04,
    ) -> None:
        if not isinstance(matcher_version, str) or not matcher_version.strip() or len(matcher_version) > 128:
            raise ValueError("matcher_version must be a bounded non-empty string")
        if not isinstance(crop_size, int) or isinstance(crop_size, bool) or not 8 <= crop_size <= 128:
            raise ValueError("crop_size must be between 8 and 128")
        if not math.isfinite(float(threshold)) or threshold <= 0:
            raise ValueError("threshold must be finite and positive")
        if not math.isfinite(float(margin)) or margin < 0:
            raise ValueError("margin must be finite and non-negative")
        self.matcher_version = matcher_version.strip()
        self.crop_size = crop_size
        self.threshold = float(threshold)
        self.margin = float(margin)
        self._templates: dict[str, tuple[tuple[float, ...], bool, str]] = {}
        self._lock = RLock()

    @property
    def template_count(self) -> int:
        with self._lock:
            return sum(1 for _identity, (_template, enabled, _digest) in self._templates.items() if enabled)

    def register(
        self,
        identity_id: str,
        crops: Iterable[Any],
        *,
        enabled: bool = True,
    ) -> MatcherTemplateMetadata:
        if not isinstance(identity_id, str) or not identity_id.strip() or len(identity_id) > 128:
            raise ValueError("identity_id must be a bounded non-empty string")
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        normalized = [normalize_grayscale_crop(crop, self.crop_size) for crop in crops]
        if not 1 <= len(normalized) <= 5:
            raise ValueError("one to five enrollment crops are required")
        vector = tuple(sum(values) / len(values) for values in zip(*normalized))
        vector = _normalize_vector(vector)
        digest = _template_hash(self.matcher_version, vector)
        with self._lock:
            self._templates[identity_id.strip()] = (vector, enabled, digest)
        return MatcherTemplateMetadata(self.matcher_version, digest)

    def enable(self, identity_id: str) -> bool:
        with self._lock:
            entry = self._templates.get(identity_id)
            if entry is None:
                return False
            self._templates[identity_id] = (entry[0], True, entry[2])
            return True

    def disable(self, identity_id: str) -> bool:
        with self._lock:
            entry = self._templates.get(identity_id)
            if entry is None:
                return False
            self._templates[identity_id] = (entry[0], False, entry[2])
            return True

    def remove(self, identity_id: str) -> bool:
        with self._lock:
            return self._templates.pop(identity_id, None) is not None

    invalidate = remove

    def remove_all(self) -> int:
        with self._lock:
            count = len(self._templates)
            self._templates.clear()
            return count

    def has_enabled(self, identity_id: str) -> bool:
        with self._lock:
            entry = self._templates.get(identity_id)
            return bool(entry and entry[1])

    def identity_ids(self) -> tuple[str, ...]:
        """Return registry identities for internal lifecycle cleanup only."""
        with self._lock:
            return tuple(self._templates)

    def match(self, crop: Any) -> MatchResult:
        normalized = normalize_grayscale_crop(crop, self.crop_size)
        with self._lock:
            candidates = [
                (identity_id, template)
                for identity_id, (template, enabled, _digest) in self._templates.items()
                if enabled
            ]
        if not candidates:
            return MatchResult(None, "unknown")
        ranked = sorted(((_distance(normalized, template), identity_id) for identity_id, template in candidates))
        best_distance, best_identity = ranked[0]
        if best_distance > self.threshold:
            return MatchResult(None, "unknown")
        if len(ranked) > 1 and ranked[1][0] - best_distance < self.margin:
            return MatchResult(None, "ambiguous")
        return MatchResult(best_identity, "recognized")

    def resolve(self, frame: Any, face: tuple[int, int, int, int]) -> str | None:
        result = self.resolve_result(frame, face)
        return result.identity_id

    def resolve_result(self, frame: Any, face: tuple[int, int, int, int]) -> MatchResult:
        return self.match(crop_frame(frame, face))


def normalize_grayscale_crop(crop: Any, crop_size: int) -> tuple[float, ...]:
    """Validate, resize, and standardize a finite 2-D grayscale crop."""
    rows, height, width = _matrix(crop)
    if height <= 0 or width <= 0:
        raise ValueError("crop must be non-empty")
    resized: list[float] = []
    for target_y in range(crop_size):
        source_y = min(height - 1, (target_y * height) // crop_size)
        for target_x in range(crop_size):
            source_x = min(width - 1, (target_x * width) // crop_size)
            resized.append(rows[source_y][source_x])
    return _normalize_vector(tuple(resized))


def crop_frame(frame: Any, face: tuple[int, int, int, int]) -> Any:
    """Extract a bounded grayscale crop without retaining or serializing the frame."""
    if not isinstance(face, (tuple, list)) or len(face) != 4:
        raise ValueError("face must be an x, y, width, height tuple")
    x, y, width, height = (int(value) for value in face)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError("face bounds are invalid")
    rows, frame_height, frame_width = _matrix(frame)
    if x + width > frame_width or y + height > frame_height:
        raise ValueError("face bounds exceed frame")
    return tuple(tuple(rows[row][x : x + width]) for row in range(y, y + height))


def _matrix(value: Any) -> tuple[list[list[float]], int, int]:
    shape = getattr(value, "shape", None)
    if shape is not None:
        try:
            dimensions = tuple(int(item) for item in shape)
        except (TypeError, ValueError):
            dimensions = ()
        if len(dimensions) != 2:
            raise ValueError("crop/frame must be a 2-D grayscale matrix")
    try:
        raw_rows = list(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("crop/frame must be a 2-D grayscale matrix") from exc
    if not raw_rows:
        raise ValueError("crop/frame must be non-empty")
    rows: list[list[float]] = []
    width: int | None = None
    for raw_row in raw_rows:
        try:
            row = [float(item) for item in raw_row]
        except (TypeError, ValueError) as exc:
            raise ValueError("crop/frame must contain numeric pixels") from exc
        if width is None:
            width = len(row)
        if not row or len(row) != width:
            raise ValueError("crop/frame rows must have equal width")
        if any(not math.isfinite(item) for item in row):
            raise ValueError("crop/frame pixels must be finite")
        rows.append(row)
    return rows, len(rows), width or 0


def _normalize_vector(values: tuple[float, ...]) -> tuple[float, ...]:
    if not values or any(not math.isfinite(value) for value in values):
        raise ValueError("crop values must be finite")
    mean = sum(values) / len(values)
    centered = tuple(value - mean for value in values)
    variance = sum(value * value for value in centered) / len(centered)
    if not math.isfinite(variance) or variance <= 1e-12:
        raise ValueError("crop variance must be positive")
    scale = math.sqrt(variance)
    return tuple(value / scale for value in centered)


def _distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)) / len(left))


def _template_hash(version: str, vector: tuple[float, ...]) -> str:
    digest = hashlib.sha256()
    digest.update(version.encode("utf-8"))
    digest.update(b"\0")
    for value in vector:
        digest.update(struct.pack("!d", value))
    return digest.hexdigest()
