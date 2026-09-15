"""Reasoning-prefix rendering: per-line italic that survives BOTH transports.

The renderer wraps each non-code segment of a reasoning line in ``_…_`` — the one wrap
both consumers of the prefix digest as italic:

- the draft channel parses the markdown into plain text + MessageEntity ranges,
- ``format_message`` keeps ``_…_`` as MarkdownV2 italic after converting ``**…**`` → ``*…*``.

The previous ``*…*`` wrap (Standard-Markdown italic) could not co-exist with the model's
own ``**bold**`` on the same line: the nesting ``***a** b*`` is digested by neither
consumer — the entity parser returns a literal edge ``*`` and ``format_message`` escapes
the outer markers — so every bolded reasoning line lost its italic. The wrap also never
spans an inline code span: the entity parser extracts code FIRST, and a wrap pair split by
one leaks its edge markers as literal text.
"""

from __future__ import annotations

from gateway.stream_consumer import render_reasoning_prefix
from plugins.platforms.telegram.adapter import TelegramAdapter


def _live_line(reasoning: str) -> str:
    """The rendered body line for a single-line reasoning body."""
    return render_reasoning_prefix(reasoning).split("\n")[1]


def test_bold_lines_keep_the_per_line_italic_wrap():
    out = render_reasoning_prefix("**bold** line\nplain line")
    assert "_**bold** line_" in out  # the model's bold nests inside the italic wrap
    assert "_plain line_" in out
    assert "***" not in out  # never the broken triple-star nesting


def test_rendered_prefix_digests_to_italic_plus_bold():
    """End to end through the entity parser used by the draft channel."""
    out = render_reasoning_prefix("**启动 CI 监控**（惯例如前）：\nplain tail")
    plain, entities = TelegramAdapter._parse_markdown_to_entities(out)
    assert "**" not in plain
    kinds = {e["type"] for e in entities}
    assert {"italic", "bold"} <= kinds
    line = out.split("\n")[1]  # the rendered line
    italic = next(e for e in entities if e["type"] == "italic")
    assert plain[italic["offset"]:italic["offset"] + italic["length"]] == "启动 CI 监控（惯例如前）："
    assert line.startswith("_**启动 CI 监控**")


def test_rendered_prefix_survives_the_markdown_channel():
    """The edit/final channel keeps the wrap as MarkdownV2 italic, no escaped-star residue."""
    out = render_reasoning_prefix("**bold** line")
    mdv2 = TelegramAdapter.format_message(TelegramAdapter.__new__(TelegramAdapter), out)
    assert "_*bold* line_" in mdv2
    assert "\\*bold" not in mdv2


def test_inline_code_never_splits_a_wrap_pair():
    """Each text segment is wrapped separately so the code-first entity parser cannot cut a
    wrap pair in half (a split pair leaks its edge underscores as literal text)."""
    rendered = _live_line("- 依赖 = `github.com/metacubex/tailscale`（fork）")
    plain, entities = TelegramAdapter._parse_markdown_to_entities(rendered)
    assert "_" not in plain  # no leaked edge underscores
    assert any(e["type"] == "code" for e in entities)
    assert sum(1 for e in entities if e["type"] == "italic") == 2  # both text segments


def test_self_marked_segment_is_left_unwrapped():
    """``*a*`` already renders as emphasis in both channels; an outer wrap would collapse
    into it as ``__a__`` (MarkdownV2 underline) instead of nesting."""
    rendered = _live_line("*要点：*")
    assert rendered == "*要点：*"
    assert TelegramAdapter.format_message(
        TelegramAdapter.__new__(TelegramAdapter), rendered) == "_要点：_"


def test_live_frames_omit_the_more_lines_digit():
    text = "\n".join(f"line {i}" for i in range(46))
    assert "_... (31 more lines)_" in render_reasoning_prefix(text)
    live = render_reasoning_prefix(text, more_lines_count=False)
    assert "_... (more lines)_" in live
    assert "(31" not in live
