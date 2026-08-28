"""SQLite connection and migration lifecycle."""

from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..errors import ConfigurationError
from .schema import MIGRATIONS

UTC = timezone.utc
_ENCRYPTED_MAGIC = b"LOBBYSQL1"
_ENCRYPTED_AAD = b"lobby-attendance-sqlite-v1"


class SQLiteStore:
    """SQLite storage with an optional authenticated encrypted-file envelope.

    With ``encryption_key`` set, the database exists only in process memory and
    is serialized to an AES-GCM envelope on commit/close. This avoids a
    plaintext SQLite database and WAL on disk. Pilot deployment still requires
    approved filesystem, backup, key-custody, and recovery controls.
    """

    def __init__(self, database_path: str | Path, encryption_key: bytes | str | None = None):
        self.database_path = str(database_path)
        self._encrypted_path = None if self.database_path == ":memory:" else Path(self.database_path)
        self._encryption_key = _coerce_key(encryption_key) if encryption_key is not None else None
        if self._encryption_key is not None and self._encrypted_path is None:
            raise ConfigurationError("encrypted storage requires a filesystem database path")
        if self._encrypted_path is not None:
            self._encrypted_path.parent.mkdir(parents=True, exist_ok=True)
        connect_path = ":memory:" if self._encryption_key is not None else self.database_path
        self.connection = sqlite3.connect(connect_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        if self._encryption_key is not None:
            self.connection.execute("PRAGMA journal_mode = MEMORY")
            self.connection.execute("PRAGMA synchronous = FULL")
            self._load_encrypted_database()
        else:
            self.connection.execute("PRAGMA journal_mode = WAL")

    @property
    def encrypted(self) -> bool:
        return self._encryption_key is not None

    def initialize(self) -> None:
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {
            row[0] for row in self.connection.execute("SELECT version FROM schema_migrations")
        }
        for version, sql in MIGRATIONS:
            if version in applied:
                continue
            with self.connection:
                self.connection.executescript(sql)
                self.connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, utc_now_text()),
                )
        self.persist()

    def commit(self) -> None:
        self.connection.commit()
        self.persist()

    def persist(self) -> None:
        if self._encryption_key is None or self._encrypted_path is None:
            return
        try:
            plaintext = self.connection.serialize()
            nonce = secrets.token_bytes(12)
            ciphertext = _aesgcm(self._encryption_key).encrypt(nonce, plaintext, _ENCRYPTED_AAD)
            envelope = _ENCRYPTED_MAGIC + nonce + ciphertext
            temporary = self._encrypted_path.with_name(self._encrypted_path.name + ".tmp")
            with temporary.open("wb") as stream:
                stream.write(envelope)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._encrypted_path)
        except OSError as exc:
            raise ConfigurationError("encrypted storage could not be persisted") from exc

    def close(self) -> None:
        if self.connection is None:
            return
        try:
            if self._encryption_key is not None:
                self.commit()
        finally:
            self.connection.close()
            self.connection = None

    def __enter__(self) -> "SQLiteStore":
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.connection.rollback()
        self.close()

    def _load_encrypted_database(self) -> None:
        if self._encrypted_path is None or not self._encrypted_path.exists():
            return
        try:
            envelope = self._encrypted_path.read_bytes()
            if len(envelope) <= len(_ENCRYPTED_MAGIC) + 12 or not envelope.startswith(_ENCRYPTED_MAGIC):
                raise ValueError("encrypted storage envelope is invalid")
            nonce_start = len(_ENCRYPTED_MAGIC)
            nonce = envelope[nonce_start:nonce_start + 12]
            ciphertext = envelope[nonce_start + 12:]
            plaintext = _aesgcm(self._encryption_key).decrypt(nonce, ciphertext, _ENCRYPTED_AAD)
            self.connection.deserialize(plaintext)
        except (OSError, ValueError) as exc:
            raise ConfigurationError("encrypted storage could not be opened") from exc
        except Exception as exc:
            raise ConfigurationError("encrypted storage authentication failed") from exc


def _coerce_key(value: bytes | str) -> bytes:
    if isinstance(value, str):
        try:
            value = bytes.fromhex(value.strip())
        except ValueError as exc:
            raise ConfigurationError("storage encryption key must be hexadecimal") from exc
    key = bytes(value)
    if len(key) != 32:
        raise ConfigurationError("storage encryption key must be exactly 32 bytes")
    return key


def _aesgcm(key: bytes):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise ConfigurationError("cryptography is required for encrypted storage") from exc
    return AESGCM(key)


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


def datetime_text(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()
