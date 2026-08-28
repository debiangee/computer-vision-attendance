"""Validated environment-backed configuration with safe local defaults."""

from __future__ import annotations

import os
import re
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ConfigurationError


_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path = Path("data/lobby_attendance.sqlite3")
    storage_encryption_key: str | None = None
    storage_encryption_required: bool = False
    site_id: str = "local-site"
    camera_id: str = "lobby-camera"
    timezone: str = "UTC"
    cooldown_seconds: int = 300
    stable_window_size: int = 5
    stable_required_count: int = 3
    queue_max_age_seconds: int = 86_400
    queue_max_size: int = 10_000
    queue_lease_seconds: int = 300
    retention_days: int = 90
    capture_max_samples: int = 5
    sampling_interval_seconds: float = 0.2
    interaction_timeout_seconds: float = 2.0
    executive_demo_mode: bool = False
    camera_index: int = 0
    matcher_version: str = "local-gray-crop-v1"
    matcher_crop_size: int = 32
    matcher_threshold: float = 0.35
    matcher_margin: float = 0.04
    enrollment_sample_count: int = 5
    demo_liveness_enabled: bool = False
    vision_model_path: Path | None = None
    vision_model_directory: Path | None = None
    vision_model_sha256: str | None = None
    development_mock_vision: bool = False
    compliance_approved: bool = False
    development_mock_compliance_approval: bool = False

    def validate(self) -> "Settings":
        if not self.site_id.strip() or not self.camera_id.strip():
            raise ConfigurationError("site_id and camera_id must not be empty")
        if self.storage_encryption_key is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", self.storage_encryption_key.strip()):
            raise ConfigurationError("storage_encryption_key must be a 64-character hexadecimal key")
        if self.storage_encryption_required and not self.storage_encryption_key:
            raise ConfigurationError("storage_encryption_key is required for encrypted storage")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ConfigurationError("timezone must be a valid IANA timezone") from exc
        if self.cooldown_seconds < 0:
            raise ConfigurationError("cooldown_seconds must be non-negative")
        if self.stable_window_size != 5 or self.stable_required_count != 3:
            if self.stable_required_count <= 0 or self.stable_required_count > self.stable_window_size:
                raise ConfigurationError("stable_required_count must be within the stable window")
        if self.stable_window_size <= 0:
            raise ConfigurationError("stable_window_size must be positive")
        if self.queue_max_age_seconds <= 0 or self.queue_max_size <= 0 or self.queue_lease_seconds <= 0:
            raise ConfigurationError("queue limits and lease must be positive")
        if self.retention_days <= 0:
            raise ConfigurationError("retention_days must be positive")
        if self.vision_model_sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", self.vision_model_sha256.strip()):
            raise ConfigurationError("vision_model_sha256 must be a 64-character SHA-256 digest")
        if not 1 <= self.capture_max_samples <= 5:
            raise ConfigurationError("capture_max_samples must be between 1 and 5")
        if self.sampling_interval_seconds < 0 or self.interaction_timeout_seconds <= 0:
            raise ConfigurationError("sampling interval must be non-negative and timeout positive")
        if not isinstance(self.camera_index, int) or isinstance(self.camera_index, bool) or self.camera_index < 0:
            raise ConfigurationError("camera_index must be a non-negative integer")
        if not isinstance(self.matcher_version, str) or not self.matcher_version.strip() or len(self.matcher_version) > 128:
            raise ConfigurationError("matcher_version must be a bounded non-empty string")
        if not isinstance(self.matcher_crop_size, int) or isinstance(self.matcher_crop_size, bool) or not 8 <= self.matcher_crop_size <= 128:
            raise ConfigurationError("matcher_crop_size must be an integer between 8 and 128")
        try:
            matcher_values_finite = all(math.isfinite(float(value)) for value in (self.matcher_threshold, self.matcher_margin))
        except (TypeError, ValueError):
            matcher_values_finite = False
        if not matcher_values_finite:
            raise ConfigurationError("matcher threshold and margin must be finite")
        if self.matcher_threshold <= 0 or self.matcher_margin < 0:
            raise ConfigurationError("matcher threshold must be positive and margin non-negative")
        if not isinstance(self.enrollment_sample_count, int) or isinstance(self.enrollment_sample_count, bool) or not 1 <= self.enrollment_sample_count <= 5:
            raise ConfigurationError("enrollment_sample_count must be an integer between 1 and 5")
        if not isinstance(self.executive_demo_mode, bool) or not isinstance(self.demo_liveness_enabled, bool):
            raise ConfigurationError("demo mode and liveness settings must be boolean")
        return self

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ
        defaults = cls()
        settings = cls(
            database_path=Path(env.get("LOBBY_ATTENDANCE_DATABASE_PATH", defaults.database_path)),
            storage_encryption_key=(env.get("LOBBY_ATTENDANCE_STORAGE_ENCRYPTION_KEY") or defaults.storage_encryption_key),
            storage_encryption_required=_bool(
                env, "LOBBY_ATTENDANCE_STORAGE_ENCRYPTION_REQUIRED", defaults.storage_encryption_required,
            ),
            site_id=env.get("LOBBY_ATTENDANCE_SITE_ID", defaults.site_id),
            camera_id=env.get("LOBBY_ATTENDANCE_CAMERA_ID", defaults.camera_id),
            timezone=env.get("LOBBY_ATTENDANCE_TIMEZONE", defaults.timezone),
            cooldown_seconds=_int(env, "LOBBY_ATTENDANCE_COOLDOWN_SECONDS", defaults.cooldown_seconds),
            stable_window_size=_int(env, "LOBBY_ATTENDANCE_STABLE_WINDOW_SIZE", defaults.stable_window_size),
            stable_required_count=_int(env, "LOBBY_ATTENDANCE_STABLE_REQUIRED_COUNT", defaults.stable_required_count),
            queue_max_age_seconds=_int(env, "LOBBY_ATTENDANCE_QUEUE_MAX_AGE_SECONDS", defaults.queue_max_age_seconds),
            queue_max_size=_int(env, "LOBBY_ATTENDANCE_QUEUE_MAX_SIZE", defaults.queue_max_size),
            queue_lease_seconds=_int(env, "LOBBY_ATTENDANCE_QUEUE_LEASE_SECONDS", defaults.queue_lease_seconds),
            retention_days=_int(env, "LOBBY_ATTENDANCE_RETENTION_DAYS", defaults.retention_days),
            capture_max_samples=_int(env, "LOBBY_ATTENDANCE_CAPTURE_MAX_SAMPLES", defaults.capture_max_samples),
            sampling_interval_seconds=_float(env, "LOBBY_ATTENDANCE_SAMPLING_INTERVAL_SECONDS", defaults.sampling_interval_seconds),
            interaction_timeout_seconds=_float(env, "LOBBY_ATTENDANCE_INTERACTION_TIMEOUT_SECONDS", defaults.interaction_timeout_seconds),
            executive_demo_mode=_bool(env, "LOBBY_ATTENDANCE_EXECUTIVE_DEMO_MODE", defaults.executive_demo_mode),
            camera_index=_int(env, "LOBBY_ATTENDANCE_CAMERA_INDEX", defaults.camera_index),
            matcher_version=env.get("LOBBY_ATTENDANCE_MATCHER_VERSION", defaults.matcher_version),
            matcher_crop_size=_int(env, "LOBBY_ATTENDANCE_MATCHER_CROP_SIZE", defaults.matcher_crop_size),
            matcher_threshold=_float(env, "LOBBY_ATTENDANCE_MATCHER_THRESHOLD", defaults.matcher_threshold),
            matcher_margin=_float(env, "LOBBY_ATTENDANCE_MATCHER_MARGIN", defaults.matcher_margin),
            enrollment_sample_count=_int(env, "LOBBY_ATTENDANCE_ENROLLMENT_SAMPLE_COUNT", defaults.enrollment_sample_count),
            demo_liveness_enabled=_bool(env, "LOBBY_ATTENDANCE_DEMO_LIVENESS_ENABLED", defaults.demo_liveness_enabled),
            vision_model_path=Path(env["LOBBY_ATTENDANCE_VISION_MODEL_PATH"]) if env.get("LOBBY_ATTENDANCE_VISION_MODEL_PATH") else defaults.vision_model_path,
            vision_model_directory=Path(env["LOBBY_ATTENDANCE_VISION_MODEL_DIRECTORY"]) if env.get("LOBBY_ATTENDANCE_VISION_MODEL_DIRECTORY") else defaults.vision_model_directory,
            vision_model_sha256=(env.get("LOBBY_ATTENDANCE_VISION_MODEL_SHA256") or defaults.vision_model_sha256),
            development_mock_vision=_bool(env, "LOBBY_ATTENDANCE_DEVELOPMENT_MOCK_VISION", defaults.development_mock_vision),
            compliance_approved=_bool(env, "LOBBY_ATTENDANCE_COMPLIANCE_APPROVED", defaults.compliance_approved),
            development_mock_compliance_approval=_bool(
                env, "LOBBY_ATTENDANCE_DEVELOPMENT_MOCK_COMPLIANCE_APPROVAL",
                defaults.development_mock_compliance_approval,
            ),
        )
        return settings.validate()


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc


def _bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    raise ConfigurationError(f"{name} must be a boolean")
