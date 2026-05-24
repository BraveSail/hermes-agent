"""Tests for Telegram auto-fold (expandable blockquote) feature.

Uses entities-only approach (consistent with reasoning italic entities).
Markdown is parsed into plain text + entity dicts, then an
EXPANDABLE_BLOCKQUOTE entity wraps everything.  No parse_mode is used.
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.config import PlatformConfig

# Ensure telegram mock is in place
if "telegram" not in sys.modules or not hasattr(sys.modules["telegram"], "__file__"):
    from types import SimpleNamespace
    mod = MagicMock()
    mod.ext.ContextTypes.DEFAULT_TYPE = type(None)
    mod.constants = MagicMock()
    mod.constants.ParseMode = SimpleNamespace(
        MARKDOWN_V2="MarkdownV2",
        HTML="HTML",
    )
    mod.constants.ChatType = SimpleNamespace(
        GROUP="group",
        SUPERGROUP="supergroup",
        CHANNEL="channel",
        PRIVATE="private",
    )
    mod.MessageEntity = MagicMock()
    for name in ("telegram", "telegram.ext", "telegram.constants",
                 "telegram.request", "telegram.error"):
        sys.modules.setdefault(name, mod)

from gateway.platforms.telegram import TelegramAdapter  # noqa: E402


@pytest.fixture()
def adapter():
    config = PlatformConfig(enabled=True, token="fake-token")
    return TelegramAdapter(config)


def _make_msg(message_id=1):
    msg = MagicMock()
    msg.message_id = message_id
    return msg


class TestAutoFold:
    """Auto-fold: non-DM long messages get EXPANDABLE_BLOCKQUOTE entity."""

    @pytest.mark.asyncio
    async def test_folds_long_message_in_group(self, adapter):
        """>100 chars in a group → entities with EXPANDABLE_BLOCKQUOTE."""
        adapter._bot = MagicMock()
        adapter._bot.send_message = AsyncMock(return_value=_make_msg(1))
        content = "This is a long message. " * 8  # ~200 chars
        assert len(content) > 100

        result = await adapter.send(
            chat_id="-1001234567890",
            content=content,
            metadata={"chat_type": "group"},
        )

        assert result.success is True
        assert adapter._bot.send_message.called
        call_kwargs = adapter._bot.send_message.call_args.kwargs

        # Entity-driven: entities should be present, NO parse_mode
        entities = call_kwargs.get("entities")
        assert entities is not None, "Auto-fold should use entities"
        assert "parse_mode" not in call_kwargs or call_kwargs["parse_mode"] is None, \
            "Entity path must NOT include parse_mode"

        # Text should be plain (no markdown markers)
        text = call_kwargs["text"]
        assert "**" not in text, f"Text should have no markdown: {text[:80]}"
        assert "This is a long message" in text

    @pytest.mark.asyncio
    async def test_no_fold_for_short_message(self, adapter):
        """≤100 chars → no auto-fold."""
        adapter._bot = MagicMock()
        adapter._bot.send_message = AsyncMock(return_value=_make_msg(1))
        content = "Short."
        assert len(content) <= 100

        result = await adapter.send(
            chat_id="-1001234567890",
            content=content,
            metadata={"chat_type": "group"},
        )

        assert result.success is True
        call_kwargs = adapter._bot.send_message.call_args.kwargs
        assert call_kwargs.get("entities") is None, "Short message should not use entities"

    @pytest.mark.asyncio
    async def test_no_fold_for_dm(self, adapter):
        """Even long messages in DM → no fold."""
        adapter._bot = MagicMock()
        adapter._bot.send_message = AsyncMock(return_value=_make_msg(1))
        content = "This is a long message. " * 8

        result = await adapter.send(
            chat_id="1879026273",
            content=content,
            metadata={"chat_type": "dm"},
        )

        assert result.success is True
        call_kwargs = adapter._bot.send_message.call_args.kwargs
        assert call_kwargs.get("entities") is None, "DM should not fold"

    @pytest.mark.asyncio
    async def test_no_fold_without_chat_type(self, adapter):
        """Missing chat_type → no fold."""
        adapter._bot = MagicMock()
        adapter._bot.send_message = AsyncMock(return_value=_make_msg(1))
        content = "Long " * 30

        result = await adapter.send(
            chat_id="-1001234567890",
            content=content,
            metadata={"notify": True},
        )

        assert result.success is True
        call_kwargs = adapter._bot.send_message.call_args.kwargs
        assert call_kwargs.get("entities") is None

    @pytest.mark.asyncio
    async def test_no_fold_when_blockquote_present(self, adapter):
        """Content already has **> → skip auto-fold."""
        adapter._bot = MagicMock()
        adapter._bot.send_message = AsyncMock(return_value=_make_msg(1))
        content = "**> already a blockquote || " + "padding " * 10
        assert len(content) > 100

        result = await adapter.send(
            chat_id="-1001234567890",
            content=content,
            metadata={"chat_type": "group"},
        )

        assert result.success is True
        call_kwargs = adapter._bot.send_message.call_args.kwargs
        assert call_kwargs.get("entities") is None, "Already-folded should skip"


class TestMarkdownToEntities:
    """Parse standard markdown into plain text + entity dicts."""

    def test_bold(self, adapter):
        text, ents = adapter._parse_markdown_to_entities("Hello **world**!")
        assert text == "Hello world!"
        assert len(ents) == 1
        assert ents[0]["type"] == "bold"
        assert ents[0]["offset"] == 6
        assert ents[0]["length"] == 5

    def test_italic(self, adapter):
        text, ents = adapter._parse_markdown_to_entities("Say *hello* there")
        assert text == "Say hello there"
        assert len(ents) == 1
        assert ents[0]["type"] == "italic"
        assert ents[0]["offset"] == 4
        assert ents[0]["length"] == 5

    def test_strikethrough(self, adapter):
        text, ents = adapter._parse_markdown_to_entities("Buy ~milk~ today")
        assert text == "Buy milk today"
        assert len(ents) == 1
        assert ents[0]["type"] == "strikethrough"

    def test_spoiler(self, adapter):
        text, ents = adapter._parse_markdown_to_entities("The answer is ||42||!")
        assert text == "The answer is 42!"
        assert len(ents) == 1
        assert ents[0]["type"] == "spoiler"

    def test_underline(self, adapter):
        text, ents = adapter._parse_markdown_to_entities("Read __this__ now")
        assert text == "Read this now"
        assert len(ents) == 1
        assert ents[0]["type"] == "underline"

    def test_link(self, adapter):
        text, ents = adapter._parse_markdown_to_entities(
            "Visit [the site](https://example.com) today"
        )
        assert text == "Visit the site today"
        assert len(ents) == 1
        assert ents[0]["type"] == "text_link"
        assert ents[0]["url"] == "https://example.com"

    def test_inline_code(self, adapter):
        text, ents = adapter._parse_markdown_to_entities(
            "Run `pip install` now"
        )
        assert text == "Run pip install now"
        assert len(ents) == 1
        assert ents[0]["type"] == "code"
        assert ents[0]["length"] == 11  # "pip install"

    def test_code_block(self, adapter):
        text, ents = adapter._parse_markdown_to_entities(
            "Before\n```\nprint('hi')\n```\nAfter"
        )
        assert "print('hi')" in text
        assert "```" not in text
        code_ents = [e for e in ents if e["type"] == "pre"]
        assert len(code_ents) == 1

    def test_nested_bold_italic(self, adapter):
        text, ents = adapter._parse_markdown_to_entities(
            "**bold *and italic* text**"
        )
        assert text == "bold and italic text"
        bold = [e for e in ents if e["type"] == "bold"]
        italic = [e for e in ents if e["type"] == "italic"]
        assert len(bold) == 1
        assert len(italic) == 1

    def test_plain_text_passthrough(self, adapter):
        text, ents = adapter._parse_markdown_to_entities(
            "Just plain text, nothing special."
        )
        assert text == "Just plain text, nothing special."
        assert ents == []

    def test_multiple_formats(self, adapter):
        text, ents = adapter._parse_markdown_to_entities(
            "**Bold** and *italic* and `code`"
        )
        assert "**" not in text
        assert "*" not in text
        assert "`" not in text
        types = {e["type"] for e in ents}
        assert types == {"bold", "italic", "code"}
