"""Reasoning is shown while streaming, but must not be glued onto the final
answer the user is left with.

Regression: the streaming consumer built ``display_text = reasoning_prefix +
accumulated`` for *every* edit, including the final one, so the delivered answer
carried a copy of the reasoning on top. The final edit now drops the prefix.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.stream_consumer import GatewayStreamConsumer, StreamConsumerConfig


def _make_adapter():
    adapter = MagicMock()
    adapter.MAX_MESSAGE_LENGTH = 4096
    adapter.send = AsyncMock(
        return_value=SimpleNamespace(success=True, message_id="msg_1"),
    )
    adapter.edit_message = AsyncMock(return_value=SimpleNamespace(success=True))
    adapter.supports_draft_streaming = lambda chat_type=None, metadata=None: False
    return adapter


def _delivered_texts(adapter) -> list[str]:
    """Every visible text handed to the platform, in call order."""
    texts: list[str] = []
    for call in adapter.send.call_args_list:
        if "content" in call.kwargs:
            texts.append(call.kwargs["content"])
    for call in adapter.edit_message.call_args_list:
        if "content" in call.kwargs:
            texts.append(call.kwargs["content"])
    return texts


@pytest.mark.asyncio
async def test_final_delivery_drops_the_reasoning_prefix():
    adapter = _make_adapter()
    consumer = GatewayStreamConsumer(
        adapter,
        "chat_1",
        StreamConsumerConfig(edit_interval=0),
    )

    task = asyncio.create_task(consumer.run())
    consumer.on_reasoning_delta("Let me think about this carefully.")
    consumer.on_delta("The answer is 42.")
    consumer.finish()
    await asyncio.wait_for(task, timeout=5)

    texts = _delivered_texts(adapter)
    assert texts, "nothing was delivered"

    final = texts[-1]
    assert "The answer is 42." in final
    assert "💭" not in final
    assert "Let me think about this carefully." not in final


@pytest.mark.asyncio
async def test_reasoning_still_visible_while_streaming():
    adapter = _make_adapter()
    consumer = GatewayStreamConsumer(
        adapter,
        "chat_1",
        StreamConsumerConfig(edit_interval=0),
    )

    task = asyncio.create_task(consumer.run())
    consumer.on_reasoning_delta("Thinking about the question.")
    consumer.on_delta("Partial answer so far.")
    # Give the loop a tick so an intermediate frame goes out before the finish.
    await asyncio.sleep(0.05)
    consumer.finish()
    await asyncio.wait_for(task, timeout=5)

    texts = _delivered_texts(adapter)
    assert texts, "nothing was delivered"
    assert "💭" not in texts[-1], "reasoning must not survive into the final message"
    if len(texts) > 1:
        assert any("💭" in text for text in texts[:-1]), (
            "reasoning should be visible in the streaming frames"
        )
