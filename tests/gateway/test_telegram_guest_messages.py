"""Telegram Bot API Guest Bots end-to-end regression coverage."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.base import MessageType
from gateway.session import build_session_key
from plugins.platforms.telegram import adapter as telegram_adapter_module

TelegramAdapter = telegram_adapter_module.TelegramAdapter


def _install_guest_result_types(monkeypatch):
    class _InputTextMessageContent:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _InlineQueryResultArticle:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

        def to_dict(self):
            return dict(self.__dict__)

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


def test_guest_handler_rejects_malformed_raw_payload(monkeypatch):
    class _Handler:
        def __init__(self, callback):
            self.callback = callback

    monkeypatch.setattr(telegram_adapter_module, "TelegramBaseHandler", _Handler)
    handler = telegram_adapter_module._guest_message_handler(object())

    assert handler.check_update(
        SimpleNamespace(api_kwargs={"guest_message": "not-a-dict"})
    ) is False
    assert handler.check_update(
        SimpleNamespace(api_kwargs={"guest_message": {"message_id": 1}})
    ) is False
    assert handler.check_update(
        SimpleNamespace(
            api_kwargs={
                "guest_message": {
                    "message_id": 1,
                    "guest_query_id": "query-1",
                    "chat": {"id": 7, "type": "private"},
                }
            }
        )
    ) is True


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
    async def _fake_cache(data, ext=".jpg"):
        return f"/cache/guest{ext}"

    # Upstream moved the image cache helper to an async facade; the guest path uses it directly.
    monkeypatch.setattr(
        "plugins.platforms.telegram.adapter.cache_image_from_bytes_async",
        _fake_cache,
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


@pytest.mark.asyncio
async def test_guest_long_reply_is_clipped_with_explicit_notice(monkeypatch):
    _install_guest_result_types(monkeypatch)
    adapter = _adapter()
    bot = MagicMock()
    bot.answer_guest_query = AsyncMock(
        return_value=SimpleNamespace(inline_message_id="inline-long")
    )
    adapter._bot = bot

    result = await adapter._answer_guest_query("guest-long", "x" * 6000)

    assert result.success is True
    input_content = bot.answer_guest_query.await_args.kwargs["result"].input_message_content
    assert telegram_adapter_module.utf16_len(input_content.message_text) <= 4096
    assert "truncated" in input_content.message_text.lower()
    assert "(1/" not in input_content.message_text


@pytest.mark.asyncio
async def test_guest_handler_failure_still_gets_one_safe_final_answer(monkeypatch):
    _install_guest_result_types(monkeypatch)
    adapter = _adapter()
    bot = MagicMock()
    bot.answer_guest_query = AsyncMock(
        return_value=SimpleNamespace(inline_message_id="inline-error")
    )
    bot.send_message = AsyncMock()
    adapter._bot = bot
    adapter._message_handler = AsyncMock(
        side_effect=RuntimeError("provider failed with api_key=do-not-leak")
    )
    message = _guest_message(text="question")
    event = adapter._build_message_event(message, MessageType.TEXT, update_id=99)
    event.metadata["guest_query_id"] = message.guest_query_id

    await adapter.handle_message(event)
    await asyncio.gather(*list(adapter._background_tasks))

    bot.answer_guest_query.assert_awaited_once()
    output = (
        bot.answer_guest_query.await_args.kwargs["result"]
        .input_message_content.message_text
    )
    assert "do-not-leak" not in output
    assert "couldn't complete" in output.lower()
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_guest_inline_busy_command_failure_gets_safe_answer(monkeypatch):
    """Busy-session bypass commands must still consume the guest query once."""
    _install_guest_result_types(monkeypatch)
    adapter = _adapter()
    bot = MagicMock()
    bot.answer_guest_query = AsyncMock(
        return_value=SimpleNamespace(inline_message_id="inline-busy-error")
    )
    bot.send_message = AsyncMock()
    adapter._bot = bot
    adapter._message_handler = AsyncMock(
        side_effect=RuntimeError("status failed with api_key=do-not-leak")
    )
    message = _guest_message(text="/status")
    event = adapter._build_message_event(message, MessageType.TEXT, update_id=99)
    event.metadata["guest_query_id"] = message.guest_query_id
    session_key = build_session_key(
        event.source,
        group_sessions_per_user=adapter.config.extra.get(
            "group_sessions_per_user", True
        ),
        thread_sessions_per_user=adapter.config.extra.get(
            "thread_sessions_per_user", False
        ),
    )
    active_task = asyncio.create_task(asyncio.Event().wait())
    adapter._active_sessions[session_key] = asyncio.Event()
    adapter._session_tasks[session_key] = active_task

    try:
        await adapter.handle_message(event)
    finally:
        active_task.cancel()
        await asyncio.gather(active_task, return_exceptions=True)

    bot.answer_guest_query.assert_awaited_once()
    output = (
        bot.answer_guest_query.await_args.kwargs["result"]
        .input_message_content.message_text
    )
    assert "do-not-leak" not in output
    assert "couldn't complete" in output.lower()
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_guest_media_output_uses_query_fallback_not_chat_api(monkeypatch, tmp_path):
    _install_guest_result_types(monkeypatch)
    adapter = _adapter()
    bot = MagicMock()
    bot.answer_guest_query = AsyncMock(
        return_value=SimpleNamespace(inline_message_id="inline-media")
    )
    bot.send_document = AsyncMock()
    adapter._bot = bot
    attachment = tmp_path / "guest-output.pdf"
    attachment.write_bytes(b"pdf")
    adapter._message_handler = AsyncMock(return_value=f"MEDIA:{attachment}")
    message = _guest_message(text="make a file")
    event = adapter._build_message_event(message, MessageType.TEXT, update_id=99)
    event.metadata["guest_query_id"] = message.guest_query_id

    await adapter.handle_message(event)
    await asyncio.gather(*list(adapter._background_tasks))

    bot.answer_guest_query.assert_awaited_once()
    output = (
        bot.answer_guest_query.await_args.kwargs["result"]
        .input_message_content.message_text
    )
    assert "attachment" in output.lower()
    bot.send_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_guest_context_suppresses_typing_chat_api():
    adapter = _adapter()
    bot = MagicMock()
    bot.send_chat_action = AsyncMock()
    adapter._bot = bot
    state = {"guest_query_id": "guest-typing", "answered": False}
    token = telegram_adapter_module._GUEST_QUERY_CONTEXT.set(state)
    try:
        await adapter.send_typing("-100123")
    finally:
        telegram_adapter_module._GUEST_QUERY_CONTEXT.reset(token)

    bot.send_chat_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_guest_final_sends_answer_only_once(monkeypatch):
    _install_guest_result_types(monkeypatch)
    adapter = _adapter()
    bot = MagicMock()

    async def _delayed_answer(**_kwargs):
        await asyncio.sleep(0)
        return SimpleNamespace(inline_message_id="inline-once")

    bot.answer_guest_query = AsyncMock(side_effect=_delayed_answer)
    adapter._bot = bot
    state = {
        "guest_query_id": "guest-once",
        "answered": False,
        "lock": asyncio.Lock(),
    }
    token = telegram_adapter_module._GUEST_QUERY_CONTEXT.set(state)
    try:
        results = await asyncio.gather(
            adapter.send("-100123", "first", metadata={"notify": True}),
            adapter.send("-100123", "second", metadata={"notify": True}),
        )
    finally:
        telegram_adapter_module._GUEST_QUERY_CONTEXT.reset(token)

    assert all(result.success for result in results)
    bot.answer_guest_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_guest_answer_is_not_retried(monkeypatch):
    """answerGuestQuery is one-shot even when the first call reports failure."""
    _install_guest_result_types(monkeypatch)
    adapter = _adapter()
    bot = MagicMock()
    bot.answer_guest_query = AsyncMock(side_effect=RuntimeError("network failed"))
    adapter._bot = bot
    state = adapter._new_guest_query_state("guest-failed-once")
    token = telegram_adapter_module._GUEST_QUERY_CONTEXT.set(state)
    try:
        first = await adapter.send("-100123", "first", metadata={"notify": True})
        second = await adapter.send("-100123", "second", metadata={"notify": True})
    finally:
        telegram_adapter_module._GUEST_QUERY_CONTEXT.reset(token)

    assert first.success is False
    assert second.success is True
    bot.answer_guest_query.assert_awaited_once()
