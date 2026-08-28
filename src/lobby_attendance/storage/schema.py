"""Versioned SQLite migrations for the local-first event store."""

from __future__ import annotations

MIGRATIONS: tuple[tuple[int, str], ...] = (
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('active', 'suspended', 'deactivated')),
            enrolled_at TEXT NOT NULL,
            deactivated_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rbac_assignments (
            user_id TEXT NOT NULL REFERENCES users(user_id),
            role TEXT NOT NULL,
            assigned_at TEXT NOT NULL,
            assigned_by TEXT,
            PRIMARY KEY (user_id, role)
        );
        CREATE TABLE IF NOT EXISTS biometric_template_metadata (
            template_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(user_id),
            model_version TEXT NOT NULL,
            template_version TEXT NOT NULL,
            template_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            retired_at TEXT
        );
        CREATE TABLE IF NOT EXISTS recognition_events (
            event_id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            user_id TEXT NOT NULL REFERENCES users(user_id),
            site_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            source TEXT NOT NULL,
            model_version TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_recognition_events_person_camera_time
            ON recognition_events(user_id, camera_id, occurred_at);
        CREATE TABLE IF NOT EXISTS suppression_records (
            suppression_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            suppressed_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            source_event_id TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS local_queue_items (
            queue_id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            state TEXT NOT NULL CHECK (state IN ('pending', 'in-flight', 'synced', 'failed', 'expired')),
            enqueued_at TEXT NOT NULL,
            available_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL,
            last_error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_local_queue_state_available
            ON local_queue_items(state, available_at);
        CREATE TABLE IF NOT EXISTS audit_events (
            audit_id TEXT PRIMARY KEY,
            occurred_at TEXT NOT NULL,
            actor_id TEXT,
            action TEXT NOT NULL,
            outcome TEXT NOT NULL CHECK (outcome IN ('success', 'denied', 'failure')),
            resource_type TEXT NOT NULL,
            resource_id TEXT,
            metadata_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS policy_config_metadata (
            config_key TEXT PRIMARY KEY,
            config_value_json TEXT NOT NULL,
            version TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        """,
    ),
    (
        2,
        """
        CREATE TRIGGER IF NOT EXISTS recognition_events_no_update
        BEFORE UPDATE ON recognition_events
        BEGIN
            SELECT RAISE(ABORT, 'recognition_events are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS recognition_events_no_delete
        BEFORE DELETE ON recognition_events
        BEGIN
            SELECT RAISE(ABORT, 'recognition_events are append-only');
        END;
        """,
    ),
    (
        3,
        """
        ALTER TABLE local_queue_items ADD COLUMN lease_until TEXT;
        ALTER TABLE local_queue_items ADD COLUMN lease_owner TEXT;
        CREATE INDEX IF NOT EXISTS idx_local_queue_in_flight_lease
            ON local_queue_items(state, lease_until);
        """,
    ),
    (
        4,
        """
        ALTER TABLE recognition_events ADD COLUMN storage_state TEXT NOT NULL DEFAULT 'recorded';
        ALTER TABLE recognition_events ADD COLUMN correlation_id TEXT;
        ALTER TABLE recognition_events ADD COLUMN audit_metadata_json TEXT NOT NULL DEFAULT '{}';
        """,
    ),
    (
        5,
        """
        CREATE TABLE IF NOT EXISTS attendance_corrections (
            correction_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL REFERENCES recognition_events(event_id),
            occurred_at TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            before_json TEXT NOT NULL,
            after_json TEXT NOT NULL,
            audit_metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attendance_corrections_event_time
            ON attendance_corrections(event_id, occurred_at);
        """,
    ),
    (
        6,
        """
        CREATE TABLE IF NOT EXISTS auth_token_revocations (
            token_id TEXT PRIMARY KEY,
            revoked_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_by TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_auth_token_revocations_expiry
            ON auth_token_revocations(expires_at);
        """,
    ),
)
