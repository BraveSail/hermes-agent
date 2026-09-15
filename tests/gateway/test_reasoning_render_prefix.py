"""Reasoning-prefix rendering regressions (star nesting + live more-lines digit).

The renderer wraps every plain line in ``*…*`` (per-line italic — MarkdownV2
emphasis cannot span blank lines). Two failure modes lived in that wrap:

1. A line already carrying the model's own emphasis markers (``**a** b``) got
   wrapped into ``***a** b*``. Neither consumer of the prefix digests the
   nesting: the draft-channel entity parser returns ``*a b*`` with a literal
   edge star, and ``format_message`` (edit/final channel) escapes the edges —
   the user sees stray ``*`` around bolded reasoning lines.
2. The more-lines note carried the exact count in the live draft. The digit
   ticks on every new reasoning line, mutating the frame mid-string; Telegram
   then repaints the whole draft instead of animating the appended tail.
"""

from __future__ import annotations

from gateway.stream_consumer import render_reasoning_prefix
from plugins.platforms.telegram.adapter import TelegramAdapter


def test_emphasis_lines_are_not_wrapped_by_the_renderer():
    out = render_reasoning_prefix("**bold** line\nplain line")
    assert "**bold** line" in out
    assert "*plain line*" in out
    assert "***bold***" not in out


def test_rendered_prefix_digests_without_literal_stars():
    """End to end through the entity parser used by the draft channel."""
    out = render_reasoning_prefix("**启动 CI 监控**（惯例如前）：\nplain tail")
    plain, entities = TelegramAdapter._parse_markdown_to_entities(out)
    assert "**" not in plain
    assert "*启动 CI 监控*" not in plain
    assert entities


def test_rendered_prefix_survives_the_markdown_channel():
    """The edit/final channel must not leave escaped-star residue on bold lines."""
    out = render_reasoning_prefix("**bold** line")
    assert "\\*bold" not in TelegramAdapter.format_message(TelegramAdapter.__new__(TelegramAdapter), out)


def test_live_frames_omit_the_more_lines_digit():
    text = "\n".join(f"line {i}" for i in range(46))
    assert "_... (31 more lines)_" in render_reasoning_prefix(text)
    live = render_reasoning_prefix(text, more_lines_count=False)
    assert "_... (more lines)_" in live
    assert "(31" not in live
