from __future__ import annotations

from app.oauth import extract_codex_text, messages_to_codex_input, short_provider_error


def test_short_provider_error_strips_html() -> None:
    html = "<html><head><style>.lo{animation:enlarge-appear}</style></head><body>nope</body></html>"
    assert short_provider_error(403, html, "chatgpt.com") == "HTTP 403 HTML from chatgpt.com"


def test_messages_to_codex_input_vision() -> None:
    instructions, rows = messages_to_codex_input([
        {"role": "system", "content": "JSON only"},
        {"role": "user", "content": [
            {"type": "text", "text": "classify"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,xx"}},
        ]},
    ])
    assert instructions == "JSON only"
    assert rows[0]["content"][0] == {"type": "input_text", "text": "classify"}
    assert rows[0]["content"][1] == {"type": "input_image", "image_url": "data:image/png;base64,xx"}


def test_messages_to_codex_input_marks_assistant_output_text() -> None:
    _, rows = messages_to_codex_input([
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "follow up"},
    ])
    assert rows[0]["content"] == [{"type": "input_text", "text": "first"}]
    assert rows[1]["content"] == [{"type": "output_text", "text": "answer"}]
    assert rows[2]["content"] == [{"type": "input_text", "text": "follow up"}]


def test_extract_codex_text_delta() -> None:
    assert extract_codex_text({"type": "response.output_text.delta", "delta": "{\"1\":"}) == "{\"1\":"
    assert "plains" in extract_codex_text({
        "type": "response.completed",
        "response": {"output": [{"content": [{"type": "output_text", "text": "{\"1\":\"plains\"}"}]}]},
    })
