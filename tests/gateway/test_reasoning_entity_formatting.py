"""The reasoning block must render its markdown as real formatting.

Draft frames can only carry entities (there is no ``parse_mode`` on the draft
transport), so the markdown a thinking model emits gets flattened into
(plain text, entities).  Only the italic wrapper used to be described, which
left ``**bold**`` and ``` fences visible as literal markers.
"""

from __future__ import annotations

from gateway.stream_consumer import _reasoning_display


def test_inline_bold_and_code_are_flattened():
    plain, entities = _reasoning_display("text **bold** and `code` here")

    assert plain == "text bold and code here"
    assert entities == [
        {"type": "bold", "offset": 5, "length": 4},
        {"type": "code", "offset": 14, "length": 4},
    ]


def test_fenced_code_keeps_its_body_and_is_marked_pre():
    plain, entities = _reasoning_display("before\n```python\nx = 1\n```\nafter")

    # The markers (and the ```python hint) are dropped and the body is marked
    # as pre; the surrounding newlines stay exactly as they were written.
    assert plain == "before\nx = 1\n\nafter"
    assert entities == [{"type": "pre", "offset": 7, "length": 6}]


def test_markup_inside_a_fence_stays_literal():
    """A ``**`` inside a code fence must not become a bold entity."""
    plain, entities = _reasoning_display("```\n**not bold**\n```")

    assert plain == "**not bold**\n"
    assert [entity["type"] for entity in entities] == ["pre"]


def test_plain_text_without_markup_is_unchanged():
    plain, entities = _reasoning_display("just thinking out loud")

    assert plain == "just thinking out loud"
    assert entities == []
