"""Tests for Telegram auto-fold (expandable blockquote) feature.

Uses MarkdownV2 **> / > syntax — entities+parse_mode are mutually
exclusive in the Telegram API, so wrapping via MarkdownV2 is the only way
to have both the collapsed fold and inner formatting (bold, links, etc.).
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
    """Auto-fold: non-DM long messages get expandable blockquote via MarkdownV2."""

    @pytest.mark.asyncio
    async def test_folds_long_message_in_group(self, adapter):
        """>100 chars in a group → **> prefix on first line."""
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

        # Should use MarkdownV2 (not entities) — parse_mode is mocked,
        # so check that entities is not used
        assert call_kwargs.get("entities") is None

        # Text should start with **> (expandable blockquote markdown)
        text = call_kwargs["text"]
        assert text.startswith("**>"), f"Expected **> prefix, got: {text[:50]}..."

        # Subsequent lines (if any) should start with >
        for line in text.split("\n")[1:]:
            assert line.startswith(">"), f"Continuation line missing >: {line[:50]}..."

        # Inner content should still be present
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
        text = call_kwargs["text"]
        assert not text.startswith("**>"), "Short message should not be folded"
        # format_message escapes special chars — "Short." becomes "Short\\."
        assert "Short" in text

    @pytest.mark.asyncio
    async def test_no_fold_for_dm(self, adapter):
        """Even long messages in DM → no fold."""
        adapter._bot = MagicMock()
        adapter._bot.send_message = AsyncMock(return_value=_make_msg(1))
        content = "This is a long message. " * 8  # >100 chars

        result = await adapter.send(
            chat_id="1879026273",
            content=content,
            metadata={"chat_type": "dm"},
        )

        assert result.success is True
        call_kwargs = adapter._bot.send_message.call_args.kwargs
        text = call_kwargs["text"]
        assert not text.startswith("**>"), "DM message should not be folded"

    @pytest.mark.asyncio
    async def test_no_fold_without_chat_type(self, adapter):
        """Missing chat_type in metadata → no fold."""
        adapter._bot = MagicMock()
        adapter._bot.send_message = AsyncMock(return_value=_make_msg(1))
        content = "Long " * 30  # >100 chars

        result = await adapter.send(
            chat_id="-1001234567890",
            content=content,
            metadata={"notify": True},  # No chat_type
        )

        assert result.success is True
        call_kwargs = adapter._bot.send_message.call_args.kwargs
        text = call_kwargs["text"]
        assert not text.startswith("**>"), "Missing chat_type should not fold"

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
        text = call_kwargs["text"]
        # Should NOT add another **> (already has one)
        assert not text.startswith("**>**>"), "Should not double-fold"
        # Original **> should still be there but only once
        assert text.count("**>") <= 1, "Should not add extra **>"

    @pytest.mark.asyncio
    async def test_multiline_message_gets_continuation_prefixes(self, adapter):
        """Multi-line content: first line **>, rest >."""
        adapter._bot = MagicMock()
        adapter._bot.send_message = AsyncMock(return_value=_make_msg(1))
        content = "Line one.\nLine two.\nLine three.\n" + "padding " * 30
        assert len(content) > 100

        result = await adapter.send(
            chat_id="-1001234567890",
            content=content,
            metadata={"chat_type": "group"},
        )

        assert result.success is True
        call_kwargs = adapter._bot.send_message.call_args.kwargs
        text = call_kwargs["text"]
        lines = text.split("\n")
        assert lines[0].startswith("**>"), f"First line: {lines[0][:50]}"
        for line in lines[1:]:
            assert line.startswith(">"), f"Continuation line: {line[:50]}"
