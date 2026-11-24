"""Exercise dialog transitions without VK credentials or network calls."""

import asyncio
import copy
import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest

from bot.jewelry.catalog import catalog
from bot.jewelry.models import Category, JewelryItem


class FakeStateDispenser:
    def __init__(self):
        self.states = {}

    async def get(self, peer_id):
        return self.states.get(peer_id)

    async def set(self, peer_id, state, **payload):
        self.states[peer_id] = SimpleNamespace(state=state, payload=payload)

    async def delete(self, peer_id):
        self.states.pop(peer_id, None)


class FakeMessage:
    def __init__(self, text="", photo=None):
        self.peer_id = 123
        self.from_id = 123
        self.payload = None
        self.text = text
        self.photo = photo
        self.attachments = [SimpleNamespace(photo=object())] if photo else []
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


@pytest.fixture
def dialog(monkeypatch):
    # The handlers depend only on vkbottle's labeler decorator and message
    # protocol. Supplying that adapter keeps tests runnable in the native
    # inference environment, where vkbottle is intentionally not installed.
    try:
        importlib.import_module("vkbottle")
    except ImportError:
        vk = ModuleType("vkbottle")
        vk.__path__ = []
        vk.BaseStateGroup = type("BaseStateGroup", (), {})
        vk.PhotoMessageUploader = object
        vk_bot = ModuleType("vkbottle.bot")

        class BotLabeler:
            def message(self, *args, **kwargs):
                return lambda handler: handler

        vk_bot.BotLabeler = BotLabeler
        vk_bot.Message = object
        monkeypatch.setitem(sys.modules, "vkbottle", vk)
        monkeypatch.setitem(sys.modules, "vkbottle.bot", vk_bot)

    fake_bot = SimpleNamespace(state_dispenser=FakeStateDispenser(), api=object())
    app = ModuleType("bot.app")
    app.bot = fake_bot

    class AcceptedConsent:
        async def intercept(self, bot, message):
            return False

        def is_allowed(self, message):
            return True

    app.consent_gate = AcceptedConsent()

    class ActiveSession:
        async def intercept(self, bot, message, consent_gate):
            return False

        def current_token(self, message):
            return 'active-test-session'

        def is_current(self, message, token):
            return token == 'active-test-session'

    app.session_gate = ActiveSession()
    monkeypatch.setitem(sys.modules, "bot.app", app)

    async def download(message):
        return message.photo

    async def upload(api, image_bytes, peer_id):
        assert api is fake_bot.api
        assert image_bytes == b"result-jpeg"
        return "photo1_2"

    # Replace the network adapter as a unit; no aiohttp dependency or VK API
    # should be needed to exercise dialog logic.
    media = ModuleType("bot.vk_media")
    media.PhotoDownloadError = type("PhotoDownloadError", (Exception,), {})
    media.download_first_photo = download
    media.upload_photo_for_message = upload
    monkeypatch.setitem(sys.modules, "bot.vk_media", media)
    handlers = SimpleNamespace(
        search=importlib.import_module("bot.handlers.catalog"),
        photo=importlib.import_module("bot.handlers.photo"),
        common=importlib.import_module("bot.handlers.common"),
        bot=fake_bot,
    )
    earrings = JewelryItem("earrings", "Серьги Луна", Category.EARRINGS, "earrings.png")
    pendant = JewelryItem("pendant", "Кулон Огонь", Category.PENDANT, "pendant.png")
    beads = JewelryItem("beads", "Бусы Весна", Category.BEADS, "beads.png")
    diadem = JewelryItem("diadem", "Диадема Рассвет", Category.DIADEM, "diadem.png")
    hairpin = JewelryItem("hairpin", "Заколка Цветок", Category.HAIRPIN, "hairpin.png")
    brooch = JewelryItem("brooch", "Брошь Птица", Category.BROOCH, "brooch.png")
    kaffy = JewelryItem("kaffy", "Кафф Лес", Category.KAFFY, "kaffy.png")
    winter = JewelryItem(
        "winter", "Венец (диадема) Зимние ягоды и серьги", Category.SET, "winter.png",
        components=[
            JewelryItem("winter-diadem", "Зимние ягоды", Category.DIADEM, "winter-diadem.png"),
            JewelryItem("winter-earrings", "Зимние серьги", Category.EARRINGS, "winter-earrings.png"),
        ],
    )
    lake = JewelryItem(
        "lake", "Набор Ледяное озеро", Category.SET, "lake.png",
        tryon_mode="sequential",
        components=[
            JewelryItem("lake-earrings", "Серьги Ледяное озеро", Category.EARRINGS, "lake-earrings.png", pair_image=True),
            JewelryItem("lake-bracelet", "Манжета Ледяное озеро", Category.BRACELET, "lake-bracelet.png"),
        ],
    )
    handlers.items = [earrings, pendant, beads, diadem, hairpin, brooch, kaffy, winter, lake]
    monkeypatch.setattr(catalog, "items", handlers.items)
    monkeypatch.setattr(catalog, "reload_if_changed", lambda: False)

    monkeypatch.setattr(handlers.photo, "download_first_photo", download)
    monkeypatch.setattr(handlers.photo, "upload_photo_for_message", upload)
    return handlers


def call(handler, text="", photo=None):
    message = FakeMessage(text, photo)
    asyncio.run(handler(message))
    return message


def selected(dialog):
    state = dialog.bot.state_dispenser.states.get(123)
    if state is None:
        return []
    return state.payload.get("item_ids", [state.payload.get("item_id")])


@pytest.mark.parametrize("separator", [" + ", "; ", "\n"])
def test_independent_products_cannot_be_selected_together(dialog, separator):
    message = call(dialog.search.search_handler, separator.join(["Серьги Луна", "Кулон Огонь"]))
    assert selected(dialog) == []
    assert "только для готовых наборов" in message.answers[-1][0]


def test_new_name_replaces_the_single_selected_product(dialog):
    call(dialog.search.search_handler, "Серьги Луна")
    call(dialog.photo.photo_handler, "Кулон Огонь")
    assert selected(dialog) == ["pendant"]


def test_add_command_explains_sets_only_and_keeps_selection(dialog):
    call(dialog.search.search_handler, "Серьги Луна")
    message = call(dialog.photo.photo_handler, "добавить Кулон Огонь")
    assert selected(dialog) == ["earrings"]
    assert "только для готовых наборов" in message.answers[-1][0]


def test_multiple_names_do_not_replace_existing_selection(dialog):
    call(dialog.search.search_handler, "Серьги Луна")
    call(dialog.photo.photo_handler, "Кулон Огонь + Диадема Рассвет")
    assert selected(dialog) == ["earrings"]


@pytest.mark.parametrize("command", ["отмена", "сброс", "убрать"])
def test_clear_selection(dialog, command):
    call(dialog.search.search_handler, "Зимние ягоды и серьги")
    call(dialog.photo.photo_handler, command)
    assert selected(dialog) == []


def test_catalog_and_category_navigation_keep_selection(dialog):
    call(dialog.search.search_handler, "Серьги Луна")
    catalog_message = call(dialog.photo.photo_handler, "каталог")
    sets_message = call(dialog.photo.photo_handler, "наборы")
    diadems_message = call(dialog.photo.photo_handler, "диадемы")
    assert selected(dialog) == ["earrings"]
    assert "Кулон Огонь" in catalog_message.answers[-1][0]
    assert "Зимние ягоды и серьги" in sets_message.answers[-1][0]
    assert "Зимние ягоды и серьги" not in diadems_message.answers[-1][0]


@pytest.mark.parametrize('text', ['КАТАЛОГ', 'Каталог!', ' «КатАлОг» ', '/catalog',
                                 'покажи каталог', 'католог', 'RFnFKJu'])
@pytest.mark.parametrize('waiting_photo', [False, True])
def test_catalog_variants_route_before_product_search_and_photo_download(dialog, monkeypatch, text, waiting_photo):
    if waiting_photo:
        call(dialog.search.search_handler, 'Серьги Луна')
    before = selected(dialog)

    async def forbidden_download(*args):
        pytest.fail('A catalog command must not download its attached photo')

    monkeypatch.setattr(dialog.photo, 'download_first_photo', forbidden_download)
    handler = dialog.photo.photo_handler if waiting_photo else dialog.search.search_handler
    message = call(handler, text, photo=b'photo')
    assert selected(dialog) == before
    assert 'Кулон Огонь' in message.answers[-1][0]
    assert 'Серьги Луна' in message.answers[-1][0]


@pytest.mark.parametrize('waiting_photo', [False, True])
@pytest.mark.parametrize('text,contains,excludes', [
    ('СЕРЬГИ!', 'Серьги Луна', 'Кулон Огонь'),
    (' «НАБОРЫ» ', 'Ледяное озеро', 'Кулон Огонь'),
    ('/БУСЫ', 'Бусы Весна', 'Кулон Огонь'),
    ('CTHMUB', 'Серьги Луна', 'Кулон Огонь'),
])
def test_category_variants_open_only_their_section(dialog, text, contains, excludes, waiting_photo):
    if waiting_photo:
        call(dialog.search.search_handler, 'Серьги Луна')
    before = selected(dialog)
    handler = dialog.photo.photo_handler if waiting_photo else dialog.search.search_handler
    message = call(handler, text)
    assert selected(dialog) == before
    assert contains in message.answers[-1][0]
    assert excludes not in message.answers[-1][0]


@pytest.mark.parametrize('text', ['ОТМЕНА!', '/CANCEL', ' СбРоС? ', 'ОЧИСТИТЬ', 'отменить'])
def test_cancel_variants_clear_waiting_selection(dialog, text):
    call(dialog.search.search_handler, 'Серьги Луна')
    call(dialog.photo.photo_handler, text)
    assert selected(dialog) == []


@pytest.mark.parametrize('text', ['/START', ' ПРИВЕТ! ', 'НаЧаТь', 'Здравствуйте!'])
def test_start_variants_reach_welcome_without_searching_products(dialog, text):
    message = call(dialog.search.search_handler, text)
    assert 'бот-примерочная' in message.answers[-1][0]


def test_uppercase_prefixed_product_commands_keep_the_original_name(dialog):
    call(dialog.search.search_handler, '/ПРИМЕРИТЬ «Серьги Луна»')
    assert selected(dialog) == ['earrings']
    call(dialog.photo.photo_handler, 'УБРАТЬ «Серьги Луна»')
    assert selected(dialog) == []


@pytest.mark.parametrize('text,expected', [('/ПРИМЕРИТЬ «Кулон Огонь»', ['pendant']),
                                        ('УБРАТЬ «Серьги Луна»', []),
                                        ('ДОБАВИТЬ Кулон Огонь', ['earrings'])])
def test_prefixed_commands_with_photo_dispatch_before_download(dialog, monkeypatch, text, expected):
    call(dialog.search.search_handler, 'Серьги Луна')

    async def forbidden_download(*args):
        pytest.fail('Explicit commands take precedence over an attached photograph')

    monkeypatch.setattr(dialog.photo, 'download_first_photo', forbidden_download)
    call(dialog.photo.photo_handler, text, photo=b'photo')
    assert selected(dialog) == expected


@pytest.mark.parametrize("command", ["привет", "каталог", "серьги"])
def test_navigation_refreshes_catalog_before_reading_items(dialog, monkeypatch, command):
    updated = JewelryItem("new", "Новые серьги из редактора", Category.EARRINGS, "new.png")
    refreshes = []

    def refresh():
        refreshes.append(True)
        monkeypatch.setattr(catalog, "items", [updated])

    monkeypatch.setattr(catalog, "reload_if_changed", refresh)
    handler = dialog.common.start_handler if command == "привет" else dialog.common.catalog_list_handler
    message = call(handler, command)
    assert refreshes == [True]
    assert updated.name in message.answers[-1][0]
    if command == "привет":
        assert "по частям" in message.answers[-1][0]
        assert "анфас" not in message.answers[-1][0]


def test_item_name_containing_and_remains_a_single_set(dialog):
    call(dialog.search.search_handler, "Венец (диадема) Зимние ягоды и серьги")
    assert selected(dialog) == ["winter"]


def test_set_and_single_product_replace_each_other(dialog):
    call(dialog.search.search_handler, "Серьги Луна")
    call(dialog.photo.photo_handler, "Зимние ягоды и серьги")
    assert selected(dialog) == ["winter"]
    call(dialog.photo.photo_handler, "Диадема Рассвет")
    assert selected(dialog) == ["diadem"]


def test_unknown_name_keeps_the_previous_selection(dialog):
    call(dialog.search.search_handler, "Серьги Луна")
    call(dialog.photo.photo_handler, "зжшдлфыва")
    assert selected(dialog) == ["earrings"]


def test_missing_photo_keeps_selection(dialog):
    call(dialog.search.search_handler, "Зимние ягоды и серьги")
    call(dialog.photo.photo_handler)
    assert selected(dialog) == ["winter"]


@pytest.mark.parametrize("name,expected", [
    ("Серьги Луна", ["earrings"]),
    ("Зимние ягоды и серьги", ["winter-diadem", "winter-earrings"]),
])
def test_one_photo_renders_selected_product_or_set_once(dialog, monkeypatch, name, expected):
    rendered = []

    def render(items, paths, photo_bytes):
        rendered.append(([item.id for item in items], paths, photo_bytes))
        return b"result-jpeg"

    monkeypatch.setattr(dialog.photo, "apply_tryon_many", render)
    call(dialog.search.search_handler, name)
    message = call(dialog.photo.photo_handler, photo=b"original-photo")
    assert len(rendered) == 1
    assert rendered[0][0] == expected
    assert rendered[0][2] == b"original-photo"
    assert len(rendered[0][1]) == len(expected)
    assert message.answers[-1][1]["attachment"] == "photo1_2"
    assert selected(dialog) == []


def test_set_renders_components_with_independent_paths(dialog, monkeypatch):
    rendered = []

    def render(items, paths, photo_bytes):
        rendered.append(([item.id for item in items], [path.name for path in paths]))
        return b"result-jpeg"

    monkeypatch.setattr(dialog.photo, "apply_tryon_many", render)
    call(dialog.search.search_handler, "Зимние ягоды и серьги")
    call(dialog.photo.photo_handler, photo=b"original-photo")
    assert rendered == [(
        ["winter-diadem", "winter-earrings"], ["winter-diadem.png", "winter-earrings.png"]
    )]


def test_failed_render_keeps_set_for_retry(dialog, monkeypatch):
    def render(*args):
        raise dialog.photo.TryOnError("Не видно открытое ухо")

    monkeypatch.setattr(dialog.photo, "apply_tryon_many", render)
    call(dialog.search.search_handler, "Зимние ягоды и серьги")
    message = call(dialog.photo.photo_handler, photo=b"original-photo")
    assert selected(dialog) == ["winter"]
    assert "Не видно открытое ухо" in message.answers[-1][0]


def test_failed_upload_keeps_set_for_retry(dialog, monkeypatch):
    monkeypatch.setattr(dialog.photo, "apply_tryon_many", lambda *args: b"result-jpeg")

    async def failed_upload(*args):
        raise OSError("VK unavailable")

    monkeypatch.setattr(dialog.photo, "upload_photo_for_message", failed_upload)
    call(dialog.search.search_handler, "Зимние ягоды и серьги")
    call(dialog.photo.photo_handler, photo=b"original-photo")
    assert selected(dialog) == ["winter"]


def test_old_single_item_state_can_still_be_processed(dialog, monkeypatch):
    monkeypatch.setattr(dialog.photo, "apply_tryon_many", lambda *args: b"result-jpeg")
    asyncio.run(dialog.bot.state_dispenser.set(123, "waiting_photo", item_id="earrings"))
    message = call(dialog.photo.photo_handler, photo=b"original-photo")
    assert message.answers[-1][1]["attachment"] == "photo1_2"
    assert selected(dialog) == []


def test_stale_catalog_id_resets_selection_without_render(dialog, monkeypatch):
    rendered = []
    monkeypatch.setattr(dialog.photo, "apply_tryon_many", lambda *args: rendered.append(args))
    asyncio.run(dialog.bot.state_dispenser.set(123, "waiting_photo", item_ids=["removed-product"]))
    call(dialog.photo.photo_handler, photo=b"original-photo")
    assert selected(dialog) == []
    assert rendered == []


def test_old_multiple_product_selection_cannot_render(dialog, monkeypatch):
    rendered = []
    monkeypatch.setattr(dialog.photo, "apply_tryon_many", lambda *args: rendered.append(args))
    asyncio.run(dialog.bot.state_dispenser.set(123, "waiting_photo", item_ids=["earrings", "pendant"]))
    message = call(dialog.photo.photo_handler, photo=b"original-photo")
    assert rendered == []
    assert selected(dialog) == []
    assert "только для готовых наборов" in message.answers[-1][0]


@pytest.mark.parametrize("outcome", ["success", "tryon-error", "unexpected-error"])
def test_changing_selection_during_render_preserves_new_selection(dialog, monkeypatch, outcome):
    async def scenario():
        render_started = asyncio.Event()
        render_finished = asyncio.Event()
        uploads = []

        async def paused_render(function, *args):
            render_started.set()
            await render_finished.wait()
            if outcome == "tryon-error":
                raise dialog.photo.TryOnError("Old photo has no visible ear")
            if outcome == "unexpected-error":
                raise RuntimeError("Old native worker failed")
            return b"result-jpeg"

        async def upload(*args):
            uploads.append(args)
            return "photo1_2"

        monkeypatch.setattr(dialog.photo.asyncio, "to_thread", paused_render)
        monkeypatch.setattr(dialog.photo, "upload_photo_for_message", upload)
        await dialog.search.search_handler(FakeMessage("Серьги Луна"))
        old_photo = FakeMessage(photo=b"original-photo")
        pending_render = asyncio.create_task(dialog.photo.photo_handler(old_photo))
        await asyncio.wait_for(render_started.wait(), timeout=1)

        await dialog.photo.photo_handler(FakeMessage("Кулон Огонь"))
        new_payload = dict(dialog.bot.state_dispenser.states[123].payload)
        render_finished.set()
        await asyncio.wait_for(pending_render, timeout=1)

        assert selected(dialog) == ["pendant"]
        assert dialog.bot.state_dispenser.states[123].payload == new_payload
        assert uploads == []
        assert old_photo.answers == []

    asyncio.run(scenario())


def test_cancelling_during_upload_suppresses_old_result(dialog, monkeypatch):
    async def scenario():
        upload_started = asyncio.Event()
        upload_finished = asyncio.Event()

        async def render(function, *args):
            return b"result-jpeg"

        async def paused_upload(*args):
            upload_started.set()
            await upload_finished.wait()
            return "photo1_2"

        monkeypatch.setattr(dialog.photo.asyncio, "to_thread", render)
        monkeypatch.setattr(dialog.photo, "upload_photo_for_message", paused_upload)
        await dialog.search.search_handler(FakeMessage("Серьги Луна"))
        old_photo = FakeMessage(photo=b"original-photo")
        pending_upload = asyncio.create_task(dialog.photo.photo_handler(old_photo))
        await asyncio.wait_for(upload_started.wait(), timeout=1)

        await dialog.photo.photo_handler(FakeMessage("отмена"))
        upload_finished.set()
        await asyncio.wait_for(pending_upload, timeout=1)

        assert selected(dialog) == []
        assert old_photo.answers == []

    asyncio.run(scenario())


def test_reselecting_same_items_during_render_has_a_new_token(dialog, monkeypatch):
    async def scenario():
        render_started = asyncio.Event()
        render_finished = asyncio.Event()
        uploads = []

        async def paused_render(function, *args):
            render_started.set()
            await render_finished.wait()
            return b"result-jpeg"

        async def upload(*args):
            uploads.append(args)
            return "photo1_2"

        monkeypatch.setattr(dialog.photo.asyncio, "to_thread", paused_render)
        monkeypatch.setattr(dialog.photo, "upload_photo_for_message", upload)
        await dialog.search.search_handler(FakeMessage("Серьги Луна"))
        old_token = dialog.bot.state_dispenser.states[123].payload["selection_token"]
        old_photo = FakeMessage(photo=b"original-photo")
        pending_render = asyncio.create_task(dialog.photo.photo_handler(old_photo))
        await asyncio.wait_for(render_started.wait(), timeout=1)

        await dialog.photo.photo_handler(FakeMessage("сброс"))
        await dialog.search.search_handler(FakeMessage("Серьги Луна"))
        new_token = dialog.bot.state_dispenser.states[123].payload["selection_token"]
        assert new_token != old_token
        render_finished.set()
        await asyncio.wait_for(pending_render, timeout=1)

        assert selected(dialog) == ["earrings"]
        assert dialog.bot.state_dispenser.states[123].payload["selection_token"] == new_token
        assert uploads == []
        assert old_photo.answers == []

    asyncio.run(scenario())


@pytest.mark.parametrize("unexpected", [False, True])
def test_download_failure_keeps_selection_and_allows_retry(dialog, monkeypatch, unexpected):
    rendered = []
    call(dialog.search.search_handler, "Зимние ягоды и серьги")
    payload = dict(dialog.bot.state_dispenser.states[123].payload)

    async def failed_download(message):
        if unexpected:
            raise RuntimeError("unexpected adapter failure")
        raise dialog.photo.PhotoDownloadError("Не удалось скачать фото. Пришлите его ещё раз.")

    monkeypatch.setattr(dialog.photo, "download_first_photo", failed_download)
    monkeypatch.setattr(dialog.photo, "apply_tryon_many", lambda *args: rendered.append(args))
    failed = call(dialog.photo.photo_handler, photo=b"photo")
    assert rendered == []
    assert selected(dialog) == ["winter"]
    assert dialog.bot.state_dispenser.states[123].payload == payload
    assert "ещё раз" in failed.answers[-1][0]

    async def download(message):
        return message.photo

    monkeypatch.setattr(dialog.photo, "download_first_photo", download)
    monkeypatch.setattr(dialog.photo, "apply_tryon_many", lambda *args: b"result-jpeg")
    retried = call(dialog.photo.photo_handler, photo=b"photo")
    assert retried.answers[-1][1]["attachment"] == "photo1_2"
    assert selected(dialog) == []


@pytest.mark.parametrize("outcome", ["success", "error"])
@pytest.mark.parametrize("action", ["change", "cancel"])
def test_changed_selection_during_download_suppresses_old_result(dialog, monkeypatch, outcome, action):
    async def scenario():
        started = asyncio.Event()
        finished = asyncio.Event()
        rendered = []

        async def download(message):
            if message.photo is None:
                return None
            started.set()
            await finished.wait()
            if outcome == "error":
                raise dialog.photo.PhotoDownloadError("Не удалось скачать фото. Пришлите его ещё раз.")
            return message.photo

        monkeypatch.setattr(dialog.photo, "download_first_photo", download)
        monkeypatch.setattr(dialog.photo, "apply_tryon_many", lambda *args: rendered.append(args))
        await dialog.search.search_handler(FakeMessage("Серьги Луна"))
        old_photo = FakeMessage(photo=b"original-photo")
        pending = asyncio.create_task(dialog.photo.photo_handler(old_photo))
        await asyncio.wait_for(started.wait(), timeout=1)
        await dialog.photo.photo_handler(FakeMessage("Кулон Огонь" if action == "change" else "отмена"))
        finished.set()
        await asyncio.wait_for(pending, timeout=1)
        assert selected(dialog) == (["pendant"] if action == "change" else [])
        assert rendered == []
        assert old_photo.answers == []

    asyncio.run(scenario())


def test_sequential_set_requests_two_photos_and_never_stores_images(dialog, monkeypatch):
    rendered = []

    def render(items, paths, photo_bytes):
        rendered.append(([item.id for item in items], [path.name for path in paths], photo_bytes))
        return b"result-jpeg"

    monkeypatch.setattr(dialog.photo, "apply_tryon_many", render)
    choice = call(dialog.search.search_handler, "Набор Ледяное озеро")
    initial = dict(dialog.bot.state_dispenser.states[123].payload)
    assert "Фото 1 из 2" in choice.answers[-1][0]
    assert "запястье" not in choice.answers[-1][0]
    face = call(dialog.photo.photo_handler, photo=b"face-photo")
    assert face.answers[-1][1]["attachment"] == "photo1_2"
    assert "Фото 2 из 2" in face.answers[-1][0]
    assert "запястье" in face.answers[-1][0]
    assert dialog.bot.state_dispenser.states[123].payload == {**initial, "step_index": 1}
    assert set(initial) == {"item_ids", "selection_token", "step_index"}
    wrist = call(dialog.photo.photo_handler, photo=b"wrist-photo")
    assert wrist.answers[-1][1]["attachment"] == "photo1_2"
    assert "Фото 2 из 2" not in wrist.answers[-1][0]
    assert rendered == [
        (["lake-earrings"], ["lake-earrings.png"], b"face-photo"),
        (["lake-bracelet"], ["lake-bracelet.png"], b"wrist-photo"),
    ]
    assert selected(dialog) == []


def test_selected_item_uses_refreshed_calibration_without_reselecting(dialog, monkeypatch):
    call(dialog.search.search_handler, "Серьги Луна")
    updated = JewelryItem("earrings", "Серьги Луна", Category.EARRINGS, "new-art.png", anchor_scale=0.73)

    def refresh():
        monkeypatch.setattr(catalog, "items", [updated])

    rendered = []

    def render(items, paths, photo_bytes):
        rendered.append((items, [path.name for path in paths]))
        return b"result-jpeg"

    monkeypatch.setattr(catalog, "reload_if_changed", refresh)
    monkeypatch.setattr(dialog.photo, "apply_tryon_many", render)
    call(dialog.photo.photo_handler, photo=b"face-photo")
    assert rendered == [([updated], ["new-art.png"])]


@pytest.mark.parametrize("step", [-1, 2, "1", True])
def test_stale_step_is_reset_without_rendering_a_different_body_part(dialog, monkeypatch, step):
    rendered = []
    monkeypatch.setattr(dialog.photo, "apply_tryon_many", lambda *args: rendered.append(args))
    asyncio.run(dialog.bot.state_dispenser.set(123, "waiting_photo", item_ids=["lake"], step_index=step))
    message = call(dialog.photo.photo_handler, photo=b"photo")
    assert rendered == []
    assert selected(dialog) == []
    assert "Шаг примерки устарел" in message.answers[-1][0]


@pytest.mark.parametrize("step", [0, 1])
@pytest.mark.parametrize("failure", ["download", "render", "upload", "send"])
def test_sequential_failure_retries_the_same_step(dialog, monkeypatch, step, failure):
    monkeypatch.setattr(dialog.photo, "apply_tryon_many", lambda *args: b"result-jpeg")
    call(dialog.search.search_handler, "Набор Ледяное озеро")
    if step:
        call(dialog.photo.photo_handler, photo=b"face-photo")
    before = dict(dialog.bot.state_dispenser.states[123].payload)
    failed = FakeMessage(photo=b"retry-photo")
    rendered = []

    with monkeypatch.context() as patch:
        if failure == "download":
            async def bad_download(message):
                raise dialog.photo.PhotoDownloadError("Не удалось скачать фото. Пришлите его ещё раз.")
            patch.setattr(dialog.photo, "download_first_photo", bad_download)
        elif failure == "render":
            def bad_render(*args):
                raise dialog.photo.TryOnError("На фото не видно нужную область")
            patch.setattr(dialog.photo, "apply_tryon_many", bad_render)
        elif failure == "upload":
            async def bad_upload(*args):
                raise OSError("VK unavailable")
            patch.setattr(dialog.photo, "upload_photo_for_message", bad_upload)
        else:
            original_answer = failed.answer

            async def bad_send(text, **kwargs):
                if kwargs.get("attachment"):
                    raise OSError("VK send failed")
                await original_answer(text, **kwargs)

            failed.answer = bad_send
        asyncio.run(dialog.photo.photo_handler(failed))
    assert dialog.bot.state_dispenser.states[123].payload == before
    assert failed.answers

    def render(items, paths, photo_bytes):
        rendered.append(([item.id for item in items], photo_bytes))
        return b"result-jpeg"

    monkeypatch.setattr(dialog.photo, "apply_tryon_many", render)
    call(dialog.photo.photo_handler, photo=b"retry-photo")
    assert rendered == [(["lake-bracelet" if step else "lake-earrings"], b"retry-photo")]
    if step:
        assert selected(dialog) == []
    else:
        assert dialog.bot.state_dispenser.states[123].payload == {**before, "step_index": 1}


@pytest.mark.parametrize("stage", ["download", "render", "upload"])
@pytest.mark.parametrize("action", ["change", "cancel", "reselect"])
def test_second_step_stale_work_cannot_change_a_new_selection(dialog, monkeypatch, stage, action):
    async def scenario():
        monkeypatch.setattr(dialog.photo, "apply_tryon_many", lambda *args: b"result-jpeg")
        await dialog.search.search_handler(FakeMessage("Набор Ледяное озеро"))
        await dialog.photo.photo_handler(FakeMessage(photo=b"face-photo"))
        assert dialog.bot.state_dispenser.states[123].payload["step_index"] == 1
        started = asyncio.Event()
        finished = asyncio.Event()

        async def pause(result):
            started.set()
            await finished.wait()
            return result

        if stage == "download":
            async def download(message):
                return await pause(message.photo) if message.photo else None
            monkeypatch.setattr(dialog.photo, "download_first_photo", download)
        elif stage == "render":
            async def render(function, *args):
                return await pause(b"result-jpeg")
            monkeypatch.setattr(dialog.photo.asyncio, "to_thread", render)
        else:
            async def upload(*args):
                return await pause("photo1_2")
            monkeypatch.setattr(dialog.photo, "upload_photo_for_message", upload)

        old_photo = FakeMessage(photo=b"wrist-photo")
        pending = asyncio.create_task(dialog.photo.photo_handler(old_photo))
        await asyncio.wait_for(started.wait(), timeout=1)
        command = {"change": "Кулон Огонь", "cancel": "отмена", "reselect": "Набор Ледяное озеро"}[action]
        await dialog.photo.photo_handler(FakeMessage(command))
        new_state = dialog.bot.state_dispenser.states.get(123)
        new_payload = dict(new_state.payload) if new_state else None
        finished.set()
        await asyncio.wait_for(pending, timeout=1)
        latest = dialog.bot.state_dispenser.states.get(123)
        assert (latest.payload if latest else None) == new_payload
        assert selected(dialog) == {"change": ["pendant"], "cancel": [], "reselect": ["lake"]}[action]
        if action == "reselect":
            assert latest.payload["step_index"] == 0
        assert old_photo.answers == []

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["success", "download-error"])
def test_slow_first_step_download_is_discarded_after_another_photo_advances(dialog, monkeypatch, outcome):
    async def scenario():
        started = asyncio.Event()
        finished = asyncio.Event()
        rendered = []

        async def download(message):
            if message.photo == b"slow-face":
                started.set()
                await finished.wait()
                if outcome == "download-error":
                    raise dialog.photo.PhotoDownloadError("Не удалось скачать старое фото")
            return message.photo

        def render(items, paths, photo_bytes):
            rendered.append(([item.id for item in items], photo_bytes))
            return b"result-jpeg"

        monkeypatch.setattr(dialog.photo, "download_first_photo", download)
        monkeypatch.setattr(dialog.photo, "apply_tryon_many", render)
        await dialog.search.search_handler(FakeMessage("Набор Ледяное озеро"))
        old_photo = FakeMessage(photo=b"slow-face")
        pending = asyncio.create_task(dialog.photo.photo_handler(old_photo))
        await asyncio.wait_for(started.wait(), timeout=1)
        await dialog.photo.photo_handler(FakeMessage(photo=b"face-photo"))
        advanced = dict(dialog.bot.state_dispenser.states[123].payload)
        assert advanced["step_index"] == 1
        finished.set()
        await asyncio.wait_for(pending, timeout=1)
        assert dialog.bot.state_dispenser.states[123].payload == advanced
        assert rendered == [(["lake-earrings"], b"face-photo")]
        assert old_photo.answers == []

    asyncio.run(scenario())


def test_simultaneous_photos_do_not_send_two_results_for_one_step(dialog, monkeypatch):
    async def scenario():
        started = asyncio.Event()
        finished = asyncio.Event()
        rendered = []

        async def render(function, items, paths, photo_bytes):
            rendered.append(([item.id for item in items], photo_bytes))
            started.set()
            await finished.wait()
            return b"result-jpeg"

        monkeypatch.setattr(dialog.photo.asyncio, "to_thread", render)
        await dialog.search.search_handler(FakeMessage("Набор Ледяное озеро"))
        first = FakeMessage(photo=b"face-photo")
        pending = asyncio.create_task(dialog.photo.photo_handler(first))
        await asyncio.wait_for(started.wait(), timeout=1)
        duplicate = FakeMessage(photo=b"duplicate-photo")
        await dialog.photo.photo_handler(duplicate)
        finished.set()
        await asyncio.wait_for(pending, timeout=1)
        assert rendered == [(["lake-earrings"], b"face-photo")]
        assert "ещё обрабатывается" in duplicate.answers[-1][0]
        assert dialog.bot.state_dispenser.states[123].payload["step_index"] == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("step", [0, 1])
def test_selection_changed_while_sending_is_not_advanced_or_cleared(dialog, monkeypatch, step):
    async def scenario():
        monkeypatch.setattr(dialog.photo, "apply_tryon_many", lambda *args: b"result-jpeg")
        await dialog.search.search_handler(FakeMessage("Набор Ледяное озеро"))
        if step:
            await dialog.photo.photo_handler(FakeMessage(photo=b"face-photo"))
        started = asyncio.Event()
        finished = asyncio.Event()
        photo = FakeMessage(photo=b"photo")
        original_answer = photo.answer

        async def paused_answer(text, **kwargs):
            started.set()
            await finished.wait()
            await original_answer(text, **kwargs)

        photo.answer = paused_answer
        pending = asyncio.create_task(dialog.photo.photo_handler(photo))
        await asyncio.wait_for(started.wait(), timeout=1)
        await dialog.photo.photo_handler(FakeMessage("Кулон Огонь"))
        new_payload = dict(dialog.bot.state_dispenser.states[123].payload)
        finished.set()
        await asyncio.wait_for(pending, timeout=1)
        assert dialog.bot.state_dispenser.states[123].payload == new_payload
        assert selected(dialog) == ["pendant"]

    asyncio.run(scenario())


@pytest.fixture
def master_dialog(dialog):
    """Fake only the new VK boundary, keeping the real dialog handlers."""
    events = []

    class API:
        def __init__(self):
            self.results = {}
            self.requests = []

        async def request(self, method, params):
            self.requests.append((method, dict(params)))
            events.append(('api', method, dict(params)))
            result = self.results.get(method, {'response': 1})
            if isinstance(result, BaseException):
                raise result
            return result

    class Message(FakeMessage):
        async def answer(self, text, **kwargs):
            events.append(('answer', text))
            await super().answer(text, **kwargs)

    dialog.master = importlib.import_module('bot.handlers.master')
    dialog.bot.api = API()
    dialog.bot.polling = SimpleNamespace(group_id=456)
    dialog.master_message = Message
    dialog.master_events = events
    return dialog


@pytest.mark.parametrize('text', [
    'Позови мастера', 'позови мастера', 'ПОЗОВИ МАСТЕРА',
    '  Позови   мастера  ', 'Позови\nмастера', 'Позови\u00a0мастера',
    'Позови мастера!', '«Позови мастера»', '"Позови мастера?!"',
])
def test_master_command_accepts_case_spacing_and_outer_punctuation(text):
    from bot.handlers.master import is_master_request
    assert is_master_request(text)


@pytest.mark.parametrize('text', [
    None, '', 'Позови', 'Мастера', 'Не позови мастера',
    'Позови мастера завтра', 'Кулон Позови мастера',
    'Позови мастера + серьги', 'Позовите мастера',
])
def test_master_command_requires_the_whole_phrase(text):
    from bot.handlers.master import is_master_request
    assert not is_master_request(text)


def test_master_request_from_idle_marks_peer_then_unanswered_after_reply(master_dialog):
    d = master_dialog
    message = d.master_message('  ПОЗОВИ   МАСТЕРА! ')
    asyncio.run(d.search.search_handler(message))
    assert d.master_events == [
        ('api', 'messages.markAsImportantConversation', {'peer_id': 123, 'important': 1, 'group_id': 456}),
        ('answer', d.master.MARKED_REPLY),
        ('api', 'messages.markAsAnsweredConversation', {'peer_id': 123, 'answered': 0, 'group_id': 456}),
    ]
    assert selected(d) == []
    assert message.answers == [(d.master.MARKED_REPLY, {})]


@pytest.mark.parametrize('payload', [
    {'item_ids': ['earrings'], 'step_index': 0, 'selection_token': 'single'},
    {'item_ids': ['lake'], 'step_index': 0, 'selection_token': 'set-first'},
    {'item_ids': ['lake'], 'step_index': 1, 'selection_token': 'set-second'},
    {'item_ids': ['removed-product'], 'step_index': 0, 'selection_token': 'stale'},
])
@pytest.mark.parametrize('photo', [None, b'attached-photo'])
def test_master_request_preempts_photo_and_keeps_selection(master_dialog, monkeypatch, payload, photo):
    d = master_dialog
    before = copy.deepcopy(payload)
    asyncio.run(d.bot.state_dispenser.set(123, 'waiting_photo', **payload))

    async def no_download(*args):
        pytest.fail('A master command must not download an attached photo')

    def no_render(*args):
        pytest.fail('A master command must not render a photo')

    monkeypatch.setattr(d.photo, 'download_first_photo', no_download)
    monkeypatch.setattr(d.photo, 'apply_tryon_many', no_render)
    message = d.master_message('Позови мастера', photo=photo)
    asyncio.run(d.photo.photo_handler(message))
    assert d.bot.state_dispenser.states[123].payload == before
    assert message.answers == [(d.master.MARKED_REPLY, {})]
    assert len(d.bot.api.requests) == 2


@pytest.mark.parametrize('failed', ['important', 'unanswered'])
def test_one_marker_failure_does_not_prevent_the_other(master_dialog, failed):
    d = master_dialog
    method = ('messages.markAsImportantConversation' if failed == 'important'
              else 'messages.markAsAnsweredConversation')
    d.bot.api.results[method] = OSError('provider unavailable')
    message = d.master_message('Позови мастера')
    assert asyncio.run(d.master.request_master(d.bot, message)) is True
    assert [name for name, _ in d.bot.api.requests] == [
        'messages.markAsImportantConversation', 'messages.markAsAnsweredConversation',
    ]
    assert message.answers == [(
        d.master.RECEIVED_REPLY if failed == 'important' else d.master.MARKED_REPLY, {},
    )]


def test_both_marker_failures_explain_retry_without_false_success(master_dialog):
    d = master_dialog
    for method in ['messages.markAsImportantConversation', 'messages.markAsAnsweredConversation']:
        d.bot.api.results[method] = asyncio.TimeoutError()
    message = d.master_message('Позови мастера')
    assert asyncio.run(d.master.request_master(d.bot, message)) is False
    assert message.answers == [(d.master.RECEIVED_REPLY, {}), (d.master.FAILED_REPLY, {})]
    assert all('Диалог отмечен' not in text for text, _ in message.answers)
    assert len(d.bot.api.requests) == 2


@pytest.mark.parametrize('response', [{'response': 0}, {}, None, {'response': '1'}])
def test_unexpected_marker_result_is_not_treated_as_success(master_dialog, response):
    d = master_dialog
    d.bot.api.results['messages.markAsImportantConversation'] = response
    message = d.master_message('Позови мастера')
    assert asyncio.run(d.master.request_master(d.bot, message)) is True  # Unanswered succeeded.
    assert message.answers == [(d.master.RECEIVED_REPLY, {})]
    assert len(d.bot.api.requests) == 2


def test_acknowledgement_failure_still_marks_unanswered(master_dialog):
    d = master_dialog
    message = d.master_message('Позови мастера')

    async def failed_answer(text, **kwargs):
        d.master_events.append(('answer-attempt', text))
        raise OSError('acknowledgement unavailable')

    message.answer = failed_answer
    assert asyncio.run(d.master.request_master(d.bot, message)) is True
    assert d.master_events[-1] == (
        'api', 'messages.markAsAnsweredConversation', {'peer_id': 123, 'answered': 0, 'group_id': 456},
    )
    assert len(d.bot.api.requests) == 2


def test_marker_and_ack_failures_cannot_leak_exception_secrets(master_dialog, caplog):
    d = master_dialog
    secret = 'private-access-token-in-url'

    class NumericError(Exception):
        code = 15

    class UnsafeCodeError(Exception):
        code = secret

    d.bot.api.results['messages.markAsImportantConversation'] = NumericError('https://example.invalid/?access_token=' + secret)
    d.bot.api.results['messages.markAsAnsweredConversation'] = UnsafeCodeError(secret)
    message = d.master_message('Позови мастера')

    async def failed_answer(*args, **kwargs):
        raise RuntimeError(secret)

    message.answer = failed_answer
    with caplog.at_level('WARNING', logger='vk_jewelry_bot.master'):
        assert asyncio.run(d.master.request_master(d.bot, message)) is False
    assert secret not in caplog.text
    assert 'https://' not in caplog.text
    assert 'code=15' in caplog.text
    assert 'code=unknown' in caplog.text
    assert 'acknowledgement failed' in caplog.text


def test_repeated_master_commands_only_set_flags_without_toggling(master_dialog):
    d = master_dialog
    for _ in range(2):
        asyncio.run(d.master.request_master(d.bot, d.master_message('Позови мастера')))
    assert d.bot.api.requests == [
        ('messages.markAsImportantConversation', {'peer_id': 123, 'important': 1, 'group_id': 456}),
        ('messages.markAsAnsweredConversation', {'peer_id': 123, 'answered': 0, 'group_id': 456}),
    ] * 2


def test_group_id_is_omitted_when_polling_has_not_resolved_it(master_dialog):
    d = master_dialog
    d.bot.polling.group_id = None
    asyncio.run(d.master.request_master(d.bot, d.master_message('Позови мастера')))
    assert d.bot.api.requests == [
        ('messages.markAsImportantConversation', {'peer_id': 123, 'important': 1}),
        ('messages.markAsAnsweredConversation', {'peer_id': 123, 'answered': 0}),
    ]


@pytest.mark.parametrize('stage', ['download', 'render', 'upload'])
@pytest.mark.parametrize('selection', ['Серьги Луна', 'Набор Ледяное озеро'])
def test_master_request_does_not_cancel_the_running_tryon(master_dialog, monkeypatch, stage, selection):
    d = master_dialog

    async def scenario():
        started, finished = asyncio.Event(), asyncio.Event()
        monkeypatch.setattr(d.photo, 'apply_tryon_many', lambda *args: b'result-jpeg')
        await d.search.search_handler(FakeMessage(selection))
        before = copy.deepcopy(d.bot.state_dispenser.states[123].payload)

        async def pause(result):
            started.set()
            await finished.wait()
            return result

        if stage == 'download':
            async def download(message):
                return await pause(message.photo)
            monkeypatch.setattr(d.photo, 'download_first_photo', download)
        elif stage == 'render':
            async def render(function, *args):
                return await pause(b'result-jpeg')
            monkeypatch.setattr(d.photo.asyncio, 'to_thread', render)
        else:
            async def upload(*args):
                return await pause('photo1_2')
            monkeypatch.setattr(d.photo, 'upload_photo_for_message', upload)

        old_photo = FakeMessage(photo=b'original-photo')
        pending = asyncio.create_task(d.photo.photo_handler(old_photo))
        await asyncio.wait_for(started.wait(), timeout=1)
        await d.photo.photo_handler(d.master_message('Позови мастера'))
        assert d.bot.state_dispenser.states[123].payload == before
        finished.set()
        await asyncio.wait_for(pending, timeout=1)
        assert old_photo.answers[-1][1] == {'attachment': 'photo1_2'}
        if selection == 'Серьги Луна':
            assert selected(d) == []
        else:
            assert d.bot.state_dispenser.states[123].payload == {**before, 'step_index': 1}

    asyncio.run(scenario())


def test_master_command_is_discoverable_in_welcome_and_catalog(master_dialog):
    d = master_dialog
    welcome = call(d.common.start_handler, 'Начать')
    listing = call(d.common.catalog_list_handler, 'Каталог')
    assert 'Позови мастера' in welcome.answers[-1][0]
    assert 'Позови мастера' in listing.answers[-1][0]
