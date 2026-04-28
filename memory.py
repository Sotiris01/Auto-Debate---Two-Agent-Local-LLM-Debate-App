"""
memory.py — Per-agent structured memory document (Phase 10).

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.

Each agent owns an :class:`AgentMemory`. The document is persisted as a
small Markdown file under ``runs/<run_id>/memory/<agent_id>.md`` with
three sections:

    ## Knowledge      # web-research snippets (Phase 11 will populate)
    ## Observations   # notes about the opponent (Phase 12 will populate)
    ## Strategy       # the agent's evolving plan

Phase 10 only defines the *mechanism*: schema, ser/de, persistence, and
the prompt-block renderer that the composer can splice into a system
prompt. The phases that *write* into these slots are 11 (research) and
12 (reflection). Until then, the document stays empty and — by the
exit-criteria contract — produces output byte-identical to v0.1.0.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final, Literal

__all__ = [
    "AgentId",
    "AgentMemory",
    "MemoryStore",
    "MemoryStoreError",
]

_log = logging.getLogger(__name__)

AgentId = Literal["offender", "defender"]

_VALID_AGENT_IDS: Final[frozenset[str]] = frozenset({"offender", "defender"})

_HEADER_KNOWLEDGE: Final[str] = "## Knowledge"
_HEADER_OBSERVATIONS: Final[str] = "## Observations"
_HEADER_STRATEGY: Final[str] = "## Strategy"
_HEADER_TURN: Final[str] = "<!-- turn:"
_HEADER_TURN_RE: Final[re.Pattern[str]] = re.compile(r"^<!--\s*turn:\s*(\d+)\s*-->\s*$")

# A bullet line: ``- payload``. Leading whitespace and trailing newlines
# tolerated; anything else is treated as a continuation of the previous
# bullet (joined with a space) so multi-line entries round-trip.
_BULLET_RE: Final[re.Pattern[str]] = re.compile(r"^\s*-\s+(.*\S)\s*$")

_DEFAULT_MAX_CHARS: Final[int] = 1500


class MemoryStoreError(RuntimeError):
    """Raised when memory cannot be persisted or parsed."""


@dataclass(frozen=True)
class AgentMemory:
    """Structured memory for a single debate agent.

    All sequence fields are tuples so the dataclass can stay frozen and
    safely shared across threads / cached at module level. ``turn_index``
    is the index of the most recent turn that this memory reflects (0 =
    fresh, no turns observed yet).
    """

    agent_id: AgentId
    knowledge: tuple[str, ...] = ()
    observations: tuple[str, ...] = ()
    strategy: tuple[str, ...] = ()
    turn_index: int = 0

    def __post_init__(self) -> None:
        if self.agent_id not in _VALID_AGENT_IDS:
            raise ValueError(
                f"agent_id must be 'offender' or 'defender', got {self.agent_id!r}",
            )
        if not isinstance(self.turn_index, int) or self.turn_index < 0:
            raise ValueError(
                f"turn_index must be a non-negative int, got {self.turn_index!r}",
            )

    @property
    def is_empty(self) -> bool:
        """True when no section carries any content."""
        return not (self.knowledge or self.observations or self.strategy)

    def with_turn_index(self, turn_index: int) -> AgentMemory:
        """Return a copy with ``turn_index`` updated."""
        return replace(self, turn_index=turn_index)


# --- markdown ser/de --------------------------------------------------------


def _render_section(header: str, items: tuple[str, ...]) -> list[str]:
    lines = [header, ""]
    if not items:
        lines.append("_(empty)_")
    else:
        lines.extend(f"- {item}" for item in items)
    lines.append("")
    return lines


def _render_markdown(memory: AgentMemory) -> str:
    out: list[str] = [
        f"<!-- turn: {memory.turn_index} -->",
        f"# {memory.agent_id.title()} memory",
        "",
    ]
    out.extend(_render_section(_HEADER_KNOWLEDGE, memory.knowledge))
    out.extend(_render_section(_HEADER_OBSERVATIONS, memory.observations))
    out.extend(_render_section(_HEADER_STRATEGY, memory.strategy))
    return "\n".join(out).rstrip() + "\n"


def _parse_markdown(text: str, *, agent_id: AgentId) -> AgentMemory:
    """Inverse of :func:`_render_markdown`. Lenient about whitespace.

    Unknown section headers are ignored. Lines under each section that
    don't match the bullet pattern are also ignored (so the ``_(empty)_``
    placeholder doesn't accumulate as a real entry on round-trip).
    """
    turn_index = 0
    sections: dict[str, list[str]] = {
        _HEADER_KNOWLEDGE: [],
        _HEADER_OBSERVATIONS: [],
        _HEADER_STRATEGY: [],
    }
    current: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        m = _HEADER_TURN_RE.match(line)
        if m:
            try:
                turn_index = int(m.group(1))
            except ValueError:
                turn_index = 0
            continue
        stripped = line.strip()
        if stripped in sections:
            current = stripped
            continue
        if stripped.startswith("## "):
            # Some other header — leave the current section.
            current = None
            continue
        if current is None:
            continue
        bullet = _BULLET_RE.match(line)
        if bullet:
            sections[current].append(bullet.group(1).strip())

    return AgentMemory(
        agent_id=agent_id,
        knowledge=tuple(sections[_HEADER_KNOWLEDGE]),
        observations=tuple(sections[_HEADER_OBSERVATIONS]),
        strategy=tuple(sections[_HEADER_STRATEGY]),
        turn_index=turn_index,
    )


# --- prompt block ----------------------------------------------------------


def _truncate_section(items: tuple[str, ...], budget: int) -> tuple[str, ...]:
    """Drop oldest items first until the rendered section fits ``budget`` chars.

    Returns the (possibly shortened) tail of ``items``. The very-last
    bullet is never dropped — if even one bullet exceeds the budget, it
    is kept intact (the budget is advisory, not a hard wall).
    """
    if not items:
        return items
    kept: list[str] = []
    used = 0
    # Walk from newest to oldest so the most recent entries survive.
    for item in reversed(items):
        size = len(item) + 3  # leading "- " + trailing "\n"
        if kept and used + size > budget:
            break
        kept.append(item)
        used += size
    kept.reverse()
    return tuple(kept)


def _render_prompt_section(label: str, items: tuple[str, ...]) -> list[str]:
    if not items:
        return []
    out = [label]
    out.extend(f"- {item}" for item in items)
    return out


def render_prompt_block(
    memory: AgentMemory,
    *,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> str:
    """Render an :class:`AgentMemory` as the body of a ``<MEMORY>`` block.

    The composer wraps the returned string in ``<MEMORY>...</MEMORY>``;
    this function only produces the inner text. An all-empty memory
    returns an empty string, which the composer treats as "no memory
    block at all" — guaranteeing v0.1.0 output is preserved when the
    feature flag is enabled but no content has been written yet.
    """
    if memory.is_empty:
        return ""
    if max_chars <= 0:
        raise ValueError(f"max_chars must be > 0, got {max_chars!r}")

    # Budget is split evenly across the three sections; each section's
    # truncator drops oldest-first.
    per_section = max_chars // 3
    knowledge = _truncate_section(memory.knowledge, per_section)
    observations = _truncate_section(memory.observations, per_section)
    strategy = _truncate_section(memory.strategy, per_section)

    parts: list[str] = []
    parts.extend(_render_prompt_section("Knowledge:", knowledge))
    parts.extend(_render_prompt_section("Observations:", observations))
    parts.extend(_render_prompt_section("Strategy:", strategy))
    return "\n".join(parts)


# --- store ------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryStore:
    """Filesystem-backed read/write contract for agent memory.

    Layout::

        <root>/
            <run_id>/
                memory/
                    offender.md
                    defender.md

    The store never silently creates parent directories outside its
    ``root`` — callers must pass an explicit, deliberate path. ``root``
    defaults to ``runs/`` next to the project root.
    """

    root: Path = field(default_factory=lambda: Path("runs"))
    max_chars: int = _DEFAULT_MAX_CHARS

    def __post_init__(self) -> None:
        if self.max_chars <= 0:
            raise ValueError(f"max_chars must be > 0, got {self.max_chars!r}")

    # --- paths ----------------------------------------------------------

    def run_dir(self, run_id: str) -> Path:
        if not run_id or "/" in run_id or "\\" in run_id or run_id in (".", ".."):
            raise ValueError(f"unsafe run_id: {run_id!r}")
        return self.root / run_id / "memory"

    def path_for(self, run_id: str, agent_id: AgentId) -> Path:
        if agent_id not in _VALID_AGENT_IDS:
            raise ValueError(f"unknown agent_id: {agent_id!r}")
        return self.run_dir(run_id) / f"{agent_id}.md"

    # --- io -------------------------------------------------------------

    def load(self, run_id: str, agent_id: AgentId) -> AgentMemory:
        """Load memory for ``agent_id`` under ``run_id``.

        Returns a fresh empty :class:`AgentMemory` when the file does
        not exist yet — first-turn behaviour.
        """
        path = self.path_for(run_id, agent_id)
        if not path.exists():
            return AgentMemory(agent_id=agent_id)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise MemoryStoreError(f"failed reading {path}: {exc}") from exc
        return _parse_markdown(text, agent_id=agent_id)

    def save(self, run_id: str, memory: AgentMemory) -> Path:
        """Persist ``memory`` and return the file path it was written to."""
        path = self.path_for(run_id, memory.agent_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_render_markdown(memory), encoding="utf-8")
        except OSError as exc:
            raise MemoryStoreError(f"failed writing {path}: {exc}") from exc
        _log.debug(
            "saved memory: run=%s agent=%s knowledge=%d observations=%d strategy=%d",
            run_id,
            memory.agent_id,
            len(memory.knowledge),
            len(memory.observations),
            len(memory.strategy),
        )
        return path

    def to_prompt_block(self, memory: AgentMemory) -> str:
        """Render ``memory`` as a composer-ready ``<MEMORY>`` body string."""
        return render_prompt_block(memory, max_chars=self.max_chars)
