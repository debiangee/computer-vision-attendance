import pytest

from lobby_attendance.config import Settings
from lobby_attendance.errors import AuthorizationError, ConfigurationError
from lobby_attendance.rbac import Permission, Principal, Role, is_authorized, require_permission


def test_settings_safe_defaults_and_environment_overrides():
    settings = Settings.from_env({
        "LOBBY_ATTENDANCE_SITE_ID": "site-a",
        "LOBBY_ATTENDANCE_CAMERA_ID": "cam-a",
        "LOBBY_ATTENDANCE_TIMEZONE": "America/New_York",
        "LOBBY_ATTENDANCE_DEVELOPMENT_MOCK_VISION": "true",
    })
    assert settings.cooldown_seconds == 300
    assert settings.stable_window_size == 5
    assert settings.stable_required_count == 3
    assert settings.retention_days == 90
    assert settings.queue_lease_seconds == 300
    assert settings.development_mock_vision is True
    assert settings.compliance_approved is False
    assert settings.development_mock_compliance_approval is False


def test_storage_encryption_settings_are_environment_backed():
    key = "ab" * 32
    settings = Settings.from_env({
        "LOBBY_ATTENDANCE_STORAGE_ENCRYPTION_KEY": key,
        "LOBBY_ATTENDANCE_STORAGE_ENCRYPTION_REQUIRED": "true",
    })
    assert settings.storage_encryption_key == key
    assert settings.storage_encryption_required is True

    with pytest.raises(ConfigurationError):
        Settings(storage_encryption_required=True).validate()
    with pytest.raises(ConfigurationError):
        Settings(storage_encryption_key="not-a-key").validate()


def test_settings_from_env_uses_slotted_instance_defaults():
    settings = Settings.from_env({})
    assert settings.database_path.name == "lobby_attendance.sqlite3"
    assert settings.timezone == "UTC"


def test_invalid_settings_fail_closed():
    with pytest.raises(ConfigurationError):
        Settings.from_env({"LOBBY_ATTENDANCE_TIMEZONE": "not/a-timezone"})
    with pytest.raises(ConfigurationError):
        Settings.from_env({"LOBBY_ATTENDANCE_COOLDOWN_SECONDS": "not-an-int"})


def test_rbac_is_default_deny_and_roles_are_separated():
    kiosk = Principal.with_roles("service", [Role.KIOSK_SERVICE])
    assert is_authorized(kiosk, Permission.APPEND_RECOGNITION_EVENT)
    assert not is_authorized(kiosk, Permission.MANAGE_RBAC)
    assert not is_authorized(None, Permission.VIEW_AUDIT)
    with pytest.raises(AuthorizationError):
        require_permission(kiosk, Permission.VIEW_AUDIT)

    enrollment = Principal.with_roles("admin", [Role.ENROLLMENT_ADMINISTRATOR])
    assert is_authorized(enrollment, Permission.MANAGE_ENROLLMENT)
    assert not is_authorized(enrollment, Permission.EXPORT_ATTENDANCE)
