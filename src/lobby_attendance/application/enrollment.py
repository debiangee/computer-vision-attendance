"""Enrollment and protected template metadata service boundary."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Iterable

from ..audit import AuditEvent
from ..domain import AuditOutcome, UserStatus
from ..errors import ComplianceApprovalError, TemplateLifecycleError
from ..storage.repositories import AuditRepository, TemplateMetadataRepository, UserRepository
from ..vision.local_matcher import LocalMatcher
from .retention import RetentionService

UTC = timezone.utc


class EnrollmentService:
    """Manage authorized users without accepting or persisting raw face images."""

    def __init__(
        self,
        users: UserRepository,
        templates: TemplateMetadataRepository,
        audit: AuditRepository | None = None,
        retention: RetentionService | None = None,
        compliance_approved: bool = False,
        demo_mode: bool = False,
        matcher: LocalMatcher | None = None,
    ) -> None:
        self.users = users
        self.templates = templates
        self.audit = audit
        self.retention = retention
        self.compliance_approved = compliance_approved
        self.demo_mode = demo_mode
        self.matcher = matcher
        self._demo_lock = RLock()

    def create_user(self, user_id: str, display_name: str, *, actor_id: str | None = None) -> None:
        # A user is not matchable until an administrator explicitly activates enrollment.
        self.users.create(user_id, display_name, status=UserStatus.SUSPENDED)
        self._audit("enrollment:create", actor_id, user_id)

    def register_template_metadata(
        self,
        *,
        template_id: str,
        user_id: str,
        model_version: str,
        template_version: str,
        protected_template_hash: str,
        actor_id: str | None = None,
    ) -> None:
        if not protected_template_hash.strip():
            raise ValueError("protected_template_hash is required")
        if self.users.get_status(user_id) is None:
            raise ValueError("user does not exist")
        self.templates.add(
            template_id, user_id, model_version, template_version,
            protected_template_hash,
        )
        self._audit("enrollment:template-metadata", actor_id, template_id)

    def activate(self, user_id: str, *, actor_id: str | None = None) -> None:
        if not self.compliance_approved:
            self._audit(
                "enrollment:activate",
                actor_id,
                user_id,
                outcome=AuditOutcome.DENIED,
                metadata={"reason": "compliance-not-approved"},
            )
            raise ComplianceApprovalError("biometric activation requires explicit compliance approval")
        if not self.templates.has_active_versioned_template(user_id):
            self._audit(
                "enrollment:activate",
                actor_id,
                user_id,
                outcome=AuditOutcome.DENIED,
                metadata={"reason": "template-lifecycle-incomplete"},
            )
            raise TemplateLifecycleError("biometric activation requires a current protected template")
        if self.demo_mode and (self.matcher is None or not self.matcher.has_enabled(user_id)):
            self._audit(
                "enrollment:activate", actor_id, user_id,
                outcome=AuditOutcome.DENIED,
                metadata={"reason": "demo-registry-incomplete"},
            )
            raise TemplateLifecycleError("demo activation requires an in-memory matcher template")
        self.users.set_status(user_id, UserStatus.ACTIVE)
        self._audit("enrollment:activate", actor_id, user_id)

    def register_demo_template(
        self,
        *,
        template_id: str,
        user_id: str,
        crops: Iterable[Any],
        model_version: str,
        actor_id: str | None = None,
    ) -> str:
        """Create, activate, and audit one real in-memory demo template."""
        if not self.demo_mode or self.matcher is None:
            raise TemplateLifecycleError("demo matcher is not enabled")
        if not self.compliance_approved:
            self._audit(
                "enrollment:demo", actor_id, user_id,
                outcome=AuditOutcome.DENIED,
                metadata={"reason": "compliance-not-approved"},
            )
            raise ComplianceApprovalError("biometric activation requires explicit compliance approval")
        if self.users.get_status(user_id) is None:
            raise ValueError("user does not exist")
        with self._demo_lock:
            metadata = self.matcher.register(user_id, crops, enabled=False)
            try:
                self.templates.add(
                    template_id, user_id, model_version, metadata.matcher_version,
                    metadata.protected_template_hash,
                )
                self.users.set_status(user_id, UserStatus.ACTIVE)
                if not self.matcher.enable(user_id):
                    raise TemplateLifecycleError("demo matcher template could not be activated")
            except Exception:
                self.matcher.remove(user_id)
                raise
            self._audit("enrollment:demo", actor_id, user_id, metadata={"matcher_version": metadata.matcher_version})
            return metadata.matcher_version

    def suspend(self, user_id: str, *, actor_id: str | None = None) -> None:
        if self.matcher:
            self.matcher.remove(user_id)
        self.users.set_status(user_id, UserStatus.SUSPENDED)
        self._audit("enrollment:suspend", actor_id, user_id)

    def reset_demo(self, user_id: str, *, actor_id: str | None = None) -> bool:
        """Revoke one demo enrollment without deleting its attendance history."""
        if not self.demo_mode:
            raise TemplateLifecycleError("demo matcher is not enabled")
        with self._demo_lock:
            removed = self.matcher.remove(user_id) if self.matcher else False
            row = self.users.get(user_id)
            if row is None:
                return removed
            if row["status"] != UserStatus.DEACTIVATED.value:
                self.users.set_status(user_id, UserStatus.SUSPENDED)
            self.templates.retire_for_user(user_id)
            self._audit(
                "enrollment:demo-reset", actor_id, user_id,
                metadata={"matcher_removed": str(bool(removed)).lower()},
            )
            return True

    def de_enroll(self, user_id: str, *, actor_id: str | None = None) -> None:
        now = datetime.now(UTC)
        if self.matcher:
            self.matcher.remove(user_id)
        self.users.set_status(user_id, UserStatus.DEACTIVATED, deactivated_at=now)
        self.templates.retire_for_user(user_id, retired_at=now)
        self._audit("enrollment:de-enroll", actor_id, user_id)
        if self.retention:
            self.retention.cleanup_de_enrollment(
                user_id, actor_id=actor_id or "enrollment-service", now=now,
            )

    def _audit(
        self, action: str, actor_id: str | None, resource_id: str,
        *, outcome: AuditOutcome = AuditOutcome.SUCCESS,
        metadata: dict[str, str] | None = None,
    ) -> None:
        if self.audit:
            occurred_at = datetime.now(UTC)
            self.audit.append(AuditEvent(
                audit_id=hashlib.sha256(f"{action}\x1f{resource_id}\x1f{occurred_at.isoformat()}".encode()).hexdigest()[:32],
                occurred_at=occurred_at,
                actor_id=actor_id,
                action=action,
                outcome=outcome,
                resource_type="enrollment",
                resource_id=resource_id,
                metadata=metadata or {},
            ))
