"""Consent is an explicit action, is durable, and gates every photo path."""
import asyncio
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from bot.consent import ConsentGate
import bot.consent as consent_module
from bot.consent_store import ConsentStore
from .test_handlers import FakeMessage, FakeStateDispenser, dialog


class Message(FakeMessage):
    def __init__(self, text="", photo=None, *, payload=None, user=123, peer=123):
        super().__init__(text, photo)
        self.from_id = user
        self.peer_id = peer
        self.payload = payload


def button(message):
    """Read the same VK text button that a client would display and send."""
    with_keyboard = [options for _, options in message.answers if options.get("keyboard")]
    assert with_keyboard, "The consent text must carry its affirmative button."
    keyboard = with_keyboard[-1]["keyboard"]
    keyboard = json.loads(keyboard) if isinstance(keyboard, str) else keyboard
    assert keyboard.get("inline") is True
    actions = [entry["action"] for row in keyboard["buttons"] for entry in row]
    affirmative = [action for action in actions if action.get("label") == "Начать"]
    assert len(affirmative) == 1
    assert affirmative[0]["type"] == "text"
    payload = affirmative[0]["payload"]
    return json.loads(payload) if isinstance(payload, str) else payload


@pytest.fixture
def consent_env(tmp_path, monkeypatch):
    store = ConsentStore(tmp_path / "consent.sqlite3")
    gate = ConsentGate(store, group_id=456)
    bot = SimpleNamespace(state_dispenser=FakeStateDispenser())
    common = ModuleType("bot.handlers.common")

    async def welcome(message):
        await message.answer("WELCOME")

    common.send_welcome = welcome
    monkeypatch.setitem(sys.modules, "bot.handlers.common", common)
    return SimpleNamespace(store=store, gate=gate, bot=bot, path=tmp_path / "consent.sqlite3")


async def accept(env, *, user=123, peer=123):
    offer = Message("Начать", user=user, peer=peer)
    assert await env.gate.intercept(env.bot, offer) is True
    payload = button(offer)
    click = Message("Начать", payload=json.dumps(payload), user=user, peer=peer)
    assert await env.gate.intercept(env.bot, click) is True
    assert env.store.has_consent((456, user, peer), env.gate.version)
    return click, payload


@pytest.mark.parametrize("text,photo", [("Начать", None), ("каталог", None), ("Серьги Луна", None), ("", b"unsolicited-photo")])
def test_first_contact_offers_consent_and_does_not_infer_acceptance(consent_env, text, photo):
    message = Message(text, photo)
    consumed = asyncio.run(consent_env.gate.intercept(consent_env.bot, message))
    assert consumed is True
    assert "СОГЛАСИЕ НА ОБРАБОТКУ ПЕРСОНАЛЬНЫХ ДАННЫХ" in "\n".join(text for text, _ in message.answers)
    payload = button(message)
    assert payload["action"] == "accept_consent"
    assert payload["version"] == consent_env.gate.version
    assert payload["token"]
    assert not consent_env.store.has_consent((456, 123, 123), consent_env.gate.version)
    assert "WELCOME" not in [text for text, _ in message.answers]


def test_button_acceptance_is_durable_and_next_command_is_allowed(consent_env):
    async def scenario():
        await consent_env.bot.state_dispenser.set(123, "waiting", item_ids=["old-selection"])
        click, _ = await accept(consent_env)
        assert click.answers[-1][0] == "WELCOME"
        assert await consent_env.bot.state_dispenser.get(123) is None

        reloaded = ConsentGate(ConsentStore(consent_env.path), group_id=456)
        catalog_request = Message("каталог")
        assert await reloaded.intercept(consent_env.bot, catalog_request) is False
        assert catalog_request.answers == []

    asyncio.run(scenario())


def test_updated_consent_document_requires_new_affirmative_action(consent_env, monkeypatch):
    async def scenario():
        await accept(consent_env)
        monkeypatch.setattr(consent_module, "CONSENT_TEXT", consent_module.CONSENT_TEXT + "\n\nОбновлённая редакция.")
        revised = ConsentGate(consent_env.store, group_id=456)
        assert revised.version != consent_env.gate.version
        message = Message("каталог")
        assert await revised.intercept(consent_env.bot, message) is True
        assert button(message)["version"] == revised.version
        assert not consent_env.store.has_consent((456, 123, 123), revised.version)

    asyncio.run(scenario())


def test_disclaimer_names_operator_vk_policy_and_actual_start_button(consent_env):
    text = consent_env.gate.text
    assert "Павленко Т.В." in text
    assert "263207534488" in text
    assert "https://vk.com/privacy" in text
    assert "Отозвать согласие" in text
    assert "«Начать»" in text
    assert "вставитьссылку" not in text
    assert "указатьканал" not in text


@pytest.mark.parametrize("payload", [None, "not json", "[]", "null", "true", "123", '{"action":"accept_consent"}', '{"action":"accept_consent","version":"old","token":"invented"}'])
def test_typed_start_and_invalid_payload_cannot_bypass_consent(consent_env, payload):
    message = Message("Начать", payload=payload)
    assert asyncio.run(consent_env.gate.intercept(consent_env.bot, message)) is True
    assert not consent_env.store.has_consent((456, 123, 123), consent_env.gate.version)
    assert "WELCOME" not in [text for text, _ in message.answers]


def test_button_copied_to_another_user_cannot_grant_consent(consent_env):
    async def scenario():
        offer = Message("начать")
        await consent_env.gate.intercept(consent_env.bot, offer)
        copied = Message("Начать", payload=json.dumps(button(offer)), user=124, peer=124)
        assert await consent_env.gate.intercept(consent_env.bot, copied) is True
        assert not consent_env.store.has_consent((456, 124, 124), consent_env.gate.version)
        assert not consent_env.store.has_consent((456, 123, 123), consent_env.gate.version)
        assert "WELCOME" not in [text for text, _ in copied.answers]

    asyncio.run(scenario())


def test_old_offer_cannot_be_accepted_after_new_offer(consent_env):
    async def scenario():
        first = Message("привет")
        second = Message("каталог")
        await consent_env.gate.intercept(consent_env.bot, first)
        await consent_env.gate.intercept(consent_env.bot, second)
        old_click = Message("Начать", payload=json.dumps(button(first)))
        assert await consent_env.gate.intercept(consent_env.bot, old_click) is True
        assert not consent_env.store.has_consent((456, 123, 123), consent_env.gate.version)
        assert "WELCOME" not in [text for text, _ in old_click.answers]

    asyncio.run(scenario())


@pytest.mark.parametrize("command", ["Отозвать согласие", "  ОТОЗВАТЬ   СОГЛАСИЕ  ",
                                     "Отозвать согласие!", "/ОТОЗВАТЬ СОГЛАСИЕ",
                                     " «ОтОзВаТь\u00a0СОГЛАСИЕ!» "])
def test_withdrawal_clears_selection_and_blocks_next_photo(consent_env, command):
    async def scenario():
        _, old_payload = await accept(consent_env)
        await consent_env.bot.state_dispenser.set(123, "waiting", item_ids=["selected"])
        withdrawal = Message(command)
        assert await consent_env.gate.intercept(consent_env.bot, withdrawal) is True
        assert not consent_env.store.has_consent((456, 123, 123), consent_env.gate.version)
        assert await consent_env.bot.state_dispenser.get(123) is None

        old_click = Message("Начать", payload=json.dumps(old_payload))
        assert await consent_env.gate.intercept(consent_env.bot, old_click) is True
        assert not consent_env.store.has_consent((456, 123, 123), consent_env.gate.version)
        photo = Message(photo=b"new-photo")
        assert await consent_env.gate.intercept(consent_env.bot, photo) is True
        assert button(photo)["action"] == "accept_consent"

    asyncio.run(scenario())


def test_withdrawal_invalidates_unaccepted_button(consent_env):
    async def scenario():
        offer = Message("начать")
        await consent_env.gate.intercept(consent_env.bot, offer)
        pending_payload = button(offer)
        await consent_env.gate.intercept(consent_env.bot, Message("Отозвать согласие"))
        click = Message("Начать", payload=json.dumps(pending_payload))
        await consent_env.gate.intercept(consent_env.bot, click)
        assert not consent_env.store.has_consent((456, 123, 123), consent_env.gate.version)
        assert "WELCOME" not in [text for text, _ in click.answers]

    asyncio.run(scenario())


def test_contacting_master_is_available_without_photo_consent(consent_env):
    message = Message("Позови мастера")
    assert asyncio.run(consent_env.gate.intercept(consent_env.bot, message)) is False
    assert message.answers == []
    assert not consent_env.store.has_consent((456, 123, 123), consent_env.gate.version)


def test_consent_can_be_read_again_without_withdrawing_it(consent_env):
    async def scenario():
        await accept(consent_env)
        message = Message("Согласие")
        assert await consent_env.gate.intercept(consent_env.bot, message) is True
        assert consent_env.gate.text in "\n".join(text for text, _ in message.answers)
        assert consent_env.store.has_consent((456, 123, 123), consent_env.gate.version)

    asyncio.run(scenario())


def test_failed_consent_database_blocks_processing_without_leaking_error(consent_env, monkeypatch, caplog):
    marker = "private-database-path-and-token"

    def failed(*args, **kwargs):
        raise OSError(marker)

    monkeypatch.setattr(consent_env.store, "has_consent", failed)
    message = Message(photo=b"photo")
    assert asyncio.run(consent_env.gate.intercept(consent_env.bot, message)) is True
    assert message.answers
    assert marker not in repr(message.answers)
    assert marker not in caplog.text
    assert "WELCOME" not in [text for text, _ in message.answers]


def test_acceptance_write_failure_never_starts_bot(consent_env, monkeypatch, caplog):
    async def scenario():
        offer = Message("Начать")
        await consent_env.gate.intercept(consent_env.bot, offer)

        def failed(*args, **kwargs):
            raise OSError("private-consent-token")

        monkeypatch.setattr(consent_env.store, "accept", failed)
        click = Message("Начать", payload=json.dumps(button(offer)))
        assert await consent_env.gate.intercept(consent_env.bot, click) is True
        assert not consent_env.store.has_consent((456, 123, 123), consent_env.gate.version)
        assert "WELCOME" not in [text for text, _ in click.answers]
        assert "private-consent-token" not in repr(click.answers)
        assert "private-consent-token" not in caplog.text

    asyncio.run(scenario())


def test_failed_withdrawal_write_still_stops_processing_in_this_process(consent_env, monkeypatch):
    async def scenario():
        await accept(consent_env)
        await consent_env.bot.state_dispenser.set(123, "waiting", item_ids=["selected"])

        def failed(*args, **kwargs):
            raise OSError("private-receipt-path")

        monkeypatch.setattr(consent_env.store, "revoke", failed)
        withdrawal = Message("Отозвать согласие")
        assert await consent_env.gate.intercept(consent_env.bot, withdrawal) is True
        assert await consent_env.bot.state_dispenser.get(123) is None
        assert consent_env.gate.is_allowed(Message(photo=b"photo")) is False
        photo = Message(photo=b"photo")
        assert await consent_env.gate.intercept(consent_env.bot, photo) is True
        assert "WELCOME" not in [text for text, _ in photo.answers]

    asyncio.run(scenario())


@pytest.mark.parametrize("route,text", [("start", "привет"), ("catalog", "каталог"), ("search", "Серьги Луна"), ("photo", "")])
def test_each_entry_handler_gates_before_catalog_selection_or_photo_work(dialog, tmp_path, monkeypatch, route, text):
    gate = ConsentGate(ConsentStore(tmp_path / "consent.sqlite3"), group_id=456)
    monkeypatch.setattr(sys.modules["bot.app"], "consent_gate", gate)
    calls = []

    async def download(*args):
        calls.append("download")
        raise AssertionError("No photograph may be downloaded before consent.")

    def render(*args):
        calls.append("render")
        raise AssertionError("No photograph may be rendered before consent.")

    monkeypatch.setattr(dialog.photo, "download_first_photo", download)
    monkeypatch.setattr(dialog.photo, "apply_tryon_many", render)
    asyncio.run(dialog.bot.state_dispenser.set(123, "waiting", item_ids=["earrings"]))
    message = Message(text, photo=b"photo" if route == "photo" else None)
    handler = {"start": dialog.common.start_handler, "catalog": dialog.common.catalog_list_handler,
               "search": dialog.search.search_handler, "photo": dialog.photo.photo_handler}[route]
    asyncio.run(handler(message))
    assert calls == []
    assert button(message)["action"] == "accept_consent"
    assert 123 not in dialog.bot.state_dispenser.states
    assert not any("attachment" in options for _, options in message.answers)


@pytest.mark.parametrize("reaccept", [False, True])
def test_withdrawal_during_render_suppresses_old_upload_and_result(dialog, tmp_path, monkeypatch, reaccept):
    store = ConsentStore(tmp_path / "consent.sqlite3")
    gate = ConsentGate(store, group_id=456)
    env = SimpleNamespace(store=store, gate=gate, bot=dialog.bot)
    monkeypatch.setattr(sys.modules["bot.app"], "consent_gate", gate)

    async def scenario():
        await accept(env)
        await dialog.search.search_handler(Message("Серьги Луна"))
        started = asyncio.Event()
        finished = asyncio.Event()
        uploads = []

        async def paused_render(function, *args):
            started.set()
            await finished.wait()
            return b"result-jpeg"

        async def upload(*args):
            uploads.append(args)
            return "photo1_2"

        monkeypatch.setattr(dialog.photo.asyncio, "to_thread", paused_render)
        monkeypatch.setattr(dialog.photo, "upload_photo_for_message", upload)
        old_photo = Message(photo=b"photo")
        pending = asyncio.create_task(dialog.photo.photo_handler(old_photo))
        await asyncio.wait_for(started.wait(), timeout=2)
        withdrawal = Message("Отозвать согласие")
        await dialog.photo.photo_handler(withdrawal)
        assert not store.has_consent((456, 123, 123), gate.version)
        if reaccept:
            await accept(env)
            await dialog.search.search_handler(Message("Серьги Луна"))
        finished.set()
        await asyncio.wait_for(pending, timeout=2)
        assert uploads == []
        assert old_photo.answers == []

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["download", "upload"])
def test_withdrawal_during_media_io_suppresses_remaining_work(dialog, tmp_path, monkeypatch, phase):
    store = ConsentStore(tmp_path / "consent.sqlite3")
    gate = ConsentGate(store, group_id=456)
    env = SimpleNamespace(store=store, gate=gate, bot=dialog.bot)
    monkeypatch.setattr(sys.modules["bot.app"], "consent_gate", gate)

    async def scenario():
        await accept(env)
        await dialog.search.search_handler(Message("Серьги Луна"))
        started = asyncio.Event()
        finished = asyncio.Event()
        calls = []

        async def download(message):
            calls.append("download")
            if phase == "download":
                started.set()
                await finished.wait()
            return message.photo

        async def render(function, *args):
            calls.append("render")
            return b"result-jpeg"

        async def upload(*args):
            calls.append("upload")
            if phase == "upload":
                started.set()
                await finished.wait()
            return "photo1_2"

        monkeypatch.setattr(dialog.photo, "download_first_photo", download)
        monkeypatch.setattr(dialog.photo.asyncio, "to_thread", render)
        monkeypatch.setattr(dialog.photo, "upload_photo_for_message", upload)
        old_photo = Message(photo=b"photo")
        pending = asyncio.create_task(dialog.photo.photo_handler(old_photo))
        await asyncio.wait_for(started.wait(), timeout=2)
        await dialog.photo.photo_handler(Message("Отозвать согласие"))
        assert not store.has_consent((456, 123, 123), gate.version)
        finished.set()
        await asyncio.wait_for(pending, timeout=2)
        assert old_photo.answers == []
        assert calls == (["download"] if phase == "download" else ["download", "render", "upload"])

    asyncio.run(scenario())
