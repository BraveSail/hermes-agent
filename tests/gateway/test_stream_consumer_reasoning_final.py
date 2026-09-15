"""Reasoning is shown while streaming, but must not be glued onto the final
answer the user is left with.

Regression: the streaming consumer built ``display_text = reasoning_prefix +
accumulated`` for *every* edit, including the final one, so the delivered answer
carried a copy of the reasoning on top. The final edit now drops the prefix.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.stream_consumer import (
    REASONING_SEPARATOR,
    GatewayStreamConsumer,
    StreamConsumerConfig,
    _Tick,
)


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


def test_reasoning_prefix_is_italic_not_fenced():
    """Local fork §3: the live reasoning prefix renders as italic commentary (*…*),
    not a ``` fenced block — Telegram clients draw fenced content as monospace."""
    adapter = _make_adapter()
    consumer = GatewayStreamConsumer(
        adapter, "12345", StreamConsumerConfig(transport="auto", chat_type="dm"),
    )
    # on_reasoning_delta only enqueues; seed the accumulator the drain loop fills.
    consumer._reasoning_accumulated = "thinking about it"

    prefix = consumer._reasoning_display_prefix()

    assert prefix.startswith("💭 **Reasoning:**\n_")  # per-line italic wrap
    assert "```" not in prefix
    assert REASONING_SEPARATOR in prefix  # reasoning is separated from the answer


def test_reasoning_prefix_italicizes_per_line():
    """Multi-paragraph reasoning must be italicized PER LINE: Telegram's MarkdownV2
    emphasis cannot span blank lines, so one wrap renders as literal markers.
    (Local fork §3 — this is the shape that was live-verified on Telegram.)"""
    adapter = _make_adapter()
    consumer = GatewayStreamConsumer(
        adapter, "12345", StreamConsumerConfig(transport="auto", chat_type="dm"),
    )
    consumer._reasoning_accumulated = "first line\n\nsecond line"

    prefix = consumer._reasoning_display_prefix()

    assert "_first line_" in prefix
    assert "_second line_" in prefix
    assert "_first line\n\nsecond line_" not in prefix


def test_reasoning_prefix_keeps_code_fences_paired_and_verbatim():
    """A fenced block inside reasoning must keep its fences verbatim (never wrapped in
    *…*), because *```* breaks the block; a line-count cut must also close a fence it
    left open — MarkdownV2 then fails to parse and the whole message degrades to raw
    markers on the client."""
    adapter = _make_adapter()
    consumer = GatewayStreamConsumer(
        adapter, "12345", StreamConsumerConfig(transport="auto", chat_type="dm"),
    )
    consumer._reasoning_accumulated = "\n".join(
        ["intro line", "```python", "print('hi')", "```", "after"]
    )

    prefix = consumer._reasoning_display_prefix()

    assert prefix.count("```") % 2 == 0        # fences stay paired
    assert "_```python_" not in prefix          # fence lines are never italicized
    assert "print('hi')" in prefix              # code body kept verbatim
    assert "_intro line_" in prefix             # prose is still per-line italic


def test_reasoning_prefix_closes_fence_left_open_by_cut():
    adapter = _make_adapter()
    consumer = GatewayStreamConsumer(
        adapter, "12345", StreamConsumerConfig(transport="auto", chat_type="dm"),
    )
    # The closing fence sits beyond the 15-line cap.
    consumer._reasoning_accumulated = "\n".join(
        ["```"] + [f"code {i}" for i in range(19)] + ["```"]
    )

    prefix = consumer._reasoning_display_prefix()

    assert prefix.count("```") % 2 == 0
    assert "more lines)" in prefix


def test_reasoning_delta_does_not_bypass_edit_interval():
    """Reasoning deltas must ride the edit-interval clock. Forcing an edit per delta
    hammered Telegram's edit rate limit (429, retry_after ~106s observed live) until the
    whole live stream died — the exact "streaming reasoning disappeared" regression."""
    adapter = _make_adapter()
    consumer = GatewayStreamConsumer(
        adapter, "12345",
        StreamConsumerConfig(transport="edit", chat_type="dm", edit_interval=10.0),
    )
    tick = _Tick(reasoning_changed=True)

    # Just edited a moment ago: a reasoning delta must NOT force an immediate edit.
    consumer._last_edit_time = time.monotonic()
    assert consumer._should_edit(tick) is False

    # Once the interval has elapsed, the reasoning block refreshes.
    consumer._last_edit_time = time.monotonic() - 20.0
    assert consumer._should_edit(tick) is True


def test_live_prefix_defers_the_separator_until_answer_text():
    """The live frame is strictly append-only (local fork): the separator is the boundary
    INTO the answer, so while no answer text exists it must not be rendered — it lands
    together with the digit the moment reasoning is done, and then answer text appends
    after them."""
    adapter = _make_adapter()
    consumer = GatewayStreamConsumer(
        adapter, "12345", StreamConsumerConfig(transport="auto", chat_type="dm"),
    )
    consumer._reasoning_accumulated = "first line\nsecond line"

    reasoning_only = consumer._reasoning_display_prefix(reasoning_done=False)
    with_sep = consumer._reasoning_display_prefix(reasoning_done=True)

    assert REASONING_SEPARATOR not in reasoning_only
    assert REASONING_SEPARATOR in with_sep
    assert with_sep.endswith(REASONING_SEPARATOR + "\n\n")


def test_strip_reasoning_prefix_handles_both_live_shapes():
    """Ledger reconciliation strips whichever shape the frame was delivered in — with the
    separator (answer had begun) or without (reasoning-only). Longest form first, so a
    shorter prefix can never strip half of a longer one."""
    consumer = GatewayStreamConsumer(
        _make_adapter(), "12345", StreamConsumerConfig(transport="auto", chat_type="dm"),
    )
    consumer._reasoning_accumulated = "thinking"

    no_sep = consumer._reasoning_display_prefix(reasoning_done=False)
    with_sep = consumer._reasoning_display_prefix(reasoning_done=True)

    assert consumer._strip_reasoning_prefix(no_sep + "answer") == "answer"
    assert consumer._strip_reasoning_prefix(with_sep + "answer") == "answer"
    assert consumer._strip_reasoning_prefix("plain text") == "plain text"


def test_live_prefix_defers_the_more_lines_digit_until_reasoning_done():
    """User-requested final form: while reasoning streams, the frame ends at a bare
    ``_... (more lines)_`` — no digit — so the whole reasoning phase is strictly
    append-only (zero repaints). The digit and the separator land TOGETHER the moment
    reasoning is done (the single allowed repaint); answer text appends after them:
    reasoning -> count -> separator -> answer."""
    consumer = GatewayStreamConsumer(
        _make_adapter(), "12345", StreamConsumerConfig(transport="auto", chat_type="dm"),
    )
    consumer._reasoning_accumulated = "\n".join(f"line {i}" for i in range(46))

    streaming = consumer._reasoning_display_prefix(reasoning_done=False)
    done = consumer._reasoning_display_prefix(reasoning_done=True)

    assert "_... (more lines)_" in streaming
    assert "(31" not in streaming
    assert REASONING_SEPARATOR not in streaming

    assert "_... (31 more lines)_" in done
    assert REASONING_SEPARATOR in done
