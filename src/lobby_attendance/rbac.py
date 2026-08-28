"""Default-deny RBAC definitions for administrative and kiosk actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import FrozenSet, Iterable

from .errors import AuthorizationError


class Role(StrEnum):
    KIOSK_SERVICE = "kiosk-service"
    ENROLLMENT_ADMINISTRATOR = "enrollment-administrator"
    ATTENDANCE_ADMINISTRATOR = "attendance-administrator"
    AUDITOR = "auditor"
    SYSTEM_OPERATOR = "system-operator"
    RBAC_ADMINISTRATOR = "rbac-administrator"


class Permission(StrEnum):
    APPEND_RECOGNITION_EVENT = "recognition-event:append"
    MANAGE_ENROLLMENT = "enrollment:manage"
    VIEW_ATTENDANCE_EVENTS = "attendance-events:view"
    CORRECT_ATTENDANCE_EVENTS = "attendance-events:correct"
    VIEW_AUDIT = "audit:view"
    MANAGE_DEVICE = "device:manage"
    MANAGE_QUEUE = "queue:manage"
    MANAGE_RBAC = "rbac:manage"
    EXPORT_ATTENDANCE = "attendance-events:export"


ROLE_PERMISSIONS: dict[Role, FrozenSet[Permission]] = {
    Role.KIOSK_SERVICE: frozenset({Permission.APPEND_RECOGNITION_EVENT}),
    Role.ENROLLMENT_ADMINISTRATOR: frozenset({Permission.MANAGE_ENROLLMENT}),
    Role.ATTENDANCE_ADMINISTRATOR: frozenset({Permission.VIEW_ATTENDANCE_EVENTS, Permission.CORRECT_ATTENDANCE_EVENTS, Permission.EXPORT_ATTENDANCE}),
    Role.AUDITOR: frozenset({Permission.VIEW_ATTENDANCE_EVENTS, Permission.VIEW_AUDIT}),
    Role.SYSTEM_OPERATOR: frozenset({Permission.MANAGE_DEVICE, Permission.MANAGE_QUEUE}),
    Role.RBAC_ADMINISTRATOR: frozenset({Permission.MANAGE_RBAC}),
}


ROLE_SEPARATION_CONFLICTS: tuple[frozenset[Role], ...] = (
    frozenset({Role.ENROLLMENT_ADMINISTRATOR, Role.ATTENDANCE_ADMINISTRATOR}),
    frozenset({Role.RBAC_ADMINISTRATOR, Role.ENROLLMENT_ADMINISTRATOR}),
    frozenset({Role.RBAC_ADMINISTRATOR, Role.ATTENDANCE_ADMINISTRATOR}),
    frozenset({Role.RBAC_ADMINISTRATOR, Role.SYSTEM_OPERATOR}),
)


@dataclass(frozen=True, slots=True)
class Principal:
    subject_id: str
    roles: FrozenSet[Role]
    site_ids: FrozenSet[str] = frozenset()
    subject_ids: FrozenSet[str] = frozenset()
    auth_time: datetime | None = None
    token_id: str | None = None
    token_kind: str = "admin"
    authentication_method: str = "legacy"

    @classmethod
    def with_roles(
        cls,
        subject_id: str,
        roles: Iterable[Role],
        *,
        site_ids: Iterable[str] = (),
        subject_ids: Iterable[str] = (),
        auth_time: datetime | None = None,
        token_id: str | None = None,
        token_kind: str = "admin",
        authentication_method: str = "legacy",
    ) -> "Principal":
        return cls(
            subject_id=subject_id,
            roles=frozenset(roles),
            site_ids=frozenset(site_ids),
            subject_ids=frozenset(subject_ids),
            auth_time=auth_time,
            token_id=token_id,
            token_kind=token_kind,
            authentication_method=authentication_method,
        )

    def can_access_site(self, site_id: str) -> bool:
        return site_id in self.site_ids or "*" in self.site_ids

    def can_access_subject(self, subject_id: str) -> bool:
        return subject_id in self.subject_ids or "*" in self.subject_ids


def permissions_for(roles: Iterable[Role]) -> FrozenSet[Permission]:
    permissions: set[Permission] = set()
    for role in roles:
        permissions.update(ROLE_PERMISSIONS.get(role, frozenset()))
    return frozenset(permissions)


def roles_obey_separation(roles: Iterable[Role]) -> bool:
    assigned = frozenset(roles)
    return not any(conflict <= assigned for conflict in ROLE_SEPARATION_CONFLICTS)


def is_authorized(principal: Principal | None, permission: Permission) -> bool:
    if principal is None:
        return False
    return permission in permissions_for(principal.roles)


def require_permission(principal: Principal | None, permission: Permission) -> None:
    if not is_authorized(principal, permission):
        raise AuthorizationError(f"permission denied: {permission.value}")
