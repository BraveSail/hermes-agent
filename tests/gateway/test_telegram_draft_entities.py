"""Draft-frame entities channel regressions.

The pre-merge fork sent draft frames as **plain text + MessageEntity** (no
``parse_mode``), which Telegram renders incrementally (the animated preview).
The 0.21.2 merge replaced that with MarkdownV2 strings; re-parsing the
changing markup on every frame made the live preview repaint (the "blinking"
report). ``send_draft`` now parses the markdown into plain + entities first
and keeps the markdown channel only as a fallback.

The isolated test env installs a MagicMock telegram package, so these tests
assert on the parse layer (pure dicts) and on the call shape (no parse_mode +
entities present), never on MessageEntity field values.
"""

from unittest.mock import AsyncMock

import pytest

from gateway.config import Platform
from plugins.platforms.telegram.adapter import TelegramAdapter


def _make_adapter():
    adapter = TelegramAdapter.__new__(TelegramAdapter)
    adapter.platform = Platform.TELEGRAM
    adapter._typing_paused = set()
    adapter._fatal_error_message = None
    adapter._bot = AsyncMock()
    adapter._bot.send_message_draft = AsyncMock(return_value=True)
    return adapter


@pytest.mark.asyncio
async def test_send_draft_prefers_the_entities_channel():
    adapter = _make_adapter()
    content = "💭 **Reasoning:**\n*thinking aloud*\n\nAnswer with **bold** and *italic*"
    result = await adapter.send_draft(chat_id="1", draft_id=7, content=content)

    assert result.success
    kwargs = adapter._bot.send_message_draft.call_args.kwargs
    assert "parse_mode" not in kwargs, "the entities channel must not carry parse_mode"
    assert "**" not in kwargs["text"], "frame text must be plain (no markdown markers)"
    assert kwargs["entities"], "the entities channel must carry MessageEntity ranges"


@pytest.mark.asyncio
async def test_send_draft_falls_back_to_markdown_when_entities_channel_fails():
    adapter = _make_adapter()
    adapter._bot.send_message_draft = AsyncMock(side_effect=[RuntimeError("boom"), True])
    result = await adapter.send_draft(chat_id="1", draft_id=7, content="**bold** text")

    assert result.success
    assert adapter._bot.send_message_draft.call_count == 2
    second = adapter._bot.send_message_draft.call_args_list[1].kwargs
    assert second.get("parse_mode") is not None, "the fallback must use the markdown channel"


def test_markdown_parse_keeps_astral_ranges():
    # Parse layer: pure-python dicts, unaffected by the telegram mock.
    plain, dicts = TelegramAdapter._parse_markdown_to_entities("💭 **Reasoning:**\n*line*")
    assert plain == "💭 Reasoning:\nline"
    assert {"type": "bold", "offset": 2, "length": len("Reasoning:")} in dicts
    italic = next(d for d in dicts if d["type"] == "italic")
    assert italic["offset"] == 13  # code-point offsets: "💭 " (2 cp + space) + "Reasoning:"
    assert italic["length"] == len("line")
