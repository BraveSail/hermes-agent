# Local Fork Modifications — Preserve During Upstream Merges

This fork tracks `NousResearch/hermes-agent` and carries a deliberately small set of local behavior. Read this file before resolving upstream conflicts.

Current upstream baseline: v0.21.2, commit `66ddd5f83c`.
The baseline was integrated with a standard Git merge (`61c5fa37c7`, merged onto `dev` as `87d31efb1b`), preserving ancestry.
Upstream split `gateway/run.py` into `run_*.py` phase modules in this release: local gateway patches
now live where upstream's structure puts them (`run_turn.py`, `run_turn_runner.py`, `turn_context.py`),
and `stream_consumer.py` gained `_push_update()` / `_display_payload()` as its single display/ledger seam.

## Non-negotiable merge rules

1. Inspect the complete implementation and tests, not only conflict hunks.
2. Prefer upstream architecture when it provides equivalent or better behavior.
3. Re-apply only the local behavior that upstream does not provide.
4. Never restore deleted compatibility code merely because it existed in the old fork.
5. Validate runtime data flow and feature markers in addition to tests.
6. Telegram runtime code now lives in `plugins/platforms/telegram/adapter.py`; do not recreate `gateway/platforms/telegram.py`.

## Retained local patch set

### 1. Telegram Bot API Guest Bots

Primary files:

- `plugins/platforms/telegram/adapter.py`
- `tests/gateway/test_telegram_guest_messages.py`

Required behavior:

- Decode raw Bot API updates containing `guest_message` even when the installed PTB version does not expose that update shape.
- Preserve `guest_query_id` through queued/background turn processing.
- Accept text, captioned media, forwarded content, and media-only guest messages.
- Route the one-shot final answer through `answerGuestQuery`; never fall through to ordinary `sendMessage`.
- Suppress progress/draft sends for guest queries, and typing chat actions entirely.
- Answer each query at most once even under concurrent callbacks; a failed or timed-out
  `answerGuestQuery` is never retried (the endpoint is one-shot).
- Route media output back through `answerGuestQuery` with a DM hint; never fall through to `sendMessage`.

Markers:

```bash
git grep -n 'guest_message\|guest_query_id\|answer_guest_query\|_GUEST_QUERY_CONTEXT' -- plugins/platforms/telegram/adapter.py tests/gateway
```

### 2. Telegram DM-only live-surface policy

Primary files:

- `gateway/run.py` (the `_allows_live_chat_surfaces` helper)
- `gateway/run_turn.py` (reasoning block, tool-progress / interim / thinking gates)
- `gateway/run_turn_runner.py` (streaming + progress-callback gates)
- `tests/gateway/test_dm_only_surfaces.py`
- `tests/gateway/test_run_progress_topics.py`

Required behavior:

- Telegram DMs may use token streaming, tool/thinking progress, interim assistant messages, and reasoning display when configured.
- Telegram groups, channels, supergroups, and guest contexts receive appropriate final responses only; live progress surfaces stay silent.
- This hard gate is Telegram-specific. Other platforms retain the upstream configurable behavior.
- Tests for generic streaming/progress mechanics must use a DM source instead of accidentally bypassing this policy.

Markers:

```bash
git grep -n '_allows_live_chat_surfaces' -- gateway/ tests/gateway
```

### 3. Structured reasoning through the native draft consumer

Primary files:

- `gateway/run_turn_runner.py` (`reasoning_callback` wiring)
- `gateway/run_turn.py` (trailing reasoning block, gated to DMs)
- `gateway/stream_consumer.py` (`_REASONING` lane, bounded prefix, answer ledgers)
- `tests/gateway/test_stream_consumer_draft.py`
- `tests/gateway/test_stream_consumer_reasoning_final.py`
- `tests/gateway/test_dm_only_surfaces.py`

Required behavior:

- Connect `agent.reasoning_callback` to `GatewayStreamConsumer.on_reasoning_delta()` only when streaming, reasoning display, and the Telegram DM live-surface gate are all enabled.
- Keep reasoning on a dedicated `_REASONING` queue lane so it does not pollute the assistant answer ledger.
- Accumulate incremental deltas with `+=` semantics and reset reasoning on segment breaks.
- Render a bounded `💭 **Reasoning:**` prefix through the upstream native draft path.
- Strip the presentation-only reasoning prefix during final reconciliation so the final answer is not sent twice.
- The FINAL frame drops the prefix (`not tick.got_done` in `_push_update`): streaming already showed the
  reasoning, and keeping it would deliver the answer with a copy glued on top. Non-streaming turns are
  unaffected — there the prepend path is the only way reasoning is ever seen.

Markers:

```bash
git grep -n 'on_reasoning_delta\|_REASONING\|reasoning_streamed\|_strip_reasoning_prefix' -- gateway/ tests/gateway
```

### 4. Long non-DM Telegram auto-fold

Primary files:

- `plugins/platforms/telegram/adapter.py`
- `tests/gateway/test_telegram_auto_fold.py`

Required behavior:

- Telegram non-DM replies longer than `AUTO_FOLD_THRESHOLD` start collapsed.
- Use upstream-compatible MarkdownV2 expandable-blockquote syntax; do not restore the removed global MessageEntity parser.
- Do not fold DMs, short replies, replies without trustworthy `chat_type`, or content already containing a blockquote.
- Format and split first, then wrap every overflow chunk independently so each Telegram payload is valid and remains within 4096 UTF-16 units.
- Auto-folded payloads stay on the MarkdownV2 path instead of generic rich-message delivery.

Markers:

```bash
git grep -n 'AUTO_FOLD_THRESHOLD\|_should_auto_fold\|_wrap_expandable_blockquote\|auto-fold triggered' -- plugins/platforms/telegram/adapter.py tests/gateway
```

### 5. Shared table-heading normalization

Primary files:

- `gateway/platforms/helpers.py`
- `tests/gateway/test_table_helpers.py`

Required behavior:

- GFM tables continue to render as readable heading-and-bullet groups on platforms without table syntax.
- A first cell already written as `**bold**` must produce `**bold**`, never `****bold****`.
- Comparing normalized values must still suppress a redundant first bullet.
- Keep this fix in the shared helper so Telegram and Discord use the same behavior.

Markers:

```bash
git grep -n 'heading_text\|value_text' -- gateway/platforms/helpers.py tests/gateway/test_table_helpers.py
```

## Repository convention to preserve

`AGENTS.md` contains the local hard requirement that all assistant reasoning/thinking blocks be written in Chinese. It also points future merge work back to this document.

```bash
git grep -n 'Chinese\|中文\|LOCAL_FORK_MODIFICATIONS' -- AGENTS.md
```

## Intentionally retired local patches

Do not reintroduce these unless a new, demonstrated regression requires a fresh design:

- The old `gateway/platforms/telegram.py` adapter. Upstream migrated Telegram to the bundled plugin.
- The fork-wide MessageEntity formatting/parser path. Upstream MarkdownV2 and Bot API 10.1 rich/draft paths are now canonical.
- The old Codex null-output recovery patches in `run_agent.py` and `agent/auxiliary_client.py`. Upstream `agent/codex_runtime.py` provides the replacement.
- Local `.pytest_cache` ignore work; upstream already covers pytest cache artifacts.
- Local copies of basic Markdown/table conversion that upstream now provides in shared helpers.
- The `_reasoning_display()` MessageEntity flattening for reasoning draft frames (and its test): upstream
  drafts are sent as MarkdownV2, so there are no literal markers to flatten — keep `format_message` as
  the single renderer.

## Minimum verification after an upstream merge

```bash
# No unresolved conflict markers or unmerged index entries
git grep -n -E '^(<<<<<<< |>>>>>>> )' -- .
test -z "$(git ls-files -u)"

# Syntax and local lint gate
python -m py_compile \
  gateway/run.py gateway/stream_consumer.py gateway/platforms/helpers.py \
  plugins/platforms/telegram/adapter.py
python -m pylint --errors-only \
  gateway/run.py gateway/stream_consumer.py gateway/platforms/helpers.py \
  plugins/platforms/telegram/adapter.py

# Local feature regression set
python -m pytest -q \
  tests/gateway/test_telegram_guest_messages.py \
  tests/gateway/test_dm_only_surfaces.py \
  tests/gateway/test_stream_consumer_draft.py \
  tests/gateway/test_run_progress_topics.py \
  tests/gateway/test_telegram_auto_fold.py \
  tests/gateway/test_table_helpers.py \
  tests/gateway/test_telegram_format.py
```

Passing tests alone is insufficient: also inspect marker searches and verify the live Telegram/runtime path after deployment.

## Runtime note

Do not synchronously restart the gateway from inside an active gateway turn. After deploying code/config changes, ask the user to send `/restart` (asynchronous) or restart it externally, then verify logs and Bot API behavior.
