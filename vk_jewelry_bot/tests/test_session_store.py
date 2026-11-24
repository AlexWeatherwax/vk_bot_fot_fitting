"""Session lifetime is durable, explicitly bounded and safe across threads."""
from concurrent.futures import ThreadPoolExecutor
import os
import sqlite3
import stat

import pytest

from bot.session_store import SessionStore


SUBJECT = (1, 123, 123)


@pytest.fixture
def store(tmp_path):
    return SessionStore(tmp_path / "data" / "sessions" / "sessions.sqlite3")


def test_session_survives_recreation_and_start_is_idempotent(store):
    assert store.get_token(SUBJECT) is None
    token = store.start(SUBJECT)
    assert isinstance(token, str) and token
    assert store.start(SUBJECT) == token
    restored = SessionStore(store.path)
    assert restored.get_token(SUBJECT) == token
    assert restored.start(SUBJECT) == token
    assert restored.is_current(SUBJECT, token)


def test_finish_invalidates_inflight_token_and_new_start_has_a_distinct_token(store):
    old_token = store.start(SUBJECT)
    assert store.finish(SUBJECT) is None
    assert store.get_token(SUBJECT) is None
    assert not store.is_current(SUBJECT, old_token)
    assert store.finish(SUBJECT) is None
    restored = SessionStore(store.path)
    assert restored.get_token(SUBJECT) is None
    new_token = restored.start(SUBJECT)
    assert new_token != old_token
    assert restored.is_current(SUBJECT, new_token)
    assert store.is_current(SUBJECT, new_token)
    assert not store.is_current(SUBJECT, old_token)


@pytest.mark.parametrize("other", [(2, 123, 123), (1, 456, 123), (1, 123, 456)])
def test_every_subject_component_separates_sessions(store, other):
    token = store.start(SUBJECT)
    assert store.get_token(other) is None
    assert not store.is_current(other, token)
    other_token = store.start(other)
    assert other_token != token
    store.finish(SUBJECT)
    assert store.get_token(SUBJECT) is None
    assert store.get_token(other) == other_token


def test_concurrent_starts_return_one_token_even_from_separate_store_instances(store):
    stores = [SessionStore(store.path) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as executor:
        tokens = list(executor.map(lambda instance: instance.start(SUBJECT), stores))
    assert len(set(tokens)) == 1
    assert store.get_token(SUBJECT) == tokens[0]
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1


@pytest.mark.parametrize("token", [None, "", "forged", 1, True, [], {}])
def test_noncurrent_or_malformed_token_is_rejected(store, token):
    assert not store.is_current(SUBJECT, token)
    store.start(SUBJECT)
    assert not store.is_current(SUBJECT, token)


@pytest.mark.parametrize("subject", [
    None, (), (1,), (1, 2), (1, 2, 3, 4), "123", [1, 2, 3],
    (0, 123, 123), (1, -1, 123), (1, 123, 0),
    (True, 123, 123), (1, False, 123), (1, 123, True),
    (1.0, 123, 123), (1, "123", 123), (1, 123, None),
])
@pytest.mark.parametrize("operation", ["get_token", "start", "finish", "is_current"])
def test_all_operations_reject_invalid_subjects(store, subject, operation):
    args = (subject, "token") if operation == "is_current" else (subject,)
    with pytest.raises(ValueError, match="three positive integer IDs"):
        getattr(store, operation)(*args)
    assert store.get_token(SUBJECT) is None


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_database_and_new_sessions_directory_are_private(store):
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700
    store.path.chmod(0o644)
    SessionStore(store.path)
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="O_NOFOLLOW is unavailable")
def test_database_symlink_is_refused_without_touching_its_target(tmp_path):
    target = tmp_path / "target"
    target.write_text("keep this file")
    target.chmod(0o644)
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(OSError):
        SessionStore(link)
    assert target.read_text() == "keep this file"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


@pytest.mark.parametrize("operation", ["get_token", "start", "finish", "is_current"])
def test_database_errors_propagate_instead_of_granting_session_access(store, operation):
    token = store.start(SUBJECT)
    store.path.write_bytes(b"not a SQLite database")
    args = (SUBJECT, token) if operation == "is_current" else (SUBJECT,)
    with pytest.raises(sqlite3.DatabaseError):
        getattr(store, operation)(*args)
