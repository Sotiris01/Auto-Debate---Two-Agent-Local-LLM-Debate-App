"""
reflection.py — Pre-turn memory reflection (Phase 12).

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.

Before each speaking turn, the agent runs a *silent* reflection LLM call
that reads the opponent's most recent answer and produces a tiny diff
against its own memory document:

    <UPDATE>
    add_observations: ["..."]
    add_strategy: ["..."]
    drop_observations: [0, 2]
    drop_strategy: []
    </UPDATE>

The diff is parsed, validated, applied to the in-memory
:class:`memory.AgentMemory`, persisted, and only *then* does the speaking
turn run with the freshly updated ``<MEMORY>`` block. Reflection
failures (malformed JSON, LLM error, no ``<UPDATE>`` block) degrade
gracefully: the speaking turn proceeds with the unchanged memory and a
warning is logged.

The reflection prompt deliberately does **not** see the conversation
history — it only sees the role, the current memory, and the opponent's
last turn. This forces the model to focus on the diff task and keeps the
reflection call cheap (low ``num_predict`` cap).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from memory import AgentId, AgentMemory, render_prompt_block

__all__ = [
    "REFLECTOR_SYSTEM_PROMPT",
    "MemoryUpdate",
    "Reflector",
    "apply_update",
    "build_reflection_messages",
    "parse_update_block",
]

_log = logging.getLogger(__name__)

# Hard caps so a runaway reflection call cannot flood the memory.
_MAX_ADDITIONS_PER_SECTION: Final[int] = 5
_MAX_ITEM_CHARS: Final[int] = 240
# Stage A is meant to be cheap. The speaking turn keeps its full budget.
_REFLECTION_NUM_PREDICT: Final[int] = 220


REFLECTOR_SYSTEM_PROMPT: Final[str] = (
    "You are the SILENT memory keeper for a debate agent. You do NOT speak in "
    "the debate. Your only job is to read the opponent's latest answer and "
    "produce a tiny diff against the agent's memory.\n"
    "\n"
    "Output STRICTLY one block, nothing else, exactly in this format:\n"
    "<UPDATE>\n"
    'add_observations: ["short note", "..."]\n'
    'add_strategy: ["short tactic", "..."]\n'
    "drop_observations: [<index>, ...]\n"
    "drop_strategy: [<index>, ...]\n"
    "</UPDATE>\n"
    "\n"
    "Rules:\n"
    "- Each list value MUST be valid JSON.\n"
    "- Keep each note <= 30 words. Avoid duplicating existing entries.\n"
    "- Drop indices refer to the CURRENT memory (0-based). Out-of-range "
    "indices are ignored.\n"
    "- Add at most 3 new observations and 3 new strategy items per turn.\n"
    "- If there is nothing to update, emit empty arrays. Never write prose "
    "outside the <UPDATE> block."
)


# --- update schema ---------------------------------------------------------


@dataclass(frozen=True)
class MemoryUpdate:
    """A diff against an :class:`AgentMemory`.

    All four fields are normalised to tuples so the dataclass can stay
    frozen. Indices are 0-based and refer to the *current* memory at the
    time the update was generated.
    """

    add_observations: tuple[str, ...] = ()
    add_strategy: tuple[str, ...] = ()
    drop_observations: tuple[int, ...] = ()
    drop_strategy: tuple[int, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (
            self.add_observations
            or self.add_strategy
            or self.drop_observations
            or self.drop_strategy
        )


# --- parser ----------------------------------------------------------------


_UPDATE_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"<UPDATE>\s*(?P<body>.*?)\s*</UPDATE>",
    re.IGNORECASE | re.DOTALL,
)
# Matches ``key: <json-value>`` on a single logical line. We capture the
# value greedily until a newline+next-key boundary so that JSON arrays
# spanning multiple lines still parse if the model decides to pretty-print.
_FIELD_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(add_observations|add_strategy|drop_observations|drop_strategy)\s*:"
    r"\s*(?P<value>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _coerce_string_list(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if not cleaned:
            continue
        if len(cleaned) > _MAX_ITEM_CHARS:
            cleaned = cleaned[:_MAX_ITEM_CHARS].rstrip()
        out.append(cleaned)
    return tuple(out)


def _coerce_int_list(raw: Any) -> tuple[int, ...]:
    if not isinstance(raw, list):
        return ()
    out: list[int] = []
    for item in raw:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            if item >= 0:
                out.append(item)
        elif isinstance(item, str):
            try:
                value = int(item.strip())
            except ValueError:
                continue
            if value >= 0:
                out.append(value)
    return tuple(out)


def parse_update_block(text: str) -> MemoryUpdate | None:
    """Parse an ``<UPDATE>...</UPDATE>`` block.

    Returns ``None`` when no block is found at all, when the block body
    does not contain at least one recognised field, or when every field
    value fails to JSON-decode. Otherwise returns a :class:`MemoryUpdate`
    where each missing/malformed field is silently treated as empty.
    """
    if not isinstance(text, str) or not text:
        return None
    match = _UPDATE_BLOCK_RE.search(text)
    if match is None:
        return None
    body = match.group("body")
    fields: dict[str, Any] = {}
    for field_match in _FIELD_RE.finditer(body):
        key = field_match.group(1).lower()
        raw_value = field_match.group("value").strip()
        try:
            decoded = json.loads(raw_value)
        except json.JSONDecodeError:
            continue
        fields[key] = decoded

    if not fields:
        return None

    return MemoryUpdate(
        add_observations=_coerce_string_list(fields.get("add_observations"))[
            :_MAX_ADDITIONS_PER_SECTION
        ],
        add_strategy=_coerce_string_list(fields.get("add_strategy"))[:_MAX_ADDITIONS_PER_SECTION],
        drop_observations=_coerce_int_list(fields.get("drop_observations")),
        drop_strategy=_coerce_int_list(fields.get("drop_strategy")),
    )


# --- mutator ---------------------------------------------------------------


def _drop_indices(items: tuple[str, ...], drops: tuple[int, ...]) -> tuple[str, ...]:
    if not drops:
        return items
    valid = {idx for idx in drops if 0 <= idx < len(items)}
    if not valid:
        return items
    return tuple(value for idx, value in enumerate(items) if idx not in valid)


def _append_dedup(
    base: tuple[str, ...],
    additions: tuple[str, ...],
    *,
    cap: int,
) -> tuple[str, ...]:
    if not additions:
        return base
    seen = set(base)
    out = list(base)
    added = 0
    for item in additions:
        if added >= cap:
            break
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
        added += 1
    return tuple(out)


def apply_update(memory: AgentMemory, update: MemoryUpdate) -> AgentMemory:
    """Apply ``update`` to ``memory`` and return a new :class:`AgentMemory`.

    The update is applied in two phases:

        1. Drop indices first (so the model can re-add a tweaked version
           of an entry it just dropped without colliding with itself).
        2. Then append new entries, deduplicated against whatever
           survives the drop step. At most
           :data:`_MAX_ADDITIONS_PER_SECTION` new items per section.

    The ``knowledge`` section is intentionally untouched — it is
    populated by Phase 11 research and is read-only for the reflector.
    ``turn_index`` is preserved; the engine stamps it separately via
    :meth:`AgentMemory.with_turn_index`.
    """
    obs = _drop_indices(memory.observations, update.drop_observations)
    obs = _append_dedup(obs, update.add_observations, cap=_MAX_ADDITIONS_PER_SECTION)
    strat = _drop_indices(memory.strategy, update.drop_strategy)
    strat = _append_dedup(strat, update.add_strategy, cap=_MAX_ADDITIONS_PER_SECTION)
    return AgentMemory(
        agent_id=memory.agent_id,
        knowledge=memory.knowledge,
        observations=obs,
        strategy=strat,
        turn_index=memory.turn_index,
    )


# --- LLM-driven reflection -------------------------------------------------


class _LLMClient(Protocol):
    """Minimal subset of :class:`engine.LLMClient` the reflector needs."""

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = ...,
        model: str | None = ...,
    ) -> Iterator[str]: ...


def _format_memory_for_reflection(memory: AgentMemory) -> str:
    block = render_prompt_block(memory)
    return block or "(memory is currently empty)"


def build_reflection_messages(
    *,
    agent_id: AgentId,
    memory: AgentMemory,
    opponent_text: str,
    topic: str,
) -> list[dict[str, Any]]:
    """Build the ``messages`` list for a reflection LLM call.

    The reflector deliberately does **not** receive the full conversation
    history — only the topic, the role stance, the current memory, and
    the opponent's most recent answer. This keeps the call small and
    focused on the diff task.
    """
    role_label = "AGAINST" if agent_id == "offender" else "FOR"
    user = (
        f'Debate topic: "{topic}"\n'
        f"Your role: argue {role_label} the topic.\n"
        "\n"
        f"Your current memory:\n{_format_memory_for_reflection(memory)}\n"
        "\n"
        "Opponent's most recent answer:\n"
        f"{opponent_text.strip() or '(no opponent answer yet)'}\n"
        "\n"
        "Reply with the <UPDATE> block."
    )
    return [
        {"role": "system", "content": REFLECTOR_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


@dataclass
class Reflector:
    """Drives the silent reflection LLM call before each speaking turn."""

    llm_client: _LLMClient
    topic: str
    model: str | None = None
    options: dict[str, Any] = field(
        default_factory=lambda: {
            "temperature": 0.2,
            "top_p": 0.9,
            "num_predict": _REFLECTION_NUM_PREDICT,
        },
    )

    def reflect(
        self,
        *,
        agent_id: AgentId,
        memory: AgentMemory,
        opponent_text: str,
    ) -> MemoryUpdate | None:
        """Run one reflection pass.

        Returns ``None`` if the LLM call fails or the response cannot be
        parsed. Callers should treat ``None`` as "leave memory
        unchanged" — never as a fatal error.
        """
        messages = build_reflection_messages(
            agent_id=agent_id,
            memory=memory,
            opponent_text=opponent_text,
            topic=self.topic,
        )
        try:
            chunks: list[str] = list(
                self.llm_client.stream_chat(
                    messages,
                    options=self.options,
                    model=self.model,
                ),
            )
        except Exception:
            _log.exception("reflection LLM call failed for agent=%s", agent_id)
            return None
        raw = "".join(chunks)
        update = parse_update_block(raw)
        if update is None:
            _log.warning(
                "reflection produced no valid <UPDATE> block for agent=%s; "
                "leaving memory unchanged",
                agent_id,
            )
            return None
        return update
