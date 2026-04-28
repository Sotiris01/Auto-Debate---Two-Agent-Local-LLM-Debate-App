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
from typing import TYPE_CHECKING, Any, Protocol

from config import Settings
from memory import AgentId, AgentMemory, MemoryStore, MemoryStoreError
from prompts import (
    CLOSING_BEHAVIOR,
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
from reflection import MemoryUpdate, Reflector, apply_update

if TYPE_CHECKING:  # pragma: no cover — type-only import
    from quality import TurnMetrics

__all__ = [
    "DebateEngine",
    "DebateTurn",
    "LLMClient",
    "ReflectionDiff",
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


@dataclass(frozen=True)
class ReflectionDiff:
    """Summary of the most recent reflection pass for one agent (UI surface).

    ``turn_index`` is the global 1-based index of the speaking turn that
    this reflection ran *before*. ``observations_added`` etc. are the
    counts after validation/dedup, so the UI never claims credit for
    entries that were silently dropped by :func:`reflection.apply_update`.
    """

    speaker: Role
    turn_index: int
    observations_added: int
    strategy_added: int
    observations_dropped: int
    strategy_dropped: int

    @property
    def is_empty(self) -> bool:
        return not (
            self.observations_added
            or self.strategy_added
            or self.observations_dropped
            or self.strategy_dropped
        )

    def summary(self) -> str:
        """Short human-readable diff (e.g. ``+2 obs · +1 strat · -1 obs``)."""
        parts: list[str] = []
        if self.observations_added:
            parts.append(f"+{self.observations_added} obs")
        if self.strategy_added:
            parts.append(f"+{self.strategy_added} strat")
        if self.observations_dropped:
            parts.append(f"-{self.observations_dropped} obs")
        if self.strategy_dropped:
            parts.append(f"-{self.strategy_dropped} strat")
        return " · ".join(parts) if parts else "no changes"


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
    defender_persona: PersonaFragment | None = None
    defender_behavior: BehaviorFragment | None = None
    memory_store: MemoryStore | None = None
    run_id: str | None = None
    reflector: Reflector | None = None
    closing_behavior: BehaviorFragment = CLOSING_BEHAVIOR

    _offender_msgs: list[dict[str, Any]] = field(init=False)
    _defender_msgs: list[dict[str, Any]] = field(init=False)
    _turns: list[DebateTurn] = field(init=False, default_factory=list)
    _offender_has_spoken: bool = field(init=False, default=False)
    _composer: PromptComposer = field(init=False)
    _memories: dict[AgentId, AgentMemory] = field(init=False, default_factory=dict)
    _last_reflection: dict[AgentId, ReflectionDiff] = field(
        init=False,
        default_factory=dict,
    )

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

    def _persona_for(self, agent_id: AgentId) -> PersonaFragment:
        if agent_id == "defender" and self.defender_persona is not None:
            return self.defender_persona
        return self.persona

    def _behavior_for(self, agent_id: AgentId) -> BehaviorFragment:
        if agent_id == "defender" and self.defender_behavior is not None:
            return self.defender_behavior
        return self.behavior

    def _build_system_prompt(
        self,
        role: RoleFragment,
        agent_id: AgentId,
        *,
        behavior: BehaviorFragment | None = None,
    ) -> str:
        return self._composer.compose(
            role=role,
            topic=self.topic,
            persona=self._persona_for(agent_id),
            behavior=behavior if behavior is not None else self._behavior_for(agent_id),
            memory=self._memory_block_for(agent_id),
        )

    def memory_for(self, agent_id: AgentId) -> AgentMemory | None:
        """Return the live memory for ``agent_id`` (UI surface)."""
        return self._memories.get(agent_id)

    def last_reflection_for(self, agent_id: AgentId) -> ReflectionDiff | None:
        """Return the most recent reflection diff for ``agent_id``, if any."""
        return self._last_reflection.get(agent_id)

    # --- closing-round + reflection ---------------------------------------

    def _agent_speech_count(self, speaker: Role) -> int:
        return sum(1 for t in self._turns if t.speaker == speaker)

    def _behavior_for_turn(self, speaker: Role) -> BehaviorFragment:
        """Pick the behaviour fragment for the upcoming turn by ``speaker``.

        Returns :attr:`closing_behavior` when the closing-round flag is on
        and the upcoming turn is the agent's final scheduled turn.
        """
        if (
            self.settings.closing_round_enabled
            and self._agent_speech_count(speaker) == self.settings.max_turns - 1
        ):
            return self.closing_behavior
        return self._behavior_for(speaker)

    def _opponent_last_text(self, speaker: Role) -> str | None:
        opponent = _opposite(speaker)
        for turn in reversed(self._turns):
            if turn.speaker == opponent:
                return turn.content
        return None

    def _refresh_system_prompt(self, speaker: Role, behavior: BehaviorFragment) -> None:
        role_fragment = OFFENDER_ROLE if speaker == "offender" else DEFENDER_ROLE
        history = self._history_for(speaker)
        new_system = self._build_system_prompt(
            role_fragment,
            speaker,
            behavior=behavior,
        )
        if history and history[0].get("role") == "system":
            history[0] = {"role": "system", "content": new_system}
        else:
            history.insert(0, {"role": "system", "content": new_system})

    def _run_reflection(self, speaker: Role) -> None:
        """Stage A: silent reflection that mutates the speaker's memory.

        Skipped when:
            * the reflector is not configured, OR
            * memory is not active (flag/store/run_id), OR
            * the opponent has not yet spoken (turn 1 of the debate).

        All failures are non-fatal: the speaking turn proceeds with the
        previous memory and a warning is logged.
        """
        if self.reflector is None or not self._memory_active:
            return
        opponent_text = self._opponent_last_text(speaker)
        if not opponent_text:
            return
        assert self.memory_store is not None and self.run_id is not None
        current = self._memories.get(speaker)
        if current is None:
            return
        upcoming_index = len(self._turns) + 1
        update: MemoryUpdate | None
        try:
            update = self.reflector.reflect(
                agent_id=speaker,
                memory=current,
                opponent_text=opponent_text,
            )
        except Exception:
            _log.exception("reflection raised for agent=%s; leaving memory unchanged", speaker)
            return
        if update is None or update.is_empty:
            self._last_reflection[speaker] = ReflectionDiff(
                speaker=speaker,
                turn_index=upcoming_index,
                observations_added=0,
                strategy_added=0,
                observations_dropped=0,
                strategy_dropped=0,
            )
            return
        updated = apply_update(current, update)
        # Re-derive the actual counts so the UI never claims credit for
        # drops/additions that validation silently rejected.
        dropped_obs = sum(
            1 for i in set(update.drop_observations) if 0 <= i < len(current.observations)
        )
        dropped_strat = sum(1 for i in set(update.drop_strategy) if 0 <= i < len(current.strategy))
        added_obs = len(updated.observations) - (len(current.observations) - dropped_obs)
        added_strat = len(updated.strategy) - (len(current.strategy) - dropped_strat)
        self._memories[speaker] = updated
        try:
            self.memory_store.save(self.run_id, updated)
        except MemoryStoreError:
            _log.exception(
                "failed to persist reflected memory for agent=%s turn=%d",
                speaker,
                upcoming_index,
            )
        self._last_reflection[speaker] = ReflectionDiff(
            speaker=speaker,
            turn_index=upcoming_index,
            observations_added=added_obs,
            strategy_added=added_strat,
            observations_dropped=dropped_obs,
            strategy_dropped=dropped_strat,
        )

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

    def to_markdown(self, *, include_quality_metrics: bool = False) -> str:
        """Render the transcript as Markdown (consumed by the Phase 8 export).

        When ``include_quality_metrics`` is ``True`` (Phase 13), a per-turn
        novelty + adherence table is appended.
        """
        lines = [f"# Debate: {self.topic}", ""]
        for turn in self._turns:
            label = "Offender" if turn.speaker == "offender" else "Defender"
            lines.append(f"### Turn {turn.index} — {label}")
            lines.append("")
            lines.append(turn.content.strip())
            lines.append("")
        body = "\n".join(lines).rstrip() + "\n"
        if include_quality_metrics and self._turns:
            from quality import render_metrics_table

            metrics = self.compute_quality_metrics()
            table = render_metrics_table(metrics)
            if table:
                body = body + "\n" + table
        return body

    def compute_quality_metrics(self) -> list[TurnMetrics]:
        """Return :class:`quality.TurnMetrics` for every committed turn.

        Defined here (rather than on every UI surface) so the same numbers
        appear in the live chips, the loop-hint banner, and the markdown
        export. Imports lazily so ``engine`` doesn't pay for ``quality``
        at module-load time when callers don't need metrics.
        """
        from quality import compute_turn_metrics

        contents = [t.content for t in self._turns]
        return [
            compute_turn_metrics(
                turn_index=t.index,
                turn_text=t.content,
                prev_turn_texts=contents[:i],
                topic=self.topic,
                role_hint=t.speaker,
            )
            for i, t in enumerate(self._turns)
        ]

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

        # Stage A (silent): reflection updates the speaker's memory before
        # we build the request. Skipped on turn 1 (no opponent text yet)
        # and whenever the reflector is not configured.
        self._run_reflection(speaker)

        # Refresh the system prompt so any memory mutation from Stage A
        # and the closing-round behavior swap take effect for Stage B.
        behavior = self._behavior_for_turn(speaker)
        self._refresh_system_prompt(speaker, behavior)

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
