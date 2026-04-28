"""
tests/test_engine.py — Tests for the debate engine orchestration.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.

The engine is exercised against a fake :class:`LLMClient` so the tests
require neither a network nor a running Ollama server.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from auto_debate.config import Settings
from auto_debate.engine import DebateEngine, DebateTurn

# --- helpers ----------------------------------------------------------------


def _settings(max_turns: int = 2, word_limit: int = 60) -> Settings:
    return Settings(
        ollama_host="http://localhost:11434",
        model_name="gemma3:4b",
        max_turns=max_turns,
        temperature=0.8,
        top_p=0.95,
        word_limit=word_limit,
    )


class _ScriptedClient:
    """Fake LLM client that yields a pre-set list of token lists per call."""

    def __init__(self, scripted_turns: list[list[str]]) -> None:
        self._turns = list(scripted_turns)
        self.calls: list[list[dict[str, Any]]] = []
        self.options_seen: list[dict[str, Any] | None] = []

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> Iterator[str]:
        self.calls.append([dict(m) for m in messages])
        self.options_seen.append(options)
        if not self._turns:
            return iter(())
        tokens = self._turns.pop(0)
        return iter(tokens)


# --- DebateTurn -------------------------------------------------------------


def test_debate_turn_is_frozen() -> None:
    t = DebateTurn(speaker="offender", content="hi", index=1)
    with pytest.raises(AttributeError):  # FrozenInstanceError
        t.content = "nope"  # type: ignore[misc]


# --- construction -----------------------------------------------------------


def test_construction_seeds_only_system_messages() -> None:
    eng = DebateEngine(_settings(), _ScriptedClient([]), "AI is dangerous")
    assert len(eng.offender_messages) == 1
    assert len(eng.defender_messages) == 1
    assert eng.offender_messages[0]["role"] == "system"
    assert eng.defender_messages[0]["role"] == "system"
    assert "OFFENDER" in eng.offender_messages[0]["content"]
    assert "DEFENDER" in eng.defender_messages[0]["content"]
    assert "AI is dangerous" in eng.offender_messages[0]["content"]


def test_construction_rejects_empty_topic() -> None:
    with pytest.raises(ValueError):
        DebateEngine(_settings(), _ScriptedClient([]), "   ")


# --- run_one_turn -----------------------------------------------------------


def test_first_offender_turn_yields_tokens_and_commits_history() -> None:
    client = _ScriptedClient([["AI ", "is ", "risky."]])
    eng = DebateEngine(_settings(), client, "AI is dangerous")

    out = list(eng.run_one_turn("offender"))

    assert out == ["AI ", "is ", "risky."]
    # After 1 turn: offender = system + assistant; defender = system + user-mirror.
    assert len(eng.offender_messages) == 2
    assert len(eng.defender_messages) == 2
    assert eng.offender_messages[-1] == {"role": "assistant", "content": "AI is risky."}
    assert eng.defender_messages[-1] == {"role": "user", "content": "AI is risky."}
    # Transcript captured.
    assert eng.transcript() == [
        DebateTurn(speaker="offender", content="AI is risky.", index=1),
    ]


def test_first_offender_request_includes_opening_message() -> None:
    client = _ScriptedClient([["x"]])
    eng = DebateEngine(_settings(), client, "AI is dangerous")
    list(eng.run_one_turn("offender"))

    sent = client.calls[0]
    # system + injected user(OPENING)
    assert len(sent) == 2
    assert sent[0]["role"] == "system"
    assert sent[1]["role"] == "user"
    assert "Open the debate" in sent[1]["content"]


def test_request_passes_chat_options() -> None:
    client = _ScriptedClient([["x"]])
    eng = DebateEngine(_settings(word_limit=120), client, "topic")
    list(eng.run_one_turn("offender"))

    opts = client.options_seen[0]
    assert opts is not None
    assert "temperature" in opts and "top_p" in opts and "num_predict" in opts


def test_invalid_speaker_raises() -> None:
    eng = DebateEngine(_settings(), _ScriptedClient([]), "topic")
    gen = eng.run_one_turn("narrator")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        next(gen)


def test_stop_check_halts_within_one_token() -> None:
    client = _ScriptedClient([["a", "b", "c", "d"]])
    eng = DebateEngine(_settings(), client, "topic")

    out = list(eng.run_one_turn("offender", stop_check=lambda: True))

    # First stop_check fires before any token is yielded.
    assert out == []
    # Aborted turn must not be committed.
    assert eng.transcript() == []
    assert len(eng.offender_messages) == 1
    assert len(eng.defender_messages) == 1


def test_stop_check_after_one_token() -> None:
    client = _ScriptedClient([["a", "b", "c", "d"]])
    eng = DebateEngine(_settings(), client, "topic")
    counter = {"n": 0}

    def stop() -> bool:
        counter["n"] += 1
        return counter["n"] > 1  # allow first token, stop before second

    out = list(eng.run_one_turn("offender", stop_check=stop))
    assert out == ["a"]
    assert eng.transcript() == []  # partial turn never commits


# --- mirroring + alternation -----------------------------------------------


def test_two_turns_mirror_correctly() -> None:
    client = _ScriptedClient([["off1"], ["def1"]])
    eng = DebateEngine(_settings(), client, "topic")

    list(eng.run_one_turn("offender"))
    list(eng.run_one_turn("defender"))

    # Offender history: system + assistant(off1) + user(def1)
    assert [m["role"] for m in eng.offender_messages] == [
        "system",
        "assistant",
        "user",
    ]
    assert eng.offender_messages[-1]["content"] == "def1"

    # Defender history: system + user(off1) + assistant(def1)
    assert [m["role"] for m in eng.defender_messages] == [
        "system",
        "user",
        "assistant",
    ]
    assert eng.defender_messages[1]["content"] == "off1"
    assert eng.defender_messages[-1]["content"] == "def1"


def test_run_alternates_speakers_and_respects_max_turns() -> None:
    # max_turns=2 → 4 total turns: off, def, off, def.
    client = _ScriptedClient([["o1"], ["d1"], ["o2"], ["d2"]])
    eng = DebateEngine(_settings(max_turns=2), client, "topic")

    out = list(eng.run())
    speakers = [s for s, _ in out]
    contents = [c for _, c in out]

    assert speakers == ["offender", "defender", "offender", "defender"]
    assert contents == ["o1", "d1", "o2", "d2"]
    assert [t.speaker for t in eng.transcript()] == [
        "offender",
        "defender",
        "offender",
        "defender",
    ]
    assert [t.index for t in eng.transcript()] == [1, 2, 3, 4]


def test_run_honors_stop_check_between_turns() -> None:
    client = _ScriptedClient([["o1"], ["d1"], ["o2"], ["d2"]])
    eng = DebateEngine(_settings(max_turns=2), client, "topic")

    seen: list[str] = []

    def stop() -> bool:
        return len(seen) >= 1  # stop after the first token

    for _speaker, tok in eng.run(stop_check=stop):
        seen.append(tok)

    # The first token "o1" is yielded, then stop fires before any more.
    assert seen == ["o1"]
    # The offender's single-token turn completed cleanly and was committed;
    # run() then sees stop_check=True and aborts before the defender starts.
    assert [t.speaker for t in eng.transcript()] == ["offender"]
    assert eng.transcript()[0].content == "o1"


# --- transcript / markdown --------------------------------------------------


def test_to_markdown_lists_each_turn() -> None:
    client = _ScriptedClient([["o1 text"], ["d1 text"]])
    eng = DebateEngine(_settings(), client, "AI is dangerous")
    list(eng.run_one_turn("offender"))
    list(eng.run_one_turn("defender"))

    md = eng.to_markdown()
    assert md.startswith("# Debate: AI is dangerous")
    assert "Turn 1 — Offender" in md
    assert "Turn 2 — Defender" in md
    assert "o1 text" in md
    assert "d1 text" in md


# --- Phase 22: per-turn timing --------------------------------------------


def test_run_one_turn_records_wall_clock_seconds() -> None:
    eng = DebateEngine(_settings(), _ScriptedClient([["hi", " there"]]), "topic A")
    assert eng.last_turn_seconds() is None
    list(eng.run_one_turn("offender"))
    seconds = eng.last_turn_seconds()
    assert seconds is not None
    assert seconds >= 0.0
    assert eng.turn_seconds() == [seconds]


def test_run_one_turn_does_not_record_when_aborted() -> None:
    eng = DebateEngine(_settings(), _ScriptedClient([["x", "y"]]), "topic")
    list(eng.run_one_turn("offender", stop_check=lambda: True))
    assert eng.last_turn_seconds() is None
    assert eng.turn_seconds() == []


def test_turn_seconds_accumulates_per_turn() -> None:
    eng = DebateEngine(_settings(), _ScriptedClient([["a"], ["b"]]), "topic")
    list(eng.run_one_turn("offender"))
    list(eng.run_one_turn("defender"))
    assert len(eng.turn_seconds()) == 2
