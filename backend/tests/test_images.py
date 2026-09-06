import base64

import pytest
from fastapi import HTTPException

from app.images import grok_edit_body, image_size, mask_bytes, openai_edit_form, resolve_mask
from app.oauth import _codex_background
from app.schemas import ImageRequest


def test_image_request_keeps_transparent_background():
    req = ImageRequest(provider="openai-codex", prompt="cutout", background="transparent")
    assert req.background == "transparent"


def test_codex_background_defaults_opaque():
    assert _codex_background("") == "opaque"
    assert _codex_background("transparent") == "transparent"
    assert _codex_background("AUTO") == "auto"


def test_image_request_keeps_mask_from_extras_and_field():
    png = "data:image/png;base64,aaaa"
    via_field = ImageRequest(prompt="edit", mask=png)
    via_extras = ImageRequest(prompt="edit", extras={"mask": png})
    assert via_field.mask == png
    assert resolve_mask(via_extras) == png


def test_legacy_size_snap_stays_on_gpt_image_1():
    assert image_size("gpt-image-1", 2048, 1024) == "1536x1024"
    assert image_size("dall-e-3", 800, 1200) == "1024x1536"


def test_gpt_image_2_keeps_native_size():
    assert image_size("gpt-image-2", 2048, 1536) == "2048x1536"
    assert image_size("gpt-image-1.5", 1600, 900) == "1600x896"


def test_grok_edit_body_sends_json_images():
    req = ImageRequest(
        provider="xai",
        model="grok-imagine-image-2.0",
        prompt="merge",
        images=["data:image/png;base64,aaa", "data:image/png;base64,bbb", "data:image/png;base64,ccc", "extra"],
        width=2048,
        height=1024,
    )
    body = grok_edit_body(req)
    assert body["images"] == [
        {"type": "image_url", "url": "data:image/png;base64,aaa"},
        {"type": "image_url", "url": "data:image/png;base64,bbb"},
        {"type": "image_url", "url": "data:image/png;base64,ccc"},
    ]
    assert "mask" not in body
    assert body["aspect_ratio"] == "2:1"


def test_openai_edit_form_attaches_mask_file():
    png = base64.b64encode(b"PNG").decode("ascii")
    url = f"data:image/png;base64,{png}"
    req = ImageRequest(provider="openai", model="gpt-image-2", prompt="edit", images=[url], mask=url, width=2048, height=1024)
    form, files = openai_edit_form(req)
    assert form["size"] == "2048x1024"
    names = [item[0] for item in files]
    assert names == ["image[]", "mask"]


def test_mask_over_4mb_is_rejected():
    blob = base64.b64encode(b"x" * (4 * 1024 * 1024 + 1)).decode("ascii")
    req = ImageRequest(prompt="edit", extras={"mask": f"data:image/png;base64,{blob}"})
    with pytest.raises(HTTPException) as caught:
        mask_bytes(req)
    assert caught.value.status_code == 400
