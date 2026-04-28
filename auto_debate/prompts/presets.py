"""
prompts.presets — Phase 14 named persona/behavior bundles + compatibility check.

A *preset* is a pre-vetted (offender, defender) pair where each side
carries its own persona name and behavior name. This is purely a UI
convenience: the engine only ever sees fragments, never preset names.

The compatibility checker (:func:`check_compatibility`) is a tiny
heuristic that flags pairings the v0.1.0 prompts can already render but
that tend to produce internally contradictory turns (e.g. ``concise`` +
``analytical`` — one demands < 50 words, the other demands at least two
numbered claims plus a framing sentence and a conclusion). It does not
call an LLM; it just consults a small built-in rule table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "BUILTIN_PRESETS",
    "AgentPreset",
    "DebatePreset",
    "check_compatibility",
    "list_presets",
    "preset_by_name",
]


@dataclass(frozen=True)
class AgentPreset:
    """One side of a debate preset — fragment names, not loaded fragments."""

    persona: str
    behavior: str


@dataclass(frozen=True)
class DebatePreset:
    """A named (offender, defender) bundle backed by registry entries."""

    name: str
    description: str
    offender: AgentPreset
    defender: AgentPreset


# --- built-in presets -------------------------------------------------------
#
# Every preset references only fragments that ship in
# ``prompts/library/{personas,behaviors}/`` — keep this in sync with the
# JSON catalogue (see Phase 14 in ROADMAP.md).

BUILTIN_PRESETS: Final[tuple[DebatePreset, ...]] = (
    DebatePreset(
        name="Academic debate",
        description=(
            "Two professors. Steelman opposing arguments before rebutting; "
            "cite evidence on every turn."
        ),
        offender=AgentPreset(persona="professor", behavior="steelman"),
        defender=AgentPreset(persona="professor", behavior="cite_evidence"),
    ),
    DebatePreset(
        name="Tabloid showdown",
        description=("Loud headlines vs. polished pivots. Both sides keep it under 50 words."),
        offender=AgentPreset(persona="tabloid", behavior="concise"),
        defender=AgentPreset(persona="politician", behavior="concise"),
    ),
    DebatePreset(
        name="Socratic clinic",
        description=(
            "Probing questions vs. structured analytical answers. "
            "Good for stress-testing weak claims."
        ),
        offender=AgentPreset(persona="socratic", behavior="standard"),
        defender=AgentPreset(persona="professor", behavior="analytical"),
    ),
    DebatePreset(
        name="Comedy club",
        description="Dry wit vs. populist rhetoric. Civility intact, jokes intentional.",
        offender=AgentPreset(persona="comedian", behavior="standard"),
        defender=AgentPreset(persona="politician", behavior="standard"),
    ),
)


def list_presets() -> tuple[DebatePreset, ...]:
    """Return all built-in presets in display order."""
    return BUILTIN_PRESETS


def preset_by_name(name: str) -> DebatePreset | None:
    """Look up a built-in preset by its display name (case-sensitive)."""
    for preset in BUILTIN_PRESETS:
        if preset.name == name:
            return preset
    return None


# --- compatibility heuristic ------------------------------------------------
#
# Pairs of (kind_a, name_a, kind_b, name_b) that the maintainers have
# observed to fight each other in practice. Order-insensitive lookups are
# normalised by sorting the two ``(kind, name)`` keys in
# :func:`check_compatibility`. Keep messages short and actionable.

_INCOMPATIBILITIES: Final[dict[tuple[tuple[str, str], tuple[str, str]], str]] = {
    (("behavior", "analytical"), ("behavior", "concise")): (
        "'analytical' demands at least two numbered claims plus a framing "
        "and conclusion sentence; 'concise' caps the whole turn at 50 "
        "words. Pick one."
    ),
    (("behavior", "cite_evidence"), ("behavior", "concise")): (
        "'cite_evidence' requires a named source per turn, which usually "
        "blows past the 50-word cap of 'concise'."
    ),
    (("behavior", "closing"), ("behavior", "cite_evidence")): (
        "'closing' forbids fresh evidence; 'cite_evidence' demands it. "
        "Use 'closing' on its own for the final round."
    ),
}


def _key(kind: str, name: str) -> tuple[str, str]:
    return (kind, name)


def check_compatibility(
    *,
    persona: str,
    behavior: str,
    other_persona: str | None = None,
    other_behavior: str | None = None,
) -> list[str]:
    """Return human-readable warnings for contradictory combinations.

    Empty list = nothing flagged. The check is a pure rule lookup: it
    never imports the registry or calls an LLM. ``other_persona`` /
    ``other_behavior`` are optional — when supplied they cross-check the
    opposing agent's fragments against the speaking agent's, but only
    behavior-vs-behavior pairs are currently ruled on.
    """
    warnings: list[str] = []
    sides: list[tuple[str, str]] = [
        _key("persona", persona),
        _key("behavior", behavior),
    ]
    if other_persona is not None:
        sides.append(_key("persona", other_persona))
    if other_behavior is not None:
        sides.append(_key("behavior", other_behavior))

    seen: set[frozenset[tuple[str, str]]] = set()
    for i, a in enumerate(sides):
        for b in sides[i + 1 :]:
            if a == b:
                continue
            pair_key = frozenset({a, b})
            if pair_key in seen:
                continue
            seen.add(pair_key)
            ordered = (a, b) if a <= b else (b, a)
            message = _INCOMPATIBILITIES.get(ordered)
            if message is not None:
                warnings.append(message)
    return warnings
