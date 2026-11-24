"""The bot is quiet outside explicit sessions, including stale photo work."""
import asyncio
import copy
import json
import sys

import pytest

from bot.consent import ConsentGate
from bot.consent_store import ConsentStore
from bot.session_store import SessionStore
from bot.sessions import SessionGate
from .test_handlers import FakeMessage, call, dialog, selected


@pytest.fixture
def session_dialog(dialog, tmp_path, monkeypatch):
    app = sys.modules['bot.app']
    store = SessionStore(tmp_path/'sessions.sqlite3')
    gate = SessionGate(store, 456)
    monkeypatch.setattr(app, 'session_gate', gate)
    dialog.session = gate
    dialog.session_store = store
    dialog.app = app
    dialog.session_path = tmp_path/'sessions.sqlite3'
    return dialog


def labels(message):
    keyboard = json.loads(message.answers[-1][1]['keyboard'])
    return [button['action']['label'] for row in keyboard['buttons'] for button in row]


QUIET_MESSAGES = [
    'Привет!', 'Здравствуйте', 'hello', 'КАТАЛОГ!', 'СЕРЬГИ',
    'Сколько стоят эти серьги?', 'Позови мастера', 'СОГЛАСИЕ',
    'Завершить примерку', '',
]


@pytest.mark.parametrize('entry', ['search', 'photo', 'start', 'catalog'])
@pytest.mark.parametrize('text', QUIET_MESSAGES)
def test_inactive_session_does_not_answer_or_handle_photos(session_dialog, monkeypatch, entry, text):
    d = session_dialog

    async def forbidden(*args, **kwargs):
        pytest.fail('Inactive sessions must not enter consent, media, or master handling')

    monkeypatch.setattr(d.app.consent_gate, 'intercept', forbidden)
    monkeypatch.setattr(d.photo, 'download_first_photo', forbidden)
    monkeypatch.setattr(d.search, 'request_master', forbidden)
    monkeypatch.setattr(d.photo, 'request_master', forbidden)
    handler = {'search': d.search.search_handler, 'photo': d.photo.photo_handler,
               'start': d.common.start_handler, 'catalog': d.common.catalog_list_handler}[entry]
    message = call(handler, text, photo=b'not-to-be-downloaded')
    assert message.answers == []
    assert d.session.current_token(message) is None
    assert selected(d) == []


@pytest.mark.parametrize('start', ['Начать', 'НАЧАТЬ!', '/START', ' «СтАрТ» '])
@pytest.mark.parametrize('finish', ['Завершить примерку', ' ЗАВЕРШИТЬ\u00a0ПРИМЕРКУ! ',
                                    '/finish', 'Закончить примерку'])
def test_start_and_finish_boundaries_and_keyboard(session_dialog, start, finish):
    d = session_dialog
    started = call(d.search.search_handler, start)
    token = d.session.current_token(started)
    assert token
    assert started.answers[-1][0].startswith('Привет!')
    assert labels(started) == ['Завершить примерку']
    call(d.search.search_handler, 'Серьги Луна')
    assert selected(d) == ['earrings']
    listing = call(d.photo.photo_handler, 'КАТАЛОГ!')
    assert 'Кулон Огонь' in listing.answers[-1][0]
    assert selected(d) == ['earrings']

    ended = call(d.photo.photo_handler, finish, photo=b'ignored-photo')
    assert len(ended.answers) == 1
    assert 'Примерка завершена' in ended.answers[0][0]
    assert labels(ended) == ['Начать']
    assert selected(d) == []
    assert d.session.current_token(ended) is None
    assert not d.session.is_current(ended, token)
    assert call(d.search.search_handler, finish).answers == []
    for text in QUIET_MESSAGES:
        assert call(d.search.search_handler, text, photo=b'ignored').answers == []

    reopened = call(d.search.search_handler, 'НАЧАТЬ')
    assert d.session.current_token(reopened) != token
    assert labels(reopened) == ['Завершить примерку']


def test_session_survives_gate_restart_and_new_begin_is_idempotent(session_dialog, monkeypatch):
    d = session_dialog
    begin = call(d.search.search_handler, 'Начать')
    token = d.session.current_token(begin)
    call(d.search.search_handler, 'Серьги Луна')
    replacement = SessionGate(SessionStore(d.session_path), 456)
    monkeypatch.setattr(d.app, 'session_gate', replacement)
    assert replacement.current_token(begin) == token
    listing = call(d.photo.photo_handler, 'СЕРЬГИ!')
    assert 'Серьги Луна' in listing.answers[-1][0]
    call(d.photo.photo_handler, 'Начать')
    assert selected(d) == ['earrings']
    assert replacement.current_token(begin) == token
    call(d.photo.photo_handler, 'Завершить примерку')
    assert d.session.current_token(begin) is None


@pytest.mark.parametrize('stage', ['download', 'render', 'upload'])
@pytest.mark.parametrize('reopen_same_payload', [False, True])
def test_finish_suppresses_stale_photos_even_after_new_session_with_identical_state(
        session_dialog, monkeypatch, stage, reopen_same_payload):
    d = session_dialog

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        uploads = []

        async def pause(value):
            entered.set()
            await release.wait()
            return value

        async def download(message):
            return await pause(message.photo) if stage == 'download' else message.photo

        async def render(*args):
            return await pause(b'result-jpeg') if stage == 'render' else b'result-jpeg'

        async def upload(*args):
            uploads.append(args)
            return await pause('photo1_2') if stage == 'upload' else 'photo1_2'

        monkeypatch.setattr(d.photo, 'download_first_photo', download)
        monkeypatch.setattr(d.photo.asyncio, 'to_thread', render)
        monkeypatch.setattr(d.photo, 'upload_photo_for_message', upload)
        await d.search.search_handler(FakeMessage('Начать'))
        await d.search.search_handler(FakeMessage('Серьги Луна'))
        old_state = d.bot.state_dispenser.states[123]
        old_payload = copy.deepcopy(old_state.payload)
        old_message = FakeMessage(photo=b'old-photo')
        old_token = d.session.current_token(old_message)
        task = asyncio.create_task(d.photo.photo_handler(old_message))
        await asyncio.wait_for(entered.wait(), 1)
        ended = FakeMessage('Завершить примерку')
        await d.photo.photo_handler(ended)
        assert 'Примерка завершена' in ended.answers[-1][0]
        assert selected(d) == []
        assert not d.session.is_current(old_message, old_token)
        if reopen_same_payload:
            await d.search.search_handler(FakeMessage('Начать'))
            await d.bot.state_dispenser.set(123, old_state.state, **old_payload)
            assert d.session.current_token(old_message) != old_token
        release.set()
        await asyncio.wait_for(task, 1)
        assert old_message.answers == []
        assert len(uploads) == (1 if stage == 'upload' else 0)
        if reopen_same_payload:
            assert d.bot.state_dispenser.states[123].payload == old_payload
        else:
            assert selected(d) == []

    asyncio.run(scenario())


def test_finish_does_not_revoke_consent_and_begin_reuses_it(session_dialog, tmp_path, monkeypatch):
    d = session_dialog
    gate = ConsentGate(ConsentStore(tmp_path/'consent.sqlite3'), 456)
    monkeypatch.setattr(d.app, 'consent_gate', gate)
    subject = (456, 123, 123)
    challenge = gate.store.issue_challenge(subject, gate.version, gate.text, gate.policy_url)
    assert gate.store.accept(subject, gate.version, challenge)
    call(d.search.search_handler, 'Начать')
    call(d.search.search_handler, 'Серьги Луна')
    call(d.photo.photo_handler, 'Завершить примерку')
    assert gate.store.has_consent(subject, gate.version)
    assert call(d.search.search_handler, 'КАТАЛОГ').answers == []
    reopened = call(d.search.search_handler, 'Начать')
    assert len(reopened.answers) == 1
    assert reopened.answers[0][0].startswith('Привет!')
    assert labels(reopened) == ['Завершить примерку']


def test_revocation_outside_session_is_honoured_silently(session_dialog, tmp_path, monkeypatch):
    d = session_dialog
    gate = ConsentGate(ConsentStore(tmp_path/'consent.sqlite3'), 456)
    monkeypatch.setattr(d.app, 'consent_gate', gate)
    subject = (456, 123, 123)
    challenge = gate.store.issue_challenge(subject, gate.version, gate.text, gate.policy_url)
    assert gate.store.accept(subject, gate.version, challenge)
    message = call(d.search.search_handler, '/ОТОЗВАТЬ СОГЛАСИЕ')
    assert message.answers == []
    assert not gate.store.has_consent(subject, gate.version)
    assert d.session.current_token(message) is None
    assert call(d.search.search_handler, 'Привет').answers == []
    begin = call(d.search.search_handler, 'Начать')
    assert 'СОГЛАСИЕ НА ОБРАБОТКУ' in '\n'.join(t for t, _ in begin.answers)
    assert not gate.store.has_consent(subject, gate.version)


def test_new_session_requires_real_consent_button_and_finish_can_cancel_offer(
        session_dialog, tmp_path, monkeypatch):
    d = session_dialog
    gate = ConsentGate(ConsentStore(tmp_path/'consent.sqlite3'), 456)
    monkeypatch.setattr(d.app, 'consent_gate', gate)
    assert call(d.search.search_handler, 'Здравствуйте', photo=b'photo').answers == []
    begin = call(d.search.search_handler, 'Начать')
    keyboard = json.loads(begin.answers[-1][1]['keyboard'])
    payload = json.loads(keyboard['buttons'][0][0]['action']['payload'])
    assert d.session.current_token(begin)
    assert not gate.is_allowed(begin)
    ended = call(d.search.search_handler, 'Завершить примерку')
    assert 'Примерка завершена' in ended.answers[-1][0]
    assert call(d.search.search_handler, 'Привет').answers == []
    call(d.search.search_handler, 'Начать')
    assert not gate.is_allowed(begin)
    # The first offer was superseded by the second explicit begin.
    click = FakeMessage('Начать')
    click.payload = json.dumps(payload)
    asyncio.run(d.search.search_handler(click))
    assert not gate.is_allowed(click)


def test_finishing_one_user_does_not_close_another(session_dialog):
    d = session_dialog
    first = call(d.search.search_handler, 'Начать')
    second = FakeMessage('Начать')
    second.from_id = second.peer_id = 789
    asyncio.run(d.search.search_handler(second))
    second_token = d.session.current_token(second)
    assert second_token
    call(d.search.search_handler, 'Завершить примерку')
    assert d.session.current_token(first) is None
    assert d.session.current_token(second) == second_token
