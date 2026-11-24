"""Persistent consent receipts and one-use challenges; no image data is stored here."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import time


Subject = tuple[int, int, int]  # VK community, sender, conversation
CHALLENGE_TTL_SECONDS = 24 * 60 * 60


def _now() -> float:
    return time.time()


def _timestamp(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="microseconds")


def _subject(subject: Subject) -> Subject:
    if len(subject) != 3 or any(type(value) is not int or value <= 0 for value in subject):
        raise ValueError("Consent subject must contain three positive integer IDs")
    return tuple(subject)


class ConsentStore:
    """SQLite-backed consent state, bound to the exact text shown to a user.

    Each operation uses its own connection. A version is the SHA-256 digest of
    the full UTF-8 consent text, including its policy URL and button wording.
    Acceptance and revocation receipts remain available for the operator;
    current permission and a pending challenge are tracked separately.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("Consent database must be a regular file")
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        with self._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS consent_documents (
                    version TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    policy_url TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS consent_current (
                    group_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    peer_id INTEGER NOT NULL,
                    version TEXT REFERENCES consent_documents(version),
                    accepted_at TEXT,
                    PRIMARY KEY (group_id, user_id, peer_id)
                );
                CREATE TABLE IF NOT EXISTS consent_pending (
                    group_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    peer_id INTEGER NOT NULL,
                    version TEXT NOT NULL REFERENCES consent_documents(version),
                    token_hash TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    PRIMARY KEY (group_id, user_id, peer_id)
                );
                CREATE TABLE IF NOT EXISTS consent_events (
                    id INTEGER PRIMARY KEY,
                    group_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    peer_id INTEGER NOT NULL,
                    event TEXT NOT NULL CHECK (event IN ('accepted', 'revoked')),
                    version TEXT NOT NULL REFERENCES consent_documents(version),
                    occurred_at TEXT NOT NULL
                );
            """)

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA journal_mode = DELETE")
            db.execute("PRAGMA synchronous = FULL")
            with db:
                yield db
        finally:
            db.close()

    def issue_challenge(self, subject: Subject, version: str, text: str, policy_url: str) -> str:
        """Replace this subject's pending challenge and return its opaque token."""
        subject = _subject(subject)
        if not isinstance(text, str) or hashlib.sha256(text.encode("utf-8")).hexdigest() != version:
            raise ValueError("Consent version must be the SHA-256 digest of its text")
        if not isinstance(policy_url, str) or not policy_url:
            raise ValueError("A consent document must include its policy URL")
        now = _now()
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            document = db.execute(
                "SELECT text, policy_url FROM consent_documents WHERE version = ?", (version,),
            ).fetchone()
            if document is not None and document != (text, policy_url):
                raise ValueError("An existing consent document is immutable")
            db.execute(
                "INSERT OR IGNORE INTO consent_documents VALUES (?, ?, ?, ?)",
                (version, text, policy_url, _timestamp(now)),
            )
            db.execute(
                """INSERT INTO consent_pending VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (group_id, user_id, peer_id) DO UPDATE SET
                   version = excluded.version, token_hash = excluded.token_hash,
                   expires_at = excluded.expires_at""",
                (*subject, version, token_hash, now + CHALLENGE_TTL_SECONDS),
            )
        return token

    def has_consent(self, subject: Subject, version: str) -> bool:
        subject = _subject(subject)
        with self._connection() as db:
            row = db.execute(
                """SELECT version FROM consent_current
                   WHERE group_id = ? AND user_id = ? AND peer_id = ?""", subject,
            ).fetchone()
        return row is not None and row[0] is not None and row[0] == version

    def accept(self, subject: Subject, version: str, token: str) -> bool:
        """Consume a current, unexpired challenge and record affirmative consent."""
        subject = _subject(subject)
        if not isinstance(token, str) or not token or len(token) > 200:
            return False
        now = _now()
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            pending = db.execute(
                """SELECT version, token_hash, expires_at FROM consent_pending
                   WHERE group_id = ? AND user_id = ? AND peer_id = ?""", subject,
            ).fetchone()
            if pending is None:
                return False
            if pending[2] <= now:
                db.execute(
                    "DELETE FROM consent_pending WHERE group_id = ? AND user_id = ? AND peer_id = ?",
                    subject,
                )
                return False
            if pending[0] != version or not hmac.compare_digest(pending[1], token_hash):
                return False
            accepted_at = _timestamp(now)
            db.execute(
                """INSERT INTO consent_current VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (group_id, user_id, peer_id) DO UPDATE SET
                   version = excluded.version, accepted_at = excluded.accepted_at""",
                (*subject, version, accepted_at),
            )
            db.execute(
                "INSERT INTO consent_events (group_id, user_id, peer_id, event, version, occurred_at) "
                "VALUES (?, ?, ?, 'accepted', ?, ?)", (*subject, version, accepted_at),
            )
            db.execute(
                "DELETE FROM consent_pending WHERE group_id = ? AND user_id = ? AND peer_id = ?",
                subject,
            )
        return True

    def revoke(self, subject: Subject) -> bool:
        """Clear permission and pending challenges, preserving historical receipts."""
        subject = _subject(subject)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                """SELECT version FROM consent_current
                   WHERE group_id = ? AND user_id = ? AND peer_id = ?""", subject,
            ).fetchone()
            db.execute(
                "DELETE FROM consent_pending WHERE group_id = ? AND user_id = ? AND peer_id = ?",
                subject,
            )
            active = current is not None and current[0] is not None
            if active:
                db.execute(
                    "INSERT INTO consent_events (group_id, user_id, peer_id, event, version, occurred_at) "
                    "VALUES (?, ?, ?, 'revoked', ?, ?)", (*subject, current[0], _timestamp(_now())),
                )
                db.execute(
                    """UPDATE consent_current SET version = NULL, accepted_at = NULL
                       WHERE group_id = ? AND user_id = ? AND peer_id = ?""", subject,
                )
        return active
