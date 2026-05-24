"""Tests for Telegram auto-fold (expandable blockquote) feature.

Ported from openclaw/extensions/telegram/src/auto-fold.ts.
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
    # ParseMode as a plain namespace (not MagicMock) so MARKDOWN_V2 resolves
    # to the string value the production code expects.
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
    # MessageEntity as a callable class mock
    _me_mock = MagicMock()
    _me_mock.EXPANDABLE_BLOCKQUOTE = "expandable_blockquote"
    _me_mock.ITALIC = "italic"
    _me_mock.BOLD = "bold"
    _me_mock.CODE = "code"
    _me_mock.STRIKETHROUGH = "strikethrough"
    _me_mock.UNDERLINE = "underline"
    _me_mock.SPOILER = "spoiler"
    mod.MessageEntity = _me_mock
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


# Fake _convert_entities returns a stable list we can assert on
_FAKE_ENTITIES = [MagicMock(type="expandable_blockquote", offset=0, length=999)]


class TestAutoFold:
    """Auto-fold: non-DM long messages get wrapped in EXPANDABLE_BLOCKQUOTE."""

    @pytest.mark.asyncio
    async def test_folds_long_message_in_group(self, adapter):
        """>100 chars in a group → EXPANDABLE_BLOCKQUOTE entity."""
        adapter._bot = MagicMock()
        adapter._bot.send_message = AsyncMock(return_value=_make_msg(1))
        content = "This is a long message. " * 8  # ~200 chars
        assert len(content) > 100

        with patch.object(
            adapter, "_convert_entities", return_value=_FAKE_ENTITIES,
        ) as mock_convert:
            result = await adapter.send(
                chat_id="-1001234567890",
                content=content,
                metadata={"chat_type": "group"},
            )

        assert result.success is True
        assert adapter._bot.send_message.called
        call_kwargs = adapter._bot.send_message.call_args.kwargs
        assert call_kwargs["entities"] == _FAKE_ENTITIES
        # Hybrid mode: should include parse_mode for inner formatting
        assert "parse_mode" in call_kwargs, "Hybrid path must include parse_mode"
        # Verify _convert_entities was called with formatted (not raw) text
        mock_convert.assert_called_once()
        _text_arg = mock_convert.call_args[0][0]
        # format_message escapes dots → formatted text differs from raw
        assert _text_arg != content, "Should receive formatted text, not raw"

    @pytest.mark.asyncio
    async def test_no_fold_for_short_message(self, adapter):
        """≤100 chars → no auto-fold."""
        adapter._bot = MagicMock()
        adapter._bot.send_message = AsyncMock(return_value=_make_msg(1))
        content = "Short."
        assert len(content) <= 100

        with patch.object(adapter, "_convert_entities") as mock_convert:
            result = await adapter.send(
                chat_id="-1001234567890",
                content=content,
                metadata={"chat_type": "group"},
            )

        assert result.success is True
        call_kwargs = adapter._bot.send_message.call_args.kwargs
        assert call_kwargs.get("entities") is None
        mock_convert.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_fold_for_dm(self, adapter):
        """Even long messages in DM → no fold."""
        adapter._bot = MagicMock()
        adapter._bot.send_message = AsyncMock(return_value=_make_msg(1))
        content = "This is a long message. " * 8  # >100 chars

        with patch.object(adapter, "_convert_entities") as mock_convert:
            result = await adapter.send(
                chat_id="1879026273",
                content=content,
                metadata={"chat_type": "dm"},
            )

        assert result.success is True
        call_kwargs = adapter._bot.send_message.call_args.kwargs
        assert call_kwargs.get("entities") is None
        mock_convert.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_fold_without_chat_type(self, adapter):
        """Missing chat_type in metadata → no fold."""
        adapter._bot = MagicMock()
        adapter._bot.send_message = AsyncMock(return_value=_make_msg(1))
        content = "Long " * 30  # >100 chars

        with patch.object(adapter, "_convert_entities") as mock_convert:
            result = await adapter.send(
                chat_id="-1001234567890",
                content=content,
                metadata={"notify": True},  # No chat_type
            )

        assert result.success is True
        call_kwargs = adapter._bot.send_message.call_args.kwargs
        assert call_kwargs.get("entities") is None
        mock_convert.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_fold_when_blockquote_present(self, adapter):
        """Content already has **> → skip auto-fold."""
        adapter._bot = MagicMock()
        adapter._bot.send_message = AsyncMock(return_value=_make_msg(1))
        content = "**> already a blockquote || " + "padding " * 10
        assert len(content) > 100

        with patch.object(adapter, "_convert_entities") as mock_convert:
            result = await adapter.send(
                chat_id="-1001234567890",
                content=content,
                metadata={"chat_type": "group"},
            )

        assert result.success is True
        call_kwargs = adapter._bot.send_message.call_args.kwargs
        assert call_kwargs.get("entities") is None
        mock_convert.assert_not_called()
