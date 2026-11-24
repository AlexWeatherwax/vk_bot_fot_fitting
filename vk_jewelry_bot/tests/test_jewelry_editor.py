"""Exercise editor HTTP and persistence against an isolated temporary gallery.

No VK credentials, production catalogue or native model initialization is used.
Requires the editor's FastAPI dependencies plus httpx for TestClient.
"""
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest
from PIL import Image

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient


EDITOR_SOURCE = Path(__file__).resolve().parents[1] / "jewelry_editor/app.py"
PASSWORD = "isolated-editor-test-password"


def png(color=(190, 140, 40, 255), *, transparent=True):
    image = Image.new("RGBA", (30, 50), (0, 0, 0, 0) if transparent else color)
    if transparent:
        image.paste(color, (5, 5, 25, 45))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def photo():
    output = io.BytesIO()
    Image.new("RGB", (200, 300), (232, 222, 210)).save(output, format="JPEG")
    return output.getvalue()


@pytest.fixture
def editor(tmp_path, monkeypatch):
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    manifest = gallery / "manifest.json"
    manifest.write_text("[]\n", encoding="utf-8")
    monkeypatch.setenv("EDITOR_GALLERY", str(gallery))
    monkeypatch.setenv("EDITOR_PASSWORD", PASSWORD)
    monkeypatch.setenv("EDITOR_USER", "author")

    # Avoid even reading the production catalogue singleton during import.
    catalogue = ModuleType("bot.jewelry.catalog")
    catalogue.GALLERY_DIR = gallery
    monkeypatch.setitem(sys.modules, catalogue.__name__, catalogue)
    native = ModuleType("bot.tryon.pipeline")
    native.TryOnError = type("TryOnError", (Exception,), {})
    monkeypatch.setitem(sys.modules, native.__name__, native)
    import bot.tryon
    monkeypatch.setattr(bot.tryon, "pipeline", native, raising=False)

    name = "jewelry_editor._isolated_test_app"
    spec = importlib.util.spec_from_file_location(name, EDITOR_SOURCE)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)

    async def preview_without_native_models(payload):
        return {"image": "data:image/jpeg;base64," + base64.b64encode(photo()).decode(),
                "width": 200, "height": 300, "handles": []}

    monkeypatch.setattr(module, "run_preview", preview_without_native_models)
    client = TestClient(module.app)
    client.headers.update({"Authorization": "Basic " + base64.b64encode(
        ("author:" + PASSWORD).encode()).decode(), "X-Editor-Request": "1"})
    with client:
        yield SimpleNamespace(app=module, client=client, gallery=gallery, manifest=manifest)


def write_entries(editor, entries):
    editor.manifest.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return hashlib.sha256(editor.manifest.read_bytes()).hexdigest()


def entry(editor, item_id="existing", name="Серьги Луна", **extra):
    image = f"{item_id}.png"
    (editor.gallery / image).write_bytes(png())
    return {"id": item_id, "name": name, "category": "earrings", "image": image, **extra}


def revision(editor):
    response = editor.client.get("/api/catalog")
    assert response.status_code == 200, response.text
    return response.json()["revision"]


def upload(editor, raw=None):
    response = editor.client.post("/api/upload/jewelry?crop=true", content=raw or png())
    assert response.status_code == 200, response.text
    return response.json()["token"]


def payload(editor, **changes):
    data = {
        "settings": {"name": "  Новые   серьги  ", "category": "earrings",
                     "anchor_scale": 1.7, "offset_x": -.12, "offset_y": .18,
                     "rotation_offset": -27.5, "overlay_anchor": [.3, .07]},
        "asset": upload(editor), "revision": revision(editor),
    }
    data.update(changes)
    return data


def test_authentication_and_same_origin_guard_protect_mutations(editor):
    unauthenticated = TestClient(editor.app.app)
    assert unauthenticated.get("/api/catalog").status_code == 401
    assert editor.client.post("/api/upload/jewelry", content=png(),
                              headers={"X-Editor-Request": "0"}).status_code == 403
    assert editor.client.post("/api/upload/jewelry", content=png(),
                              headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert json.loads(editor.manifest.read_text()) == []


def test_windows_launcher_can_identify_editor_without_credentials(editor):
    # The launcher must distinguish the editor from another process using its port,
    # without storing the catalogue password or bypassing HTTP authentication.
    with TestClient(editor.app.app) as unauthenticated:
        response = unauthenticated.get('/')
    assert response.status_code == 401
    assert response.headers['X-Imladris-Editor'] == '1'
    assert response.headers['Cache-Control'] == 'no-store'
    assert 'Basic realm=' in response.headers['WWW-Authenticate']
    response = editor.client.get('/')
    assert response.status_code == 200
    assert response.headers['X-Imladris-Editor'] == '1'


def test_upload_requires_visible_jewelry_on_transparent_background(editor):
    opaque = editor.client.post("/api/upload/jewelry", content=png(transparent=False))
    assert opaque.status_code == 422
    blank = io.BytesIO()
    Image.new("RGBA", (20, 20)).save(blank, format="PNG")
    assert editor.client.post("/api/upload/jewelry", content=blank.getvalue()).status_code == 422
    assert editor.client.post("/api/upload/jewelry", content=b"not-an-image").status_code == 422
    assert json.loads(editor.manifest.read_text()) == []


def test_uploaded_asset_is_accessible_by_opaque_token_only(editor):
    token = upload(editor)
    response = editor.client.get(f"/api/asset/{token}")
    assert response.status_code == 200
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.mode == "RGBA"
        assert image.size == (20, 40)  # Transparent margins were cropped.
    assert editor.client.get("/api/asset/manifest.json").status_code in {404, 422}
    assert editor.client.get("/api/asset/unknown-token").status_code in {404, 422}
    # Displaying an upload in the browser must not invalidate its asset kind.
    data = payload(editor, asset=token)
    saved = editor.client.post("/api/save", json=data)
    assert saved.status_code == 200, saved.text


def test_save_persists_fitting_numbers_and_catalogue_can_load_them(editor):
    response = editor.client.post("/api/save", json=payload(editor))
    assert response.status_code == 200, response.text
    saved = response.json()["entry"]
    assert saved["name"] == "Новые серьги"
    assert saved["anchor_scale"] == 1.7
    assert saved["offset_x"] == -.12
    assert saved["offset_y"] == .18
    assert saved["rotation_offset"] == -27.5
    assert saved["overlay_anchor"] == [.3, .07]
    assert (editor.gallery / saved["image"]).is_file()
    assert json.loads(editor.manifest.read_text())[0] == saved
    loaded = editor.client.post(f'/api/load/{saved["id"]}', json={})
    assert loaded.status_code == 200
    assert loaded.json()["entry"] == saved
    assert loaded.json()["revision"] == response.json()["revision"]


def test_edit_renames_and_replaces_image_but_preserves_id_and_extra_metadata(editor):
    original = entry(editor, artisan_note="Ручная сборка", price=1200)
    write_entries(editor, [original])
    data = payload(editor, editing_id=original["id"], replace=True)
    data["settings"]["name"] = "Луна после правки"
    response = editor.client.post("/api/save", json=data)
    assert response.status_code == 200, response.text
    saved = response.json()["entry"]
    assert saved["id"] == original["id"]
    assert saved["name"] == "Луна после правки"
    assert saved["image"] != original["image"]
    assert saved["artisan_note"] == "Ручная сборка"
    assert saved["price"] == 1200
    assert (editor.gallery / original["image"]).is_file()
    assert len(json.loads(editor.manifest.read_text())) == 1


def test_duplicate_name_does_not_overwrite_without_explicit_replacement(editor):
    original = entry(editor)
    write_entries(editor, [original])
    data = payload(editor)
    data["settings"]["name"] = "  СЕРЬГИ   ЛУНА "
    before = editor.manifest.read_bytes()
    response = editor.client.post("/api/save", json=data)
    assert response.status_code == 409
    assert editor.manifest.read_bytes() == before


def test_rename_to_another_products_name_is_rejected(editor):
    originals = [entry(editor), entry(editor, "other", "Серьги Солнце")]
    write_entries(editor, originals)
    data = payload(editor, editing_id="existing", replace=True)
    data["settings"]["name"] = "Серьги Солнце"
    before = editor.manifest.read_bytes()
    assert editor.client.post("/api/save", json=data).status_code == 409
    assert editor.manifest.read_bytes() == before


def test_outdated_save_preserves_newer_catalogue(editor):
    data = payload(editor)
    newer = entry(editor)
    write_entries(editor, [newer])
    before = editor.manifest.read_bytes()
    assert editor.client.post("/api/save", json=data).status_code == 409
    assert editor.manifest.read_bytes() == before


def test_delete_requires_confirmation_and_current_revision(editor):
    original = entry(editor)
    current = write_entries(editor, [original])
    before = editor.manifest.read_bytes()
    for body in [{"revision": current, "confirm": False},
                 {"revision": "old-revision", "confirm": True}]:
        response = editor.client.request("DELETE", "/api/items/existing", json=body)
        assert response.status_code in {409, 422}
        assert editor.manifest.read_bytes() == before


def test_confirmed_delete_keeps_image_and_recoverable_manifest_backup(editor):
    first, second = entry(editor), entry(editor, "other", "Серьги Солнце")
    current = write_entries(editor, [first, second])
    before = editor.manifest.read_bytes()
    response = editor.client.request("DELETE", "/api/items/existing",
                                     json={"revision": current, "confirm": True})
    assert response.status_code == 200, response.text
    assert json.loads(editor.manifest.read_text()) == [second]
    assert (editor.gallery / first["image"]).is_file()
    backups = list((editor.gallery / ".editor-backups").glob("*.json"))
    assert any(path.read_bytes() == before for path in backups)
    assert response.json()["revision"] == hashlib.sha256(editor.manifest.read_bytes()).hexdigest()


def test_sets_are_listed_for_catalogue_management_and_can_be_deleted(editor):
    base = entry(editor, "winter", "Зимние ягоды и серьги")
    selected_set = dict(base, category="set", components=[
        {"id": "winter-earrings", "name": "Серьги", "category": "earrings", "image": base["image"]},
        {"id": "winter-diadem", "name": "Диадема", "category": "diadem", "image": base["image"]},
    ])
    current = write_entries(editor, [selected_set])
    response = editor.client.get("/api/catalog")
    assert response.status_code == 200
    assert response.json()["entries"][0]["id"] == "winter"
    assert response.json()["entries"][0]["editable"] is False
    assert editor.client.post("/api/load/winter", json={}).status_code == 422
    assert editor.client.request("DELETE", "/api/items/winter",
                                 json={"revision": current, "confirm": True}).status_code == 200


def test_catalogue_image_endpoint_does_not_traverse_outside_gallery(editor, tmp_path):
    outside = tmp_path / "private.png"
    outside.write_bytes(png())
    write_entries(editor, [{"id": "unsafe", "name": "Unsafe", "category": "earrings",
                            "image": "../private.png"}])
    assert editor.client.get("/api/image/unsafe").status_code in {404, 422}


def test_bad_reference_id_has_no_filesystem_access(editor):
    assert editor.client.get("/api/reference/not-a-reference").status_code == 404
    assert editor.client.post("/api/reference/not-a-reference", json={}).status_code == 404


def test_failed_catalogue_commit_leaves_previous_record_and_no_new_image(editor, monkeypatch):
    original = entry(editor)
    write_entries(editor, [original])
    data = payload(editor, editing_id="existing", replace=True)
    before = editor.manifest.read_bytes()

    def unavailable_atomic_replace(*args):
        raise OSError("simulated full filesystem")

    monkeypatch.setattr(editor.app.os, "replace", unavailable_atomic_replace)
    with pytest.raises(OSError, match="simulated full filesystem"):
        editor.client.post("/api/save", json=data)
    assert editor.manifest.read_bytes() == before
    assert list((editor.gallery / "custom").glob("*.png")) == []
    assert list(editor.gallery.glob(".manifest-*")) == []


def test_preview_exposes_actual_layers_and_correct_mono_ear_drag_direction(editor, monkeypatch):
    from bot.tryon.compose import overlay_image

    anchors = SimpleNamespace(face_width=100, left_lobe=(50, 100), right_lobe=(150, 100))
    native = ModuleType("bot.tryon.pipeline")
    native.face_mod = SimpleNamespace(get_face_anchors=lambda *args, **kwargs: anchors)
    native.hand_mod = SimpleNamespace(get_ring_anchor=lambda *args: None,
                                      get_wrist_anchor=lambda *args: None)
    native.pose_mod = SimpleNamespace(get_neck_anchor=lambda *args: None)
    native.overlay_image = overlay_image
    native.earring_points = lambda *args, **kwargs: {"right": anchors.right_lobe}
    native._PAIR_CACHE = {}

    def render_native(item, path, photo_bytes):
        # The native detector boundary is replaced, but the editor traces the
        # renderer and the real PIL composition; no coordinate mock response.
        found = native.face_mod.get_face_anchors(None)
        point = native.earring_points(None, found)["right"]
        base = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
        overlay = Image.open(path).convert("RGBA")
        result = native.overlay_image(
            base, overlay,
            (point[0] + found.face_width * item.offset_x,
             point[1] + found.face_width * item.offset_y),
            18 * item.anchor_scale, item.rotation_offset,
            overlay_anchor=item.overlay_anchor or (.5, .05),
        )
        output = io.BytesIO()
        result.convert("RGB").save(output, format="JPEG")
        return output.getvalue()

    native.apply_tryon = render_native
    monkeypatch.setattr(editor.app, "pipeline", native)
    data = payload(editor, photo=editor.app.put_asset(photo(), "photo"))
    data["settings"]["single_ear"] = True
    preview = editor.app.render(editor.app.parse(data))
    assert preview["width"] == 200 and preview["height"] == 300
    assert preview["unit"] == 100
    assert preview["settings"]["anchor_scale"] == 1.7
    assert len(preview["layers"]) == 1
    layer = preview["layers"][0]
    assert layer["sign"] == 1  # A single visible right ear must follow the pointer.
    assert layer["x"] == 138
    assert layer["y"] == 118
    assert layer["width"] == pytest.approx(30.6)
    assert layer["height"] == pytest.approx(61.2)
    assert layer["anchor"] == [.3, .07]
    assert layer["rotation"] == -27.5
    assert layer["editable"] is True
    assert layer["scale_with_item"] is True
    assert layer["rotate_with_item"] is True
    assert layer["image"].startswith("data:image/png;base64,")
    assert preview["base_image"].startswith("data:image/jpeg;base64,")


@pytest.mark.parametrize("frame_mode", ["legacy", "corrected", "masked"])
def test_pendant_preview_exposes_chain_frame_and_photo_mask_only_for_chain(editor, monkeypatch, frame_mode):
    from bot.tryon.compose import overlay_image
    import numpy as np

    neck = SimpleNamespace(shoulder_width=100, down=(.6, .8))
    corrected = SimpleNamespace(shoulder_width=100, down=(-.8, .6), chain_top=(80, 90))
    confidence = np.zeros((300, 200), dtype=np.float32)
    confidence[:100] = 1
    confidence[100:200] = .5
    frame = SimpleNamespace(anchors=corrected,
                            occlusion_mask=confidence if frame_mode == "masked" else None)
    native = ModuleType("bot.tryon.pipeline")
    native.face_mod = SimpleNamespace(get_face_anchors=lambda *args, **kwargs: None)
    native.hand_mod = SimpleNamespace(get_ring_anchor=lambda *args: None,
                                      get_wrist_anchor=lambda *args: None)
    native.pose_mod = SimpleNamespace(get_neck_anchor=lambda *args: neck)
    native.overlay_image = overlay_image
    native._PAIR_CACHE = {}
    height_calls = []

    def chain_height(found, point, face):
        height_calls.append((found, point, face))
        return -10.4

    native._neck_chain_height = chain_height
    if frame_mode != "legacy":
        native._pendant_frame = lambda *args: frame

    def render_native(item, path, photo_bytes):
        found = native.pose_mod.get_neck_anchor(None)
        if hasattr(native, "_pendant_frame"):
            found = native._pendant_frame(found, None, None).anchors
        base = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
        point = (100 + found.shoulder_width * item.offset_x,
                 180 + found.shoulder_width * item.offset_y)
        chain = Image.new("RGBA", (30, 20), (180, 150, 50, 100))
        base = native.overlay_image(base, chain, point, 32, 10, overlay_anchor=(.5, 1))
        result = native.overlay_image(base, Image.open(path).convert("RGBA"), point,
                                      18 * item.anchor_scale, 10 + item.rotation_offset,
                                      overlay_anchor=item.overlay_anchor or (.5, 0))
        output = io.BytesIO()
        result.convert("RGB").save(output, format="JPEG")
        return output.getvalue()

    native.apply_tryon = render_native
    monkeypatch.setattr(editor.app, "pipeline", native)
    data = payload(editor, photo=editor.app.put_asset(photo(), "photo"))
    data["settings"]["category"] = "pendant"
    preview = editor.app.render(editor.app.parse(data))
    chain, pendant = preview["layers"]
    assert chain["editable"] is False
    assert chain["scale_with_item"] is False
    assert chain["rotate_with_item"] is False
    assert chain["height_with_item_offset"] is True
    expected_anchors = neck if frame_mode == "legacy" else corrected
    assert chain["height_axis"] == list(expected_anchors.down)
    assert chain["min_height"] == 1
    assert chain["height_offset_origin"] == -10.4
    assert height_calls == [(expected_anchors, (chain["x"], chain["y"]), None)]
    assert pendant["editable"] is True
    assert pendant["scale_with_item"] is True
    assert pendant["rotate_with_item"] is True
    assert "occlusion_mask" not in pendant
    if frame_mode == "masked":
        mask_data = base64.b64decode(chain["occlusion_mask"].split(",", 1)[1])
        with Image.open(io.BytesIO(mask_data)) as mask:
            assert mask.mode == "RGBA"
            assert mask.size == (200, 300)
            assert mask.getpixel((50, 50)) == (255, 255, 255, 255)
            assert mask.getpixel((50, 150)) == (255, 255, 255, 128)
            assert mask.getpixel((50, 250)) == (255, 255, 255, 0)
    else:
        assert "occlusion_mask" not in chain
    assert chain["x"] == pendant["x"]
    assert chain["y"] == pendant["y"]
    assert preview["handles"] == [{"x": pendant["x"], "y": pendant["y"], "sign": 1}]


def test_editing_set_component_preserves_parent_sibling_and_mode(editor):
    base = entry(editor, "winter", "Зимние ягоды")
    parts = [
        {"id": "winter-diadem", "name": "Диадема", "category": "diadem", "image": base["image"],
         "offset_y": .2},
        {"id": "winter-earrings", "name": "Серьги", "category": "earrings", "image": base["image"],
         "anchor_scale": .8},
    ]
    parent = dict(base, category="set", components=parts, tryon_mode="combined")
    write_entries(editor, [parent])
    loaded = editor.client.post("/api/load/winter?component_id=winter-earrings", json={})
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["entry"] == parts[1]
    data = payload(editor, editing_id="winter", component_id="winter-earrings", replace=True)
    response = editor.client.post("/api/save", json=data)
    assert response.status_code == 200, response.text
    saved = json.loads(editor.manifest.read_text())[0]
    assert saved["id"] == parent["id"]
    assert saved["category"] == "set"
    assert saved["tryon_mode"] == "combined"
    assert saved["components"][0] == parts[0]
    assert saved["components"][1]["id"] == "winter-earrings"
    assert saved["components"][1]["anchor_scale"] == 1.7
    assert saved["components"][1]["rotation_offset"] == -27.5
    assert response.json()["parent"] == saved


def test_component_cannot_change_set_to_incompatible_views(editor):
    base = entry(editor, "winter", "Зимние ягоды")
    parent = dict(base, category="set", components=[
        {"id": "d", "name": "Диадема", "category": "diadem", "image": base["image"]},
        {"id": "e", "name": "Серьги", "category": "earrings", "image": base["image"]},
    ])
    write_entries(editor, [parent])
    data = payload(editor, editing_id="winter", component_id="e", replace=True)
    data["settings"]["category"] = "ring"
    before = editor.manifest.read_bytes()
    response = editor.client.post("/api/save", json=data)
    assert response.status_code == 422
    assert editor.manifest.read_bytes() == before


def test_set_name_can_be_changed_without_native_preview_or_component_mutation(editor):
    base = entry(editor, "winter", "Зимние ягоды")
    parent = dict(base, category="set", components=[
        {"id": "d", "name": "Диадема", "category": "diadem", "image": base["image"]},
        {"id": "e", "name": "Серьги", "category": "earrings", "image": base["image"]},
    ])
    current = write_entries(editor, [parent])
    response = editor.client.patch("/api/items/winter", json={"name": "  Зимний  образ  ", "revision": current})
    assert response.status_code == 200, response.text
    saved = json.loads(editor.manifest.read_text())[0]
    assert saved == dict(parent, name="Зимний образ")
    before = editor.manifest.read_bytes()
    stale = editor.client.patch("/api/items/winter", json={"name": "Старое изменение", "revision": current})
    assert stale.status_code == 409
    assert editor.manifest.read_bytes() == before


def test_branded_shell_assets_work_for_http_and_file_preview(editor):
    import re
    response = editor.client.get("/")
    assert response.status_code == 200
    assert "Имладрис: мастерская эльфийских украшений" in response.text
    resources = re.findall(r'(?:src|href)="(\./(?:style\.css|app\.js|transforms\.js))"', response.text)
    assert len(resources) == 3
    for resource in resources:
        local = EDITOR_SOURCE.parent / "static" / resource
        assert local.is_file()
        result = editor.client.get("/" + resource.removeprefix("./"))
        assert result.status_code == 200
        assert result.content == local.read_bytes()
    assert editor.client.get("/index.html").content == response.content
