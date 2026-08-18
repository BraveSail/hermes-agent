"""Telegram Bot API Guest Bots end-to-end regression coverage."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.base import MessageType
from plugins.platforms.telegram import adapter as telegram_adapter_module

TelegramAdapter = telegram_adapter_module.TelegramAdapter


def _adapter() -> TelegramAdapter:
    adapter = TelegramAdapter(
        PlatformConfig(
            enabled=True,
            token="test-token",
            typing_indicator=False,
            extra={"guest_mode": True},
        )
    )
    adapter._is_callback_user_authorized = lambda _user_id, **_kwargs: True
    return adapter


def _guest_message(*, text=None, caption=None, photo=None, forward_origin=None):
    chat = SimpleNamespace(
        id=-100123,
        type="supergroup",
        title="Guest group",
        full_name=None,
        is_forum=False,
    )
    user = SimpleNamespace(
        id=42,
        full_name="Guest User",
        username="guest",
        is_bot=False,
    )
    return SimpleNamespace(
        message_id=7,
        guest_query_id="guest-query-7",
        chat=chat,
        from_user=user,
        text=text,
        caption=caption,
        date=datetime.now(timezone.utc),
        entities=[],
        caption_entities=[],
        message_thread_id=None,
        is_topic_message=False,
        reply_to_message=None,
        quote=None,
        forum_topic_created=None,
        media_group_id=None,
        forward_origin=forward_origin,
        forward_from=None,
        sticker=None,
        photo=photo,
        video=None,
        audio=None,
        voice=None,
        document=None,
    )


def _guest_update(message):
    return SimpleNamespace(
        update_id=99,
        guest_message=message,
        message=None,
        effective_message=message,
        api_kwargs={},
    )


def test_guest_handler_is_registered_before_broad_text_handler(monkeypatch):
    class _Handler:
        def __init__(self, *args, **kwargs):
            del kwargs
            self.callback = args[-1]

        def check_update(self, _update):
            return False

    monkeypatch.setattr(telegram_adapter_module, "TelegramBaseHandler", _Handler)
    monkeypatch.setattr(telegram_adapter_module, "TelegramMessageHandler", _Handler)
    adapter = _adapter()
    app = MagicMock()

    adapter._register_handlers(app)

    callbacks = [call.args[0].callback for call in app.add_handler.call_args_list]
    assert callbacks.index(adapter._handle_guest_message) < callbacks.index(
        adapter._handle_text_message
    )


def test_raw_guest_payload_is_decoded_when_ptb_update_type_is_missing():
    """Older PTB retains unknown Bot API fields in Update.api_kwargs."""
    adapter = _adapter()
    bot = MagicMock()
    update = SimpleNamespace(
        guest_message=None,
        api_kwargs={
            "guest_message": {
                "message_id": 8,
                "date": 0,
                "chat": {"id": 123, "type": "private"},
                "from": {
                    "id": 42,
                    "is_bot": False,
                    "first_name": "Guest",
                },
                "guest_query_id": "raw-query",
                "text": "from raw Bot API payload",
            }
        },
    )

    class _LegacyMessage:
        @staticmethod
        def de_json(data, _bot):
            return SimpleNamespace(
                guest_query_id=None,
                api_kwargs={"guest_query_id": data["guest_query_id"]},
                text=data["text"],
                chat=SimpleNamespace(**data["chat"]),
            )

    original_message = telegram_adapter_module.Message
    telegram_adapter_module.Message = _LegacyMessage
    try:
        message = adapter._guest_message_from_update(update, bot)
    finally:
        telegram_adapter_module.Message = original_message

    assert adapter._guest_query_id_from_message(message) == "raw-query"
    assert message.text == "from raw Bot API payload"
    assert message.chat.id == 123


@pytest.mark.asyncio
async def test_guest_forwarded_text_builds_event_with_query_metadata():
    adapter = _adapter()
    adapter.handle_message = AsyncMock()
    origin = SimpleNamespace(
        type="user",
        sender_user=SimpleNamespace(full_name="Forwarded User"),
    )

    await adapter._handle_guest_message(
        _guest_update(
            _guest_message(text="forwarded body", forward_origin=origin)
        ),
        SimpleNamespace(bot=MagicMock()),
    )

    event = adapter.handle_message.await_args.args[0]
    assert event.message_type == MessageType.TEXT
    assert event.text == "[Forwarded user from Forwarded User] forwarded body"
    assert event.metadata["guest_query_id"] == "guest-query-7"


@pytest.mark.asyncio
async def test_guest_captioned_photo_uses_normal_media_download_path(monkeypatch):
    adapter = _adapter()
    adapter.handle_message = AsyncMock()
    telegram_file = SimpleNamespace(
        file_path="photos/guest.png",
        download_as_bytearray=AsyncMock(return_value=bytearray(b"image bytes")),
    )
    photo = SimpleNamespace(get_file=AsyncMock(return_value=telegram_file))
    monkeypatch.setattr(
        "plugins.platforms.telegram.adapter.cache_image_from_bytes",
        lambda data, ext: f"/cache/guest{ext}",
    )

    await adapter._handle_guest_message(
        _guest_update(_guest_message(caption="look at this", photo=[photo])),
        SimpleNamespace(bot=MagicMock()),
    )

    event = adapter.handle_message.await_args.args[0]
    photo.get_file.assert_awaited_once()
    telegram_file.download_as_bytearray.assert_awaited_once()
    assert event.message_type == MessageType.PHOTO
    assert event.text == "look at this"
    assert event.media_urls == ["/cache/guest.png"]
    assert event.media_types == ["image/png"]
    assert event.metadata["guest_query_id"] == "guest-query-7"


@pytest.mark.asyncio
async def test_guest_final_reply_uses_formatted_answer_guest_query_not_send_message(
    monkeypatch,
):
    class _InputTextMessageContent:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _InlineQueryResultArticle:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    monkeypatch.setattr(
        telegram_adapter_module,
        "InputTextMessageContent",
        _InputTextMessageContent,
    )
    monkeypatch.setattr(
        telegram_adapter_module,
        "InlineQueryResultArticle",
        _InlineQueryResultArticle,
    )
    adapter = _adapter()
    bot = MagicMock()
    bot.answer_guest_query = AsyncMock(
        return_value=SimpleNamespace(inline_message_id="inline-1")
    )
    bot.send_message = AsyncMock()
    adapter._bot = bot
    adapter._message_handler = AsyncMock(return_value="**Bold** & plain")
    message = _guest_message(text="question")
    event = adapter._build_message_event(message, MessageType.TEXT, update_id=99)
    event.metadata["guest_query_id"] = message.guest_query_id

    await adapter.handle_message(event)
    background_tasks = list(adapter._background_tasks)
    assert background_tasks
    await __import__("asyncio").gather(*background_tasks)

    bot.answer_guest_query.assert_awaited_once()
    call = bot.answer_guest_query.await_args
    assert call.kwargs["guest_query_id"] == "guest-query-7"
    input_content = call.kwargs["result"].input_message_content
    assert input_content.message_text == adapter.format_message("**Bold** & plain")
    assert input_content.parse_mode == "MarkdownV2"
    bot.send_message.assert_not_awaited()
