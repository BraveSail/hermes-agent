"""Local policy tests for Telegram DM-only live/reasoning surfaces."""

from __future__ import annotations

import importlib
import sys
import time
import types
from types import SimpleNamespace

import pytest
import yaml

from gateway.config import Platform, PlatformConfig, StreamingConfig
from gateway.platforms.base import BasePlatformAdapter, SendResult
from gateway.session import SessionSource


class _CaptureAdapter(BasePlatformAdapter):
    def __init__(self):
        super().__init__(PlatformConfig(enabled=True, token="***"), Platform.TELEGRAM)
        self.sent: list[dict] = []
        self.edits: list[dict] = []

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def send(self, chat_id, content, reply_to=None, metadata=None) -> SendResult:
        self.sent.append(
            {
                "chat_id": chat_id,
                "content": content,
                "reply_to": reply_to,
                "metadata": metadata,
            }
        )
        return SendResult(success=True, message_id="stream-1")

    async def edit_message(
        self,
        chat_id,
        message_id,
        content,
        *,
        finalize=False,
        metadata=None,
    ) -> SendResult:
        self.edits.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "content": content,
                "finalize": finalize,
                "metadata": metadata,
            }
        )
        return SendResult(success=True, message_id=message_id)

    async def send_typing(self, chat_id, metadata=None) -> None:
        return None

    async def stop_typing(self, chat_id) -> None:
        return None

    async def get_chat_info(self, chat_id: str):
        return {"id": chat_id}


class _SurfaceCaptureAgent:
    seen: dict[str, object] = {}

    def __init__(self, **kwargs):
        self.tools = []
        self.tool_progress_callback = kwargs.get("tool_progress_callback")

    def run_conversation(self, message, conversation_history=None, task_id=None):
        del message, conversation_history, task_id
        type(self).seen = {
            "tool": getattr(self, "tool_progress_callback", None),
            "stream": getattr(self, "stream_delta_callback", None),
            "reasoning": getattr(self, "reasoning_callback", None),
            "interim": getattr(self, "interim_assistant_callback", None),
        }
        for name, args in (
            ("tool", ("tool.started", "terminal", "pwd", {})),
            ("reasoning", ("inspect the request",)),
            ("interim", ("I will inspect it.",)),
            ("stream", ("done",)),
        ):
            callback = type(self).seen[name]
            if callback is not None:
                callback(*args)
        time.sleep(0.08)
        return {
            "final_response": "done",
            "last_reasoning": "inspect the request",
            "messages": [],
            "api_calls": 1,
        }


def _make_runner(adapter):
    gateway_run = importlib.import_module("gateway.run")
    runner = object.__new__(gateway_run.GatewayRunner)
    runner.adapters = {adapter.platform: adapter}
    runner._voice_mode = {}
    runner._prefill_messages = []
    runner._ephemeral_system_prompt = ""
    runner._reasoning_config = None
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._session_db = None
    runner._running_agents = {}
    runner._session_run_generation = {}
    runner.session_store = SimpleNamespace(_entries={}, _save=lambda: None)
    runner.hooks = SimpleNamespace(loaded_hooks=False)
    runner.config = SimpleNamespace(
        thread_sessions_per_user=False,
        group_sessions_per_user=False,
        stt_enabled=False,
        streaming=StreamingConfig(
            enabled=True,
            transport="edit",
            edit_interval=0.01,
            buffer_threshold=1,
            cursor="",
        ),
    )
    return runner


def _install_agent(monkeypatch):
    fake_dotenv = types.ModuleType("dotenv")
    fake_dotenv.load_dotenv = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)
    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = _SurfaceCaptureAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)


@pytest.mark.asyncio
async def test_telegram_group_disables_all_live_surfaces(monkeypatch, tmp_path):
    """Telegram groups get only the final reply, never progress/reasoning edits."""
    (tmp_path / "config.yaml").write_text(
        yaml.dump(
            {
                "display": {
                    "tool_progress": "all",
                    "thinking_progress": True,
                    "show_reasoning": True,
                    "interim_assistant_messages": True,
                    "platforms": {"telegram": {"streaming": True}},
                }
            }
        ),
        encoding="utf-8",
    )
    _install_agent(monkeypatch)
    gateway_run = importlib.import_module("gateway.run")
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setattr(
        gateway_run,
        "_resolve_runtime_agent_kwargs",
        lambda: {"api_key": "***"},
    )

    adapter = _CaptureAdapter()
    runner = _make_runner(adapter)
    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="-100123",
        chat_type="group",
    )

    result = await runner._run_agent(
        message="hello",
        context_prompt="",
        history=[],
        source=source,
        session_id="sess-group",
        session_key="agent:main:telegram:group:-100123",
    )

    assert result["final_response"] == "done"
    assert _SurfaceCaptureAgent.seen == {
        "tool": None,
        "stream": None,
        "reasoning": None,
        "interim": None,
    }
    assert adapter.sent == []
    assert adapter.edits == []


def test_non_dm_reasoning_display_is_blocked_only_for_telegram():
    gateway_run = importlib.import_module("gateway.run")
    telegram_group = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="-100123",
        chat_type="group",
    )
    telegram_dm = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="123",
        chat_type="dm",
    )
    discord_group = SessionSource(
        platform=Platform.DISCORD,
        chat_id="456",
        chat_type="group",
    )

    assert gateway_run._allows_live_chat_surfaces(telegram_group) is False
    assert gateway_run._allows_live_chat_surfaces(telegram_dm) is True
    assert gateway_run._allows_live_chat_surfaces(discord_group) is True
