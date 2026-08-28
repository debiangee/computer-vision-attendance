"""Audit event values; callers must avoid raw images, templates, and credentials."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from .domain import AuditOutcome


@dataclass(frozen=True, slots=True)
class AuditEvent:
    audit_id: str
    occurred_at: datetime
    actor_id: str | None
    action: str
    outcome: AuditOutcome
    resource_type: str
    resource_id: str | None
    metadata: Mapping[str, str]
