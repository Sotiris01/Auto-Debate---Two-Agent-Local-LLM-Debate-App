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

    _offender_msgs: list[dict[str, Any]] = field(init=False)
    _defender_msgs: list[dict[str, Any]] = field(init=False)
    _turns: list[DebateTurn] = field(init=False, default_factory=list)
    _offender_has_spoken: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        composer = PromptComposer(word_limit=self.settings.word_limit)
        offender_system = composer.compose(
            role=OFFENDER_ROLE,
            topic=self.topic,
            persona=self.persona,
            behavior=self.behavior,
        )
        defender_system = composer.compose(
            role=DEFENDER_ROLE,
            topic=self.topic,
            persona=self.persona,
            behavior=self.behavior,
        )
        self._offender_msgs = [{"role": "system", "content": offender_system}]
        self._defender_msgs = [{"role": "system", "content": defender_system}]

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
