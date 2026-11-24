"""Consent receipts remain durable; stale or foreign buttons never grant access."""
import hashlib
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor

import pytest

from bot import consent_store
from bot.consent_store import ConsentStore


SUBJECT = (1, 123, 123)
POLICY_URL = "https://example.org/privacy"
TEXT = "Согласие. Политика: " + POLICY_URL + ". Нажмите «Начать»."
VERSION = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()


@pytest.fixture
def store(tmp_path):
    return ConsentStore(tmp_path / "private" / "consent.sqlite3")


def issue(store, subject=SUBJECT, text=TEXT):
    version = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return version, store.issue_challenge(subject, version, text, POLICY_URL)


def events(store):
    with sqlite3.connect(store.path) as db:
        return db.execute("SELECT event, version FROM consent_events ORDER BY id").fetchall()


def test_acceptance_survives_store_and_connection_recreation(store):
    version, token = issue(store)
    assert not store.has_consent(SUBJECT, version)
    assert store.accept(SUBJECT, version, token)
    restored = ConsentStore(store.path)
    assert restored.has_consent(SUBJECT, version)
    assert events(restored) == [("accepted", version)]
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT text, policy_url FROM consent_documents").fetchall() == [(TEXT, POLICY_URL)]
        timestamp = db.execute("SELECT occurred_at FROM consent_events").fetchone()[0]
        assert timestamp.endswith("+00:00")


@pytest.mark.parametrize("other", [(2, 123, 123), (1, 456, 123), (1, 123, 456)])
def test_button_cannot_be_used_by_a_different_subject(store, other):
    version, token = issue(store)
    assert not store.accept(other, version, token)
    assert not store.has_consent(other, version)
    assert store.accept(SUBJECT, version, token)


def test_invalid_or_wrong_version_buttons_do_not_consume_valid_challenge(store):
    version, token = issue(store)
    assert not store.accept(SUBJECT, version, "forged")
    assert not store.accept(SUBJECT, "outdated-version", token)
    assert not store.accept(SUBJECT, version, None)
    assert not store.accept(SUBJECT, version, "x" * 201)
    assert store.accept(SUBJECT, version, token)
    assert not store.accept(SUBJECT, version, token)
    assert events(store) == [("accepted", version)]


def test_expired_challenge_cannot_be_accepted(store, monkeypatch):
    monkeypatch.setattr(consent_store, "_now", lambda: 1_000)
    version, token = issue(store)
    monkeypatch.setattr(consent_store, "_now", lambda: 1_000 + consent_store.CHALLENGE_TTL_SECONDS)
    assert not store.accept(SUBJECT, version, token)
    assert not store.has_consent(SUBJECT, version)
    assert events(store) == []
    # Rolling back the clock cannot revive an expired challenge.
    monkeypatch.setattr(consent_store, "_now", lambda: 1_000)
    assert not store.accept(SUBJECT, version, token)


def test_newly_issued_button_invalidates_previous_button(store):
    version, old_token = issue(store)
    _, new_token = issue(store)
    assert old_token != new_token
    assert not store.accept(SUBJECT, version, old_token)
    assert store.accept(SUBJECT, version, new_token)
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM consent_pending").fetchone()[0] == 0


def test_revocation_invalidates_access_and_all_pending_buttons(store):
    version, token = issue(store)
    assert store.accept(SUBJECT, version, token)
    _, pending = issue(store)
    assert store.revoke(SUBJECT)
    assert not ConsentStore(store.path).has_consent(SUBJECT, version)
    assert not store.accept(SUBJECT, version, pending)
    assert not store.revoke(SUBJECT)
    assert events(store) == [("accepted", version), ("revoked", version)]
    _, fresh = issue(store)
    assert store.accept(SUBJECT, version, fresh)
    assert store.has_consent(SUBJECT, version)


def test_revoking_a_pending_only_subject_does_not_fabricate_receipt(store):
    version, token = issue(store)
    assert not store.revoke(SUBJECT)
    assert not store.accept(SUBJECT, version, token)
    assert events(store) == []


def test_previous_text_consent_does_not_grant_access_to_a_new_version(store):
    version, token = issue(store)
    assert store.accept(SUBJECT, version, token)
    updated, new_token = issue(store, text=TEXT + " Изменённые условия.")
    assert not store.has_consent(SUBJECT, updated)
    assert store.accept(SUBJECT, updated, new_token)
    assert not store.has_consent(SUBJECT, version)
    assert store.has_consent(SUBJECT, updated)
    assert events(store) == [("accepted", version), ("accepted", updated)]


def test_documents_cannot_be_modified_under_the_same_version(store):
    issue(store)
    with pytest.raises(ValueError, match="immutable"):
        store.issue_challenge(SUBJECT, VERSION, TEXT, "https://example.org/changed")
    with pytest.raises(ValueError, match="SHA-256"):
        store.issue_challenge(SUBJECT, VERSION, "Other text", POLICY_URL)


def test_database_is_private_even_when_reopened_after_broader_mode(store):
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    store.path.chmod(0o644)
    ConsentStore(store.path)
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


def test_symlink_database_path_is_refused(tmp_path):
    target = tmp_path / "target"
    target.write_text("not a database")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(OSError):
        ConsentStore(link)
    assert target.read_text() == "not a database"


@pytest.mark.parametrize("subject", [(0, 123, 123), (1, -1, 123), (True, 123, 123), (1, 123)])
def test_invalid_subject_is_refused(store, subject):
    with pytest.raises(ValueError):
        issue(store, subject=subject)


def test_only_one_concurrent_click_consumes_a_challenge(store):
    version, token = issue(store)
    with ThreadPoolExecutor(max_workers=6) as executor:
        accepted = list(executor.map(lambda _: store.accept(SUBJECT, version, token), range(6)))
    assert accepted.count(True) == 1
    assert events(store) == [("accepted", version)]


def test_database_failures_propagate_instead_of_granting_access(store):
    store.path.write_bytes(b"not a SQLite database")
    with pytest.raises(sqlite3.DatabaseError):
        store.has_consent(SUBJECT, VERSION)
