# Local Fork Modifications — Preserve During Upstream Merges

This repository is a local fork of `NousResearch/hermes-agent` with user-specific gateway and agent fixes layered on top of upstream. Future agents must read this file before resolving merge conflicts, especially when merging upstream release commits.

Last updated for merge target: `e71a2bd11b733f3be7cf99deafde0066c343d462` (`chore: release v0.15.1 (2026.5.29)`).
Local HEAD at documentation time: `caaddc5c398efa8819785dcadb6b0051ddcf042e`.
Merge base at documentation time: `a91a57fa5a13d516c38b07a141a9ce8a3daabeb0`.

## Non-negotiable merge rule

When upstream conflicts with one of the local features below:

1. Inspect the whole file, not only the conflict hunk.
2. Check whether upstream implements an equivalent or better version of the local feature.
3. If upstream does not have an equivalent, preserve/re-apply the local feature.
4. Do not say "took upstream" unless the feature-level behavior was actually verified.

The user explicitly wants local functionality preserved.

## Current local commit stack since merge base

- `e28401207` feat(gateway): stream reasoning inline with correct scope architecture
- `a22f5d4a7` fix(gateway): revert reasoning accumulation to += for incremental deltas
- `ade664968` fix(stream): reset reasoning on segment break, restore incremental accumulate
- `424bc4150` chore: gitignore .pytest-cache
- `c5dd89c87` fix: use *italic* (standard md) instead of _italic_ so format_message converts properly
- `dab48d859` feat: reasoning streaming via draft MessageEntity instead of markdown
- `dc83bab93` feat: final send also uses MessageEntity instead of markdown
- `15b5f3b88` fix(tests): add missing platform attribute to _guest_test_adapter
- `1b590b2fa` feat(telegram): add Bot API 10.0 Guest Bots support (guest_message + answerGuestQuery)
- `4e00e7efa` fix(telegram): register GUEST_MESSAGE handler before TEXT handler
- `4c92482b9` fix(gateway): disable streaming in non-DM chats; support forwarded/captioned guest messages
- `19b780c33` fix(gateway): gate stream consumer and interim messages on chat_type=dm
- `e34e87e2e` fix(gateway): gate reasoning display to DM only — skip prepend and trailing send in groups/channels
- `361401ad0` fix(gateway): disable reasoning/tool-progress/interim in non-DM chats; fix forwarded guest msgs
- `f31e030ac` fix(gateway): unify guest answerGuestQuery formatting with normal send path
- `afa56f419` feat(telegram): auto-fold long responses in non-DM chats with EXPANDABLE_BLOCKQUOTE entity
- `0c8cf0702` fix(telegram): auto-fold preserves inner markdown formatting via hybrid entities+parse_mode
- `b5b22e031` fix(telegram): compute auto-fold entity length from formatted text, not raw content
- `3d0e7f7db` debug: add auto-fold trigger log
- `09c10e39a` test: add auto-fold tests, fix entity length computation
- `a5b18c4e3` fix(telegram): auto-fold via MarkdownV2 **> syntax instead of entities
- `8b97788d3` fix(telegram): auto-fold via entities-only (no parse_mode)
- `127832b1c` fix(telegram): ~~strikethrough~~ and _italic_ in markdown parser
- `76d212034` feat(telegram): convert markdown headers (###) to bold entities
- `7ce1b49ce` docs: reasoning language convention - Chinese in AGENTS.md
- `43ed37818` docs: strengthen Chinese reasoning directive in AGENTS.md
- `e233d85be` fix(gateway/telegram): strip existing bold markers in table heading wrapper
- `caaddc5c3` fix(agent): recover Codex Responses streams with null output

## Files with local changes

- `.gitignore`
- `AGENTS.md`
- `agent/auxiliary_client.py`
- `gateway/platforms/base.py`
- `gateway/platforms/telegram.py`
- `gateway/run.py`
- `gateway/stream_consumer.py`
- `run_agent.py`
- `scripts/release.py`
- `tests/gateway/test_run_progress_topics.py`
- `tests/gateway/test_stream_consumer_draft.py`
- `tests/gateway/test_telegram_auto_fold.py`
- `tests/gateway/test_telegram_format.py`

Expected conflict files when merging `e71a2bd11b733f3be7cf99deafde0066c343d462`:

- `.gitignore`
- `agent/auxiliary_client.py`
- `gateway/platforms/telegram.py`
- `gateway/run.py`
- `gateway/stream_consumer.py`
- `run_agent.py`
- `tests/gateway/test_telegram_format.py`

`AGENTS.md`, `gateway/platforms/base.py`, `scripts/release.py`, `tests/gateway/test_run_progress_topics.py`, and `tests/gateway/test_stream_consumer_draft.py` may auto-merge but still need feature-level verification.

## Feature inventory to preserve

### 1. Telegram Bot API 10.0 Guest Bots support

Primary files:

- `gateway/platforms/telegram.py`
- `gateway/platforms/base.py`
- `gateway/run.py`
- `tests/gateway/test_telegram_format.py` and related gateway tests

Local-only markers before the v0.15.1 merge:

- `guest_message`
- `guest_query_id`
- `answer_guest_query`
- `GUEST_MESSAGE`

Required behavior:

- Telegram adapter handles `Update.guest_message` updates via a dedicated handler.
- Guest messages are not confused with normal membership-based group messages.
- Responses to guest messages use `answerGuestQuery` / PTB `answer_guest_query`, not ordinary `send_message`.
- Guest response formatting must go through the same normalized formatting path as ordinary Telegram sends.
- Forwarded and captioned guest messages must be handled.
- Handler ordering matters: the dedicated `GUEST_MESSAGE` handler must be registered before broad text handlers so guest updates are not swallowed.

Merge guidance:

- If upstream has no `guest_message` / `guest_query_id` / `answer_guest_query` support, keep local implementation.
- Do not remove local guest tests unless upstream adds equivalent coverage.
- If upstream has refactored Telegram source/message classes, port the local `guest_query_id` plumbing into the new shape.

Validation markers:

```bash
git grep -n 'guest_message\|guest_query_id\|answer_guest_query\|GUEST_MESSAGE' -- gateway/platforms/telegram.py gateway/run.py gateway/platforms/base.py tests/gateway
```

### 2. Reasoning streaming/display architecture for Telegram gateway

Primary files:

- `gateway/run.py`
- `gateway/stream_consumer.py`
- `gateway/platforms/telegram.py`
- `tests/gateway/test_stream_consumer_draft.py`
- `tests/gateway/test_run_progress_topics.py`

Local markers:

- `on_reasoning_delta`
- `_REASONING`
- reasoning accumulation state in `gateway/stream_consumer.py`
- DM-only guards around reasoning prepend/trailing send paths

Required behavior:

- Reasoning deltas stream inline during generation for DMs when reasoning display is enabled.
- Reasoning accumulation uses incremental `+=` semantics; do not reset on each delta except on explicit segment break.
- Segment breaks reset reasoning correctly so stale reasoning does not bleed into later response sections.
- Non-DM chats must not receive reasoning, tool-progress, interim/draft streaming, or streaming consumer output.
- The final response path must not prepend or send trailing `💭 Reasoning` in groups/channels/guest contexts.

Merge guidance:

- Upstream has historically removed or refactored reasoning streaming; do not accept such removal unless an equivalent user-visible reasoning stream remains.
- Check the whole `gateway/stream_consumer.py`; conflict hunks alone are insufficient.
- If upstream rewrites the stream consumer, port the local reasoning channel (`on_reasoning_delta`, accumulated reasoning text, `_REASONING` marker handling, DM-only gating).

Validation markers:

```bash
git grep -n 'on_reasoning_delta\|_REASONING' -- gateway/run.py gateway/stream_consumer.py run_agent.py tests/gateway
git grep -n 'chat_type.*dm\|source.chat_type' -- gateway/run.py gateway/stream_consumer.py gateway/platforms/base.py
```

### 3. Telegram MessageEntity-first formatting

Primary files:

- `gateway/platforms/telegram.py`
- `gateway/stream_consumer.py`
- `tests/gateway/test_telegram_format.py`
- `tests/gateway/test_stream_consumer_draft.py`

Required behavior:

- Draft/streaming Telegram messages use explicit `MessageEntity` objects, not Markdown parse mode, because Telegram parse mode does not reliably apply during edits/draft frames.
- Final sends also use entities where needed, avoiding mixed parse mode + entities.
- Standard markdown support includes:
  - `*italic*`
  - `_italic_`
  - `**bold**`
  - `~~strikethrough~~`
  - headings like `### Heading` converted to bold entities
- Existing bold markers are stripped/normalized when wrapping table headings, avoiding doubled `**` artifacts.

Merge guidance:

- This codebase should stay entity-driven for Telegram formatting. Do not introduce a one-off parse_mode solution for one feature if entities already handle it.
- Entities and parse_mode are mutually exclusive in Telegram; sending both can cause entities to be ignored.
- Keep tests that assert entity offsets/lengths, especially UTF-16-sensitive offsets.

Validation markers:

```bash
git grep -n '_parse_markdown_to_entities\|MessageEntity\|EXPANDABLE_BLOCKQUOTE' -- gateway/platforms/telegram.py gateway/stream_consumer.py tests/gateway
```

### 4. Auto-fold long non-DM Telegram responses

Primary files:

- `gateway/platforms/telegram.py`
- `gateway/platforms/base.py`
- `tests/gateway/test_telegram_auto_fold.py`
- `tests/gateway/test_telegram_format.py`

Local-only markers before the v0.15.1 merge:

- `EXPANDABLE_BLOCKQUOTE`
- auto-fold logging/comments
- auto-fold tests

Required behavior:

- Non-DM Telegram replies longer than the configured threshold are wrapped in an expandable blockquote entity.
- Auto-fold is entities-only: no parse mode mixing.
- Inner markdown formatting is preserved by first parsing markdown into plain text + entities, then wrapping the full text in an `EXPANDABLE_BLOCKQUOTE` entity.
- Entity length is computed from formatted/plain text, not raw markdown content.
- Tables should be rewritten for Telegram-friendly display; Telegram has no table syntax.

Merge guidance:

- If upstream lacks `EXPANDABLE_BLOCKQUOTE` handling, keep local implementation.
- Keep `tests/gateway/test_telegram_auto_fold.py`; it protects the behavior most likely to regress.

Validation markers:

```bash
git grep -n 'EXPANDABLE_BLOCKQUOTE\|auto-fold' -- gateway/platforms/telegram.py gateway/platforms/base.py tests/gateway
```

### 5. Non-DM safety gates for gateway streaming/progress/reasoning

Primary files:

- `gateway/run.py`
- `gateway/stream_consumer.py`
- `gateway/platforms/base.py`
- `gateway/platforms/telegram.py`

Required behavior:

- DMs can stream/interim/progress/reasoning when configured.
- Groups/channels/guest contexts should receive only appropriate final responses, not reasoning or noisy progress frames.
- `MessageSource.chat_type` or equivalent must be propagated accurately.
- Forwarded guest messages and captioned messages must not bypass these gates.

Merge guidance:

- If upstream modifies message source/session handling, preserve the `chat_type` semantics.
- Check both the streaming path and non-streaming final response path; reasoning can leak from either.

Validation markers:

```bash
git grep -n 'chat_type' -- gateway/platforms/base.py gateway/platforms/telegram.py gateway/run.py gateway/stream_consumer.py
```

### 6. Codex Responses null-output recovery

Primary files:

- `run_agent.py`
- `agent/auxiliary_client.py`
- `scripts/release.py`

Local markers:

- `_responses_null_output_iterable_error`
- `_codex_backfilled_response`
- `_responses_backfilled_response`
- `carltonawong` in `scripts/release.py` `AUTHOR_MAP`

Required behavior:

- Codex/OpenAI Responses streams that emit usable output events but later produce `response.completed.output=null` must not abort with `TypeError: 'NoneType' object is not iterable`.
- Main agent Codex path recovers from collected `response.output_item.done` items or text deltas.
- Auxiliary Codex path uses the same recovery for compression/title/vision-related auxiliary calls.
- `output=None` and `output=[]` are both handled.
- Tool-call responses must not be collapsed into plain text just because incidental text deltas exist.

Merge guidance:

- Upstream v0.15.1 target did not contain these marker functions before the merge. Preserve them unless upstream has an equivalent fix.
- If upstream moved Codex runtime code out of `run_agent.py`, map the recovery into the new module rather than dropping it.

Validation markers:

```bash
git grep -n '_responses_null_output_iterable_error\|_codex_backfilled_response\|_responses_backfilled_response' -- run_agent.py agent/auxiliary_client.py
git grep -n 'carltonawong' -- scripts/release.py
```

### 7. AGENTS.md Chinese reasoning directive

Primary file:

- `AGENTS.md`

Required behavior:

- Root `AGENTS.md` must tell future assistants: all reasoning/thinking blocks must be in Chinese.
- The directive should appear near the top, before general development notes.
- Keep the local-fork preservation entry pointing to this document.

Validation markers:

```bash
git grep -n 'Chinese\|中文\|LOCAL_FORK_MODIFICATIONS' -- AGENTS.md
```

### 8. Minor local maintenance

- `.gitignore`: keep `.pytest-cache` ignored if upstream does not already include it.
- Tests: keep local tests that cover Telegram guest mode, auto-fold, MessageEntity formatting, and reasoning stream behavior.

## Conflict-resolution checklist for e71a2bd11b733f3be7cf99deafde0066c343d462

Before resolving:

```bash
BASE=$(git merge-base HEAD FETCH_HEAD)
git log --oneline --no-merges $BASE..HEAD
git diff --name-only $BASE..HEAD | sort
git diff --name-only $BASE..FETCH_HEAD | sort
comm -12 <(git diff --name-only $BASE..HEAD | sort) <(git diff --name-only $BASE..FETCH_HEAD | sort)
```

Predicted content conflicts:

```text
.gitignore
agent/auxiliary_client.py
gateway/platforms/telegram.py
gateway/run.py
gateway/stream_consumer.py
run_agent.py
tests/gateway/test_telegram_format.py
```

Recommended per-file strategy:

- `.gitignore`: take union; preserve `.pytest-cache` ignore.
- `AGENTS.md`: take union; preserve Chinese reasoning directive and the `LOCAL_FORK_MODIFICATIONS.md` entry.
- `agent/auxiliary_client.py`: take upstream structure, re-apply Codex null-output auxiliary recovery if missing.
- `run_agent.py`: take upstream structure, re-apply Codex null-output main-agent recovery if missing; preserve `on_reasoning_delta` callback plumbing if upstream lacks it.
- `gateway/platforms/base.py`: preserve `chat_type`/source metadata used by DM/non-DM gates.
- `gateway/platforms/telegram.py`: preserve guest-message support, entity-first formatting, auto-fold, markdown entity parsing, handler ordering, and answerGuestQuery send path.
- `gateway/run.py`: preserve DM-only gates for streaming/progress/reasoning and guest-message final send semantics.
- `gateway/stream_consumer.py`: preserve reasoning streaming, segment reset, MessageEntity draft formatting, and non-DM gating.
- `tests/gateway/test_telegram_format.py`: take union; preserve assertions for markdown entities, guest formatting, and table/heading cleanup.
- `tests/gateway/test_telegram_auto_fold.py`: keep file even if upstream lacks it.

## Required verification after merge

Run at minimum:

```bash
# No conflict markers
git grep -n '<<<<<<<\|=======\|>>>>>>' -- .

# Syntax checks
venv/bin/python - <<'PY'
import py_compile
for f in [
    'run_agent.py',
    'agent/auxiliary_client.py',
    'gateway/platforms/base.py',
    'gateway/platforms/telegram.py',
    'gateway/run.py',
    'gateway/stream_consumer.py',
    'scripts/release.py',
]:
    py_compile.compile(f, doraise=True)
    print(f, 'OK')
PY

# Pylint errors-only on modified Python files
venv/bin/python -m pylint run_agent.py agent/auxiliary_client.py gateway/platforms/base.py gateway/platforms/telegram.py gateway/run.py gateway/stream_consumer.py scripts/release.py --errors-only

# Targeted tests
venv/bin/python -m pytest \
  tests/gateway/test_telegram_format.py \
  tests/gateway/test_telegram_auto_fold.py \
  tests/gateway/test_stream_consumer_draft.py \
  tests/gateway/test_run_progress_topics.py \
  tests/run_agent/test_run_agent_codex_responses.py \
  tests/agent/test_auxiliary_client.py \
  -x -q
```

Also run marker checks from each feature section. Passing tests alone is not enough if marker checks show the local feature disappeared.

## Runtime note

After code changes are merged and pushed, do not restart the gateway from inside an agent turn. Ask the user to send `/restart` or restart externally.
