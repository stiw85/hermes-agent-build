"""Native learning memory: a local MemoryProvider that recalls conclusions with premises and learns at session end.

Select it with ``memory.provider: native``. Config lives under ``plugins.native-memory``:

- ``db_path``: default ``$HERMES_HOME/memory_native.db`` (``$HERMES_HOME`` is expanded per profile).
- ``learning``: run the extraction pass at session end (default true; it costs one auxiliary LLM call per
  session, capped by ``max_new_per_session``).
- ``task_learning``: also record task outcomes for the curator (default false until an eval shows a gain).
- ``recall_limit`` / ``recall_char_budget``: bounds for the per-turn recall block.
- ``max_new_per_session``: cap on conclusions written from one session.

Recall never calls a model. The block travels through ``prefetch()``, so the system prompt stays
byte-identical within a session.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Optional

from agent.memory_provider import (
    MemoryProvider,
    is_trivial_prompt,
    spawn_context_thread,
)
from hermes_cli.config import cfg_get

from .learn import MAX_NEW_PER_SESSION, TASK_KEY, learn_from_session
from .recall import DEFAULT_CHAR_BUDGET, DEFAULT_LIMIT, recall_block
from .store import NativeStore

logger = logging.getLogger(__name__)

_DEFAULT_DB = "$HERMES_HOME/memory_native.db"
_SHUTDOWN_JOIN_S = 60.0


def _load_plugin_config() -> dict:
    try:
        from hermes_cli.config import (
            load_config_readonly,
        )  # canonical: managed-scope overlay + ${VAR} expansion

        return (
            cfg_get(load_config_readonly(), "plugins", "native-memory", default={})
            or {}
        )
    except Exception:
        logger.warning("native memory: config unreadable, using defaults", exc_info=True)
        return {}


def _response_text(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError):
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    texts = (
        part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
        for part in content
    )
    return "".join(t for t in texts if isinstance(t, str))


def _auxiliary_extractor(messages: list[dict[str, str]]) -> str:
    """Production extractor: one auxiliary-model call under ``auxiliary.memory_learning``."""
    from agent.auxiliary_client import call_llm

    response = call_llm(
        task=TASK_KEY, messages=messages, temperature=0, max_tokens=1500
    )
    return _response_text(response)


class NativeMemoryProvider(MemoryProvider):
    def __init__(self, config: Optional[dict] = None) -> None:
        self._config = dict(config or {})
        self._store: Optional[NativeStore] = None
        self._session_id = ""
        self._learn_thread: Optional[threading.Thread] = None
        self._extractor = _auxiliary_extractor

    @property
    def name(self) -> str:
        return "native"

    def is_available(self) -> bool:
        return True  # local SQLite, no network and no credentials

    def initialize(self, session_id: str, **kwargs) -> None:
        from hermes_constants import get_hermes_home

        home = str(get_hermes_home())
        db_path = (
            str(self._config.get("db_path", _DEFAULT_DB))
            .replace("${HERMES_HOME}", home)
            .replace("$HERMES_HOME", home)
        )
        self._store = NativeStore(Path(db_path))
        self._session_id = session_id

    def system_prompt_block(self) -> str:
        return ""  # recall travels through prefetch(), never the system prompt

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if self._store is None or is_trivial_prompt(query):
            return ""
        block, _ids = recall_block(
            self._store,
            query,
            limit=int(self._config.get("recall_limit", DEFAULT_LIMIT)),
            char_budget=int(
                self._config.get("recall_char_budget", DEFAULT_CHAR_BUDGET)
            ),
        )
        return block

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        **kwargs,
    ) -> None:
        return None  # learning happens at session end, not per turn

    def on_session_end(self, messages: list[dict[str, Any]]) -> None:
        if self._store is None or not self._config.get("learning", True):
            return
        session_id = self._session_id
        messages = list(messages)
        self._learn_thread = spawn_context_thread(
            target=self._learn, args=(session_id, messages), name="native-memory-learn"
        )
        self._learn_thread.start()

    def _learn(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        try:
            stats = learn_from_session(
                self._store,
                messages,
                session_id=session_id,
                call=self._extractor,
                task_learning=bool(self._config.get("task_learning", False)),
                max_new=int(
                    self._config.get("max_new_per_session", MAX_NEW_PER_SESSION)
                ),
            )
            logger.debug("native memory learning for %s: %s", session_id, stats)
        except Exception:
            logger.exception("native memory learning failed for %s", session_id)

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return []  # recall and learning are automatic; the model gets no extra tools

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs) -> str:
        return json.dumps({"error": f"native memory has no tool named {tool_name!r}"})

    def shutdown(self) -> None:
        thread = self._learn_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=_SHUTDOWN_JOIN_S)
        if self._store is not None:
            self._store.close()
            self._store = None


def register(ctx) -> None:
    """Register the native learning memory provider with the plugin system."""
    ctx.register_memory_provider(NativeMemoryProvider(config=_load_plugin_config()))
