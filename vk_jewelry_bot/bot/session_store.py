"""Durable opt-in bot sessions, scoped to community, sender and conversation."""
from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import sqlite3
import stat


Subject = tuple[int, int, int]


def _subject(subject: Subject) -> Subject:
    if (not isinstance(subject, tuple) or len(subject) != 3
            or any(type(value) is not int or value <= 0 for value in subject)):
        raise ValueError("Session subject must contain three positive integer IDs")
    return subject


class SessionStore:
    """Persist active sessions without expiry or photograph data.

    Every operation owns its SQLite connection. A write transaction serializes
    concurrent starts so that they all receive the same active session token.
    Finishing a session invalidates the token also for work already in flight.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("Session database must be a regular file")
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        with self._connection() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    group_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    peer_id INTEGER NOT NULL,
                    token TEXT NOT NULL,
                    PRIMARY KEY (group_id, user_id, peer_id)
                )
            """)

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute("PRAGMA journal_mode = DELETE")
            db.execute("PRAGMA synchronous = FULL")
            with db:
                yield db
        finally:
            db.close()

    def get_token(self, subject: Subject) -> str | None:
        """Return the active token, or None when the bot session is closed."""
        subject = _subject(subject)
        with self._connection() as db:
            row = db.execute(
                "SELECT token FROM sessions WHERE group_id = ? AND user_id = ? AND peer_id = ?",
                subject,
            ).fetchone()
        return row[0] if row is not None else None

    def start(self, subject: Subject) -> str:
        """Open a session, preserving the token when it is already open."""
        subject = _subject(subject)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT token FROM sessions WHERE group_id = ? AND user_id = ? AND peer_id = ?",
                subject,
            ).fetchone()
            if row is not None:
                return row[0]
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)", (*subject, token))
        return token

    def finish(self, subject: Subject) -> None:
        """Close a session; closing an inactive session has no effect."""
        subject = _subject(subject)
        with self._connection() as db:
            db.execute(
                "DELETE FROM sessions WHERE group_id = ? AND user_id = ? AND peer_id = ?",
                subject,
            )

    def is_current(self, subject: Subject, token: str) -> bool:
        """Reject tokens from finished sessions, including after a new start."""
        subject = _subject(subject)
        return isinstance(token, str) and bool(token) and self.get_token(subject) == token
