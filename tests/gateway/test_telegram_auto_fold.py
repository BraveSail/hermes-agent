"""Tests for Telegram's local non-DM auto-fold policy.

The upstream adapter already understands Telegram MarkdownV2 expandable
blockquotes.  The fork only restores the policy trigger: long non-DM replies
are wrapped using that syntax, without reviving the removed entity parser.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import PlatformConfig
from plugins.platforms.telegram.adapter import TelegramAdapter


@pytest.fixture()
def adapter():
    instance = TelegramAdapter(PlatformConfig(enabled=True, token="fake-token"))
    instance._bot = MagicMock()
    instance._bot.send_message = AsyncMock(
        return_value=SimpleNamespace(message_id=1)
    )
    instance._bot.send_chat_action = AsyncMock()
    return instance


async def _send(adapter, content: str, *, chat_type=None):
    metadata = {"notify": True}
    if chat_type is not None:
        metadata["chat_type"] = chat_type
    result = await adapter.send(
        chat_id="12345" if chat_type == "dm" else "-1001234567890",
        content=content,
        metadata=metadata,
    )
    assert result.success is True
    return adapter._bot.send_message.call_args.kwargs


class TestAutoFold:
    """Long non-DM replies use MarkdownV2 expandable-blockquote syntax."""

    @pytest.mark.asyncio
    async def test_folds_long_message_in_group(self, adapter):
        content = "This is a long **message**. " * 8
        assert len(content) > 100

        call_kwargs = await _send(adapter, content, chat_type="group")

        text = call_kwargs["text"]
        assert text.startswith("**> ")
        assert text.endswith("||")
        assert "*message*" in text
        assert call_kwargs.get("parse_mode") is not None
        assert "entities" not in call_kwargs

    @pytest.mark.asyncio
    async def test_multiline_fold_quotes_every_line_and_keeps_close_marker(self, adapter):
        content = "First long line " * 5 + "\n" + "Second long line " * 5
        assert len(content) > 100

        call_kwargs = await _send(adapter, content, chat_type="supergroup")

        text = call_kwargs["text"]
        lines = text.splitlines()
        assert lines[0].startswith("**> ")
        assert lines[1].startswith("> ")
        assert text.endswith("||")
        assert "\\|\\|" not in text

    @pytest.mark.asyncio
    async def test_each_overflow_chunk_is_independently_folded(self, adapter):
        content = "longword " * 800

        result = await adapter.send(
            chat_id="-1001234567890",
            content=content,
            metadata={"chat_type": "group", "notify": True},
        )

        assert result.success is True
        calls = adapter._bot.send_message.call_args_list
        assert len(calls) > 1
        assert all(call.kwargs["text"].startswith("**> ") for call in calls)
        assert all(call.kwargs["text"].endswith("||") for call in calls)

    @pytest.mark.asyncio
    async def test_no_fold_for_short_message(self, adapter):
        call_kwargs = await _send(adapter, "Short.", chat_type="group")
        assert not call_kwargs["text"].startswith("**> ")
        assert not call_kwargs["text"].endswith("||")

    @pytest.mark.asyncio
    async def test_no_fold_for_dm(self, adapter):
        content = "This is a long message. " * 8
        call_kwargs = await _send(adapter, content, chat_type="dm")
        assert not call_kwargs["text"].startswith("**> ")
        assert not call_kwargs["text"].endswith("||")

    @pytest.mark.asyncio
    async def test_no_fold_without_chat_type(self, adapter):
        call_kwargs = await _send(adapter, "Long " * 30)
        assert not call_kwargs["text"].startswith("**> ")
        assert not call_kwargs["text"].endswith("||")

    @pytest.mark.asyncio
    async def test_no_double_fold_when_blockquote_present(self, adapter):
        content = "**> already expandable " + "padding " * 15 + "||"
        assert len(content) > 100

        call_kwargs = await _send(adapter, content, chat_type="group")

        assert call_kwargs["text"].count("**>") == 1
