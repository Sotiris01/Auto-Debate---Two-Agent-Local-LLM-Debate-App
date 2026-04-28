"""Tests for the Phase 12 pre-turn reflection module."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from config import Settings
from engine import DebateEngine
from memory import AgentMemory, MemoryStore
from reflection import (
    MemoryUpdate,
    Reflector,
    apply_update,
    build_reflection_messages,
    parse_update_block,
)

# --- helpers ----------------------------------------------------------------


class _ScriptedClient:
    """Yields canned token sequences in order. Captures the system prompt."""

    def __init__(self, scripts: list[list[str]]) -> None:
        self._scripts = list(scripts)
        self.calls: list[list[dict[str, Any]]] = []

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> Iterator[str]:
        self.calls.append([dict(m) for m in messages])
        if not self._scripts:
            raise AssertionError("ScriptedClient ran out of scripts")
        yield from self._scripts.pop(0)


def _settings(**overrides: Any) -> Settings:
    base = Settings(
        ollama_host="http://localhost:11434",
        model_name="gemma3:4b",
        max_turns=2,
        temperature=0.7,
        top_p=0.9,
        word_limit=120,
    )
    if overrides:
        from dataclasses import replace as dc_replace

        base = dc_replace(base, **overrides)
    return base


# --- 12.1 parser ------------------------------------------------------------


def test_parse_update_block_happy_path() -> None:
    raw = (
        "<UPDATE>\n"
        'add_observations: ["Opp leans on cost.", "Repeats safety claim."]\n'
        'add_strategy: ["Pivot to externalities."]\n'
        "drop_observations: [0]\n"
        "drop_strategy: []\n"
        "</UPDATE>"
    )
    update = parse_update_block(raw)
    assert update is not None
    assert update.add_observations == ("Opp leans on cost.", "Repeats safety claim.")
    assert update.add_strategy == ("Pivot to externalities.",)
    assert update.drop_observations == (0,)
    assert update.drop_strategy == ()


def test_parse_update_block_tolerates_surrounding_noise() -> None:
    raw = (
        "Here is my analysis (will be ignored):\n"
        "<UPDATE>\n"
        'add_observations: ["X"]\n'
        "add_strategy: []\n"
        "drop_observations: []\n"
        "drop_strategy: []\n"
        "</UPDATE>\n"
        "trailing prose"
    )
    update = parse_update_block(raw)
    assert update is not None
    assert update.add_observations == ("X",)


def test_parse_update_block_missing_block_returns_none() -> None:
    assert parse_update_block("just prose, no update block here") is None


def test_parse_update_block_handles_partial_fields() -> None:
    raw = '<UPDATE>\nadd_observations: ["A", "B"]\n</UPDATE>'
    update = parse_update_block(raw)
    assert update is not None
    assert update.add_observations == ("A", "B")
    assert update.add_strategy == ()
    assert update.drop_observations == ()


def test_parse_update_block_drops_malformed_indices() -> None:
    raw = (
        "<UPDATE>\n"
        "add_observations: []\n"
        "add_strategy: []\n"
        'drop_observations: [0, "1", "x", -3, true]\n'
        "drop_strategy: []\n"
        "</UPDATE>"
    )
    update = parse_update_block(raw)
    assert update is not None
    # 0 (int), "1" (string-int) survive; "x", -3, true rejected.
    assert update.drop_observations == (0, 1)


def test_parse_update_block_caps_additions() -> None:
    items = [f"o{i}" for i in range(20)]
    body = (
        "<UPDATE>\n"
        f"add_observations: {items!r}\n"
        "add_strategy: []\n"
        "drop_observations: []\n"
        "drop_strategy: []\n"
        "</UPDATE>"
    ).replace("'", '"')
    update = parse_update_block(body)
    assert update is not None
    assert len(update.add_observations) == 5  # _MAX_ADDITIONS_PER_SECTION


# --- 12.2 apply_update ------------------------------------------------------


def _mk_memory(
    *,
    observations: tuple[str, ...] = (),
    strategy: tuple[str, ...] = (),
) -> AgentMemory:
    return AgentMemory(
        agent_id="offender",
        knowledge=("[supports] cited (source: https://e.com/x)",),
        observations=observations,
        strategy=strategy,
        turn_index=3,
    )


def test_apply_update_adds_and_drops() -> None:
    base = _mk_memory(observations=("o0", "o1", "o2"), strategy=("s0",))
    update = MemoryUpdate(
        add_observations=("o3",),
        add_strategy=("s1",),
        drop_observations=(1,),
        drop_strategy=(),
    )
    out = apply_update(base, update)
    assert out.observations == ("o0", "o2", "o3")
    assert out.strategy == ("s0", "s1")
    # Knowledge is read-only for the reflector.
    assert out.knowledge == base.knowledge
    assert out.turn_index == base.turn_index


def test_apply_update_dedupes_against_existing_entries() -> None:
    base = _mk_memory(observations=("o0", "o1"))
    update = MemoryUpdate(add_observations=("o0", "o2", "o2"))
    out = apply_update(base, update)
    # Duplicate "o0" suppressed; duplicate "o2" suppressed once present.
    assert out.observations == ("o0", "o1", "o2")


def test_apply_update_ignores_out_of_range_drops() -> None:
    base = _mk_memory(observations=("o0",))
    update = MemoryUpdate(drop_observations=(99, 5, 0))
    out = apply_update(base, update)
    assert out.observations == ()


def test_apply_update_caps_additions_at_five_per_section() -> None:
    base = _mk_memory()
    update = MemoryUpdate(
        add_observations=tuple(f"o{i}" for i in range(10)),
    )
    out = apply_update(base, update)
    assert len(out.observations) == 5


def test_apply_update_drop_then_add_same_index() -> None:
    """Drops are applied before adds, so a re-added entry doesn't clash."""
    base = _mk_memory(observations=("old",))
    update = MemoryUpdate(
        add_observations=("new",),
        drop_observations=(0,),
    )
    out = apply_update(base, update)
    assert out.observations == ("new",)


# --- 12.3 engine two-stage pipeline ----------------------------------------


def test_engine_skips_reflection_on_turn_one(tmp_path: Path) -> None:
    """First offender turn: no opponent text yet → reflection skipped."""
    store = MemoryStore(root=tmp_path)
    # Seed empty memory so memory-active path triggers.
    store.save("run", AgentMemory(agent_id="offender"))
    store.save("run", AgentMemory(agent_id="defender"))

    speaking = _ScriptedClient(scripts=[["Hello ", "world."]])
    reflecting = _ScriptedClient(scripts=[])  # never called → AssertionError if used
    reflector = Reflector(llm_client=reflecting, topic="X")
    engine = DebateEngine(
        _settings(memory_enabled=True),
        speaking,
        topic="Is X good?",
        memory_store=store,
        run_id="run",
        reflector=reflector,
    )
    list(engine.run_one_turn("offender"))
    assert engine.transcript()[0].content == "Hello world."
    # Reflector script untouched.
    assert reflecting.calls == []
    diff = engine.last_reflection_for("offender")
    assert diff is None


def test_engine_runs_reflection_before_second_turn(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    store.save("run", AgentMemory(agent_id="offender"))
    store.save("run", AgentMemory(agent_id="defender"))

    speaking = _ScriptedClient(
        scripts=[
            ["Offender turn one."],
            ["Defender turn one."],
        ],
    )
    update_block = (
        "<UPDATE>\n"
        'add_observations: ["Offender attacked X."]\n'
        'add_strategy: ["Counter with Y."]\n'
        "drop_observations: []\n"
        "drop_strategy: []\n"
        "</UPDATE>"
    )
    reflecting = _ScriptedClient(scripts=[[update_block]])
    reflector = Reflector(llm_client=reflecting, topic="X")
    engine = DebateEngine(
        _settings(memory_enabled=True),
        speaking,
        topic="Is X good?",
        memory_store=store,
        run_id="run",
        reflector=reflector,
    )
    list(engine.run_one_turn("offender"))
    list(engine.run_one_turn("defender"))

    # Reflector was called exactly once (before defender's turn).
    assert len(reflecting.calls) == 1
    diff = engine.last_reflection_for("defender")
    assert diff is not None
    assert diff.observations_added == 1
    assert diff.strategy_added == 1
    assert diff.observations_dropped == 0

    # Defender memory updated and persisted.
    defender_mem = engine.memory_for("defender")
    assert defender_mem is not None
    assert "Offender attacked X." in defender_mem.observations
    persisted = store.load("run", "defender")
    assert "Counter with Y." in persisted.strategy


def test_engine_reflection_failure_is_non_fatal(tmp_path: Path) -> None:
    """Malformed reflection output → speaking turn proceeds unchanged."""
    store = MemoryStore(root=tmp_path)
    store.save("run", AgentMemory(agent_id="offender"))
    store.save("run", AgentMemory(agent_id="defender"))

    speaking = _ScriptedClient(
        scripts=[
            ["Offender turn one."],
            ["Defender turn one."],
        ],
    )
    reflecting = _ScriptedClient(scripts=[["this is not an update block"]])
    reflector = Reflector(llm_client=reflecting, topic="X")
    engine = DebateEngine(
        _settings(memory_enabled=True),
        speaking,
        topic="Is X good?",
        memory_store=store,
        run_id="run",
        reflector=reflector,
    )
    list(engine.run_one_turn("offender"))
    list(engine.run_one_turn("defender"))
    # Defender turn still committed.
    assert engine.transcript()[1].content == "Defender turn one."
    # Memory unchanged.
    defender_mem = engine.memory_for("defender")
    assert defender_mem is not None
    assert defender_mem.observations == ()
    assert defender_mem.strategy == ()


def test_engine_without_reflector_unchanged(tmp_path: Path) -> None:
    """Phase 11 regression: engine works as before when no reflector is wired."""
    speaking = _ScriptedClient(scripts=[["t1."]])
    engine = DebateEngine(
        _settings(memory_enabled=False),
        speaking,
        topic="Is X good?",
    )
    list(engine.run_one_turn("offender"))
    assert engine.transcript()[0].content == "t1."
    assert engine.last_reflection_for("offender") is None


# --- 12.5 closing-round behaviour swap -------------------------------------


def test_closing_round_swaps_behavior_on_last_turn(tmp_path: Path) -> None:
    """When closing_round_enabled, the agent's final turn uses CLOSING."""
    speaking = _ScriptedClient(scripts=[["t1."], ["t2."]])
    engine = DebateEngine(
        _settings(max_turns=2, closing_round_enabled=True),
        speaking,
        topic="Is X good?",
    )
    # Turn 1 (offender): not the final turn → standard behaviour.
    list(engine.run_one_turn("offender"))
    sys_t1 = speaking.calls[0][0]["content"]
    assert "CLOSING" not in sys_t1.upper() or "# Behavior: closing" not in sys_t1

    # Turn 2 (offender's 2nd, also the final): closing behaviour swapped in.
    list(engine.run_one_turn("offender"))
    sys_t2 = speaking.calls[1][0]["content"]
    assert "# Behavior: closing" in sys_t2


def test_closing_round_disabled_keeps_standard(tmp_path: Path) -> None:
    speaking = _ScriptedClient(scripts=[["t1."], ["t2."]])
    engine = DebateEngine(
        _settings(max_turns=2, closing_round_enabled=False),
        speaking,
        topic="Is X good?",
    )
    list(engine.run_one_turn("offender"))
    list(engine.run_one_turn("offender"))
    for call in speaking.calls:
        assert "# Behavior: closing" not in call[0]["content"]


# --- reflection prompt assembly --------------------------------------------


def test_build_reflection_messages_excludes_history() -> None:
    memory = _mk_memory(observations=("o0",))
    msgs = build_reflection_messages(
        agent_id="offender",
        memory=memory,
        opponent_text="The defender said something profound.",
        topic="Is X good?",
    )
    assert msgs[0]["role"] == "system"
    assert "memory keeper" in msgs[0]["content"].lower()
    user_text = msgs[1]["content"]
    assert "Is X good?" in user_text
    assert "AGAINST" in user_text  # offender stance
    assert "profound" in user_text
    assert "o0" in user_text
