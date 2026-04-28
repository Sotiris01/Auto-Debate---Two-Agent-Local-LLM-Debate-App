"""
engine.py — Pure debate orchestration. Knows nothing about Streamlit.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.

Phase 5: takes a :class:`Settings`, an LLM client (anything with a
``stream_chat(messages, *, options)`` iterator) and a topic, and produces
a stream of ``(speaker, token)`` pairs. The engine owns the two role
histories and the alternating-role mirroring trick that lets two assistant
agents debate through a single chat-model interface.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from config import Settings
from memory import AgentId, AgentMemory, MemoryStore, MemoryStoreError
from prompts import (
    DEFENDER_ROLE,
    NEUTRAL_PERSONA,
    OFFENDER_ROLE,
    OPENING_USER_MESSAGE,
    STANDARD_BEHAVIOR,
    BehaviorFragment,
    PersonaFragment,
    PromptComposer,
    Role,
    RoleFragment,
)

__all__ = [
    "DebateEngine",
    "DebateTurn",
    "LLMClient",
]

_log = logging.getLogger(__name__)


# --- types ------------------------------------------------------------------


class LLMClient(Protocol):
    """Structural type for the LLM transport the engine depends on.

    Matches :class:`llm.OllamaClient` but lets tests pass a plain fake.
    """

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = ...,
        model: str | None = ...,
    ) -> Iterator[str]: ...


@dataclass(frozen=True)
class DebateTurn:
    """A single committed turn in the debate transcript."""

    speaker: Role
    content: str
    index: int  # 1-based, monotonic across the whole debate


# --- engine -----------------------------------------------------------------


def _opposite(speaker: Role) -> Role:
    return "defender" if speaker == "offender" else "offender"


@dataclass
class DebateEngine:
    """Drives a two-agent debate over a single topic.

    Construction validates the topic via :func:`prompts.build_system_prompt`
    and seeds two parallel chat histories — one from each agent's point of
    view. The OPENING user message is *not* persisted into either history;
    it is injected only when the offender takes its very first turn so the
    persisted state stays a clean assistant/user alternation usable by any
    chat model.
    """

    settings: Settings
    llm_client: LLMClient
    topic: str
    persona: PersonaFragment = NEUTRAL_PERSONA
    behavior: BehaviorFragment = STANDARD_BEHAVIOR
    memory_store: MemoryStore | None = None
    run_id: str | None = None

    _offender_msgs: list[dict[str, Any]] = field(init=False)
    _defender_msgs: list[dict[str, Any]] = field(init=False)
    _turns: list[DebateTurn] = field(init=False, default_factory=list)
    _offender_has_spoken: bool = field(init=False, default=False)
    _composer: PromptComposer = field(init=False)
    _memories: dict[AgentId, AgentMemory] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self._composer = PromptComposer(word_limit=self.settings.word_limit)
        if self._memory_active:
            assert self.memory_store is not None and self.run_id is not None
            self._memories = {
                "offender": self.memory_store.load(self.run_id, "offender"),
                "defender": self.memory_store.load(self.run_id, "defender"),
            }
        offender_system = self._build_system_prompt(OFFENDER_ROLE, "offender")
        defender_system = self._build_system_prompt(DEFENDER_ROLE, "defender")
        self._offender_msgs = [{"role": "system", "content": offender_system}]
        self._defender_msgs = [{"role": "system", "content": defender_system}]

    # --- memory helpers ----------------------------------------------------

    @property
    def _memory_active(self) -> bool:
        """True when memory injection is fully wired (flag + store + run_id)."""
        return (
            self.settings.memory_enabled
            and self.memory_store is not None
            and self.run_id is not None
        )

    def _memory_block_for(self, agent_id: AgentId) -> str | None:
        if not self._memory_active:
            return None
        memory = self._memories.get(agent_id)
        if memory is None:
            return None
        assert self.memory_store is not None
        block = self.memory_store.to_prompt_block(memory)
        return block or None

    def _build_system_prompt(self, role: RoleFragment, agent_id: AgentId) -> str:
        return self._composer.compose(
            role=role,
            topic=self.topic,
            persona=self.persona,
            behavior=self.behavior,
            memory=self._memory_block_for(agent_id),
        )

    def memory_for(self, agent_id: AgentId) -> AgentMemory | None:
        """Return the live memory for ``agent_id`` (UI surface)."""
        return self._memories.get(agent_id)

    def _persist_memory(self, speaker: Role, turn_index: int) -> None:
        """Persist both agents' memories after a turn is committed.

        Phase 10 only stamps the new ``turn_index`` — the section
        contents are unchanged because no phase mutates them yet.
        Phase 12's reflection pass will replace this stub with a real
        update routine.
        """
        if not self._memory_active:
            return
        assert self.memory_store is not None and self.run_id is not None
        for agent_id, current in list(self._memories.items()):
            updated = current.with_turn_index(turn_index)
            self._memories[agent_id] = updated
            try:
                self.memory_store.save(self.run_id, updated)
            except MemoryStoreError:
                _log.exception(
                    "failed to persist memory for agent=%s turn=%d",
                    agent_id,
                    turn_index,
                )
        # Speaker is only used for logging context; no per-speaker logic yet.
        _log.debug("memory snapshot persisted after turn %d (%s)", turn_index, speaker)

    # --- inspection --------------------------------------------------------

    def transcript(self) -> list[DebateTurn]:
        """Return a copy of the committed transcript so far."""
        return list(self._turns)

    @property
    def offender_messages(self) -> list[dict[str, Any]]:
        return list(self._offender_msgs)

    @property
    def defender_messages(self) -> list[dict[str, Any]]:
        return list(self._defender_msgs)

    def to_markdown(self) -> str:
        """Render the transcript as Markdown (consumed by the Phase 8 export)."""
        lines = [f"# Debate: {self.topic}", ""]
        for turn in self._turns:
            label = "Offender" if turn.speaker == "offender" else "Defender"
            lines.append(f"### Turn {turn.index} — {label}")
            lines.append("")
            lines.append(turn.content.strip())
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    # --- turn execution ----------------------------------------------------

    def _history_for(self, speaker: Role) -> list[dict[str, Any]]:
        return self._offender_msgs if speaker == "offender" else self._defender_msgs

    def _build_request_messages(self, speaker: Role) -> list[dict[str, Any]]:
        history = self._history_for(speaker)
        # On the offender's first turn there is nothing to respond to yet —
        # inject the opening prompt only for that single request.
        if speaker == "offender" and not self._offender_has_spoken:
            return [*history, {"role": "user", "content": OPENING_USER_MESSAGE}]
        return list(history)

    def _commit_turn(self, speaker: Role, content: str) -> None:
        own = self._history_for(speaker)
        opp = self._history_for(_opposite(speaker))
        own.append({"role": "assistant", "content": content})
        opp.append({"role": "user", "content": content})
        if speaker == "offender":
            self._offender_has_spoken = True
        index = len(self._turns) + 1
        self._turns.append(
            DebateTurn(speaker=speaker, content=content, index=index),
        )
        self._persist_memory(speaker, index)
        _log.info(
            "committed turn %d: speaker=%s chars=%d words=%d",
            index,
            speaker,
            len(content),
            len(content.split()),
        )

    def run_one_turn(
        self,
        speaker: Role,
        *,
        stop_check: Callable[[], bool] | None = None,
    ) -> Iterator[str]:
        """Stream one turn from ``speaker``, yielding tokens as they arrive.

        After the stream ends the turn is committed: the assistant message is
        appended to the speaker's own history and mirrored as a user message
        into the opponent's history (the alternating-role trick).

        If ``stop_check`` is provided it is consulted before yielding each
        token; the first ``True`` aborts the turn cleanly without committing
        the partial text.
        """
        if speaker not in ("offender", "defender"):
            raise ValueError(f"speaker must be 'offender' or 'defender', got {speaker!r}")

        request = self._build_request_messages(speaker)
        from llm import chat_options  # local import to keep engine import-light

        options = chat_options(self.settings)

        buf: list[str] = []
        aborted = False
        for token in self.llm_client.stream_chat(request, options=options):
            if stop_check is not None and stop_check():
                aborted = True
                break
            buf.append(token)
            yield token

        if not aborted and buf:
            self._commit_turn(speaker, "".join(buf))

    # --- top-level loop ----------------------------------------------------

    def run(
        self,
        stop_check: Callable[[], bool] | None = None,
    ) -> Iterator[tuple[Role, str]]:
        """Run the full debate, yielding ``(speaker, token)`` pairs.

        Alternates offender, defender, offender, … for ``max_turns * 2``
        total turns. Honors ``stop_check`` between every emitted token.
        """
        total_turns = self.settings.max_turns * 2
        speaker: Role = "offender"
        for _ in range(total_turns):
            if stop_check is not None and stop_check():
                return
            for token in self.run_one_turn(speaker, stop_check=stop_check):
                yield speaker, token
            if stop_check is not None and stop_check():
                return
            speaker = _opposite(speaker)
