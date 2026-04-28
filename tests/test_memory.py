"""
tests/test_memory.py — Tests for the Phase 10 per-agent memory layer.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.

Covers:
    * AgentMemory schema validation
    * Markdown round-trip (render -> parse -> equal)
    * MemoryStore.load returns a fresh empty memory when no file exists
    * MemoryStore.save writes under runs/<run_id>/memory/<agent_id>.md
    * to_prompt_block returns "" for empty memory and a sensibly bounded
      string when populated, dropping oldest items first
    * path-traversal-style run_id values are rejected
    * Engine integration: memory_enabled=False matches v0.1.0 (regression)
    * Engine integration: memory_enabled=True with empty memory still
      matches v0.1.0 (no <MEMORY> block emitted)
    * Engine integration: memory file is written under runs/<run_id>/memory/
      after a turn completes
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from config import Settings
from engine import DebateEngine
from memory import AgentMemory, MemoryStore, MemoryStoreError, render_prompt_block

# --- helpers ----------------------------------------------------------------


def _settings(*, memory_enabled: bool = False) -> Settings:
    return Settings(
        ollama_host="http://localhost:11434",
        model_name="gemma3:4b",
        max_turns=2,
        temperature=0.8,
        top_p=0.95,
        word_limit=60,
        memory_enabled=memory_enabled,
    )


class _ScriptedClient:
    """Minimal fake LLM that yields a single canned response per turn."""

    def __init__(self, scripted: list[list[str]]) -> None:
        self._scripted = list(scripted)
        self.system_prompts_seen: list[str] = []

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> Iterator[str]:
        # Capture the system prompt the engine sent so the test can assert
        # presence / absence of <MEMORY> blocks.
        for msg in messages:
            if msg.get("role") == "system":
                self.system_prompts_seen.append(str(msg["content"]))
                break
        if not self._scripted:
            return iter(())
        return iter(self._scripted.pop(0))


# --- AgentMemory schema -----------------------------------------------------


def test_agent_memory_defaults_are_empty() -> None:
    mem = AgentMemory(agent_id="offender")
    assert mem.knowledge == ()
    assert mem.observations == ()
    assert mem.strategy == ()
    assert mem.turn_index == 0
    assert mem.is_empty is True


def test_agent_memory_rejects_unknown_agent_id() -> None:
    with pytest.raises(ValueError):
        AgentMemory(agent_id="judge")  # type: ignore[arg-type]


def test_agent_memory_rejects_negative_turn_index() -> None:
    with pytest.raises(ValueError):
        AgentMemory(agent_id="offender", turn_index=-1)


def test_with_turn_index_preserves_other_fields() -> None:
    mem = AgentMemory(
        agent_id="defender",
        knowledge=("k1",),
        observations=("o1",),
        strategy=("s1",),
        turn_index=2,
    )
    bumped = mem.with_turn_index(7)
    assert bumped.turn_index == 7
    assert bumped.knowledge == ("k1",)
    assert bumped.observations == ("o1",)
    assert bumped.strategy == ("s1",)


# --- markdown round-trip ----------------------------------------------------


def test_markdown_round_trip_preserves_content(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    original = AgentMemory(
        agent_id="offender",
        knowledge=("source A says X (https://example.com/a)",),
        observations=("opp leaned on appeals to tradition on turn 2",),
        strategy=("press the cost-of-living angle next",),
        turn_index=3,
    )
    path = store.save("run-001", original)
    assert path.exists()
    assert path == tmp_path / "run-001" / "memory" / "offender.md"

    reloaded = store.load("run-001", "offender")
    assert reloaded == original


def test_markdown_round_trip_for_empty_memory(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    original = AgentMemory(agent_id="defender")
    store.save("run-002", original)
    reloaded = store.load("run-002", "defender")
    assert reloaded == original
    assert reloaded.is_empty


def test_load_returns_empty_when_file_missing(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    mem = store.load("nonexistent-run", "offender")
    assert mem == AgentMemory(agent_id="offender")


# --- prompt block -----------------------------------------------------------


def test_prompt_block_for_empty_memory_is_empty_string() -> None:
    mem = AgentMemory(agent_id="offender")
    assert render_prompt_block(mem) == ""


def test_prompt_block_renders_sections_with_bullets() -> None:
    mem = AgentMemory(
        agent_id="offender",
        knowledge=("k1", "k2"),
        observations=("o1",),
        strategy=("s1",),
    )
    block = render_prompt_block(mem)
    assert "Knowledge:" in block
    assert "- k1" in block and "- k2" in block
    assert "Observations:" in block
    assert "- o1" in block
    assert "Strategy:" in block
    assert "- s1" in block


def test_prompt_block_drops_oldest_first_when_over_budget() -> None:
    long_items = tuple(f"item-{i}-" + ("x" * 40) for i in range(20))
    mem = AgentMemory(agent_id="offender", knowledge=long_items)
    block = render_prompt_block(mem, max_chars=300)
    assert long_items[-1] in block  # newest survives
    assert long_items[0] not in block  # oldest dropped


def test_prompt_block_rejects_non_positive_budget() -> None:
    mem = AgentMemory(agent_id="offender", knowledge=("k",))
    with pytest.raises(ValueError):
        render_prompt_block(mem, max_chars=0)


# --- store path safety -----------------------------------------------------


def test_run_id_path_traversal_rejected(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    for bad in ("../etc", "a/b", "..", "."):
        with pytest.raises(ValueError):
            store.path_for(bad, "offender")


def test_unknown_agent_id_rejected_by_path_for(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    with pytest.raises(ValueError):
        store.path_for("run-1", "judge")  # type: ignore[arg-type]


def test_load_raises_memory_store_error_on_unreadable_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MemoryStore(root=tmp_path)
    store.save("run-x", AgentMemory(agent_id="offender", knowledge=("k",)))

    def boom(self: Path, encoding: str | None = None) -> str:
        raise OSError("disk on fire")

    monkeypatch.setattr(Path, "read_text", boom)
    with pytest.raises(MemoryStoreError):
        store.load("run-x", "offender")


# --- engine integration ----------------------------------------------------


def test_memory_disabled_default_matches_v0_1_0(tmp_path: Path) -> None:
    """memory_enabled=False (the default) MUST keep v0.1.0 output."""
    client = _ScriptedClient([["t1"]])
    engine = DebateEngine(_settings(), client, "Pineapple on pizza")
    list(engine.run_one_turn("offender"))
    assert len(client.system_prompts_seen) == 1
    assert "<MEMORY>" not in client.system_prompts_seen[0]
    # No runs/ directory should be created.
    assert not (tmp_path / "runs").exists()


def test_memory_enabled_with_empty_memory_does_not_emit_block(
    tmp_path: Path,
) -> None:
    """Exit criterion #3: empty memory + flag on still has no <MEMORY> block."""
    client = _ScriptedClient([["t1"]])
    store = MemoryStore(root=tmp_path)
    engine = DebateEngine(
        _settings(memory_enabled=True),
        client,
        "Pineapple on pizza",
        memory_store=store,
        run_id="run-empty",
    )
    list(engine.run_one_turn("offender"))
    assert "<MEMORY>" not in client.system_prompts_seen[0]


def test_memory_enabled_writes_files_after_turn(tmp_path: Path) -> None:
    client = _ScriptedClient([["t1"]])
    store = MemoryStore(root=tmp_path)
    engine = DebateEngine(
        _settings(memory_enabled=True),
        client,
        "Pineapple on pizza",
        memory_store=store,
        run_id="run-write",
    )
    list(engine.run_one_turn("offender"))
    off_path = tmp_path / "run-write" / "memory" / "offender.md"
    def_path = tmp_path / "run-write" / "memory" / "defender.md"
    assert off_path.exists()
    assert def_path.exists()
    # turn_index was stamped to 1 after the first commit.
    reloaded = store.load("run-write", "offender")
    assert reloaded.turn_index == 1


def test_memory_enabled_with_preloaded_content_emits_block(
    tmp_path: Path,
) -> None:
    """When memory has content saved on disk, the <MEMORY> block appears."""
    store = MemoryStore(root=tmp_path)
    store.save(
        "run-preload",
        AgentMemory(
            agent_id="offender",
            knowledge=("Pineapple yields debated lol",),
            turn_index=0,
        ),
    )
    store.save(
        "run-preload",
        AgentMemory(agent_id="defender"),
    )
    client = _ScriptedClient([["t1"]])
    engine = DebateEngine(
        _settings(memory_enabled=True),
        client,
        "Pineapple on pizza",
        memory_store=store,
        run_id="run-preload",
    )
    list(engine.run_one_turn("offender"))
    sys_prompt = client.system_prompts_seen[0]
    assert "<MEMORY>" in sys_prompt
    assert "Pineapple yields debated lol" in sys_prompt
