"""Tests for the Phase 14 persona / behavior library + presets."""

from __future__ import annotations

import pytest

from auto_debate.prompts import (
    BUILTIN_PRESETS,
    OFFENDER_ROLE,
    PromptComposer,
    check_compatibility,
    list_fragments,
    list_presets,
    load_behavior,
    load_persona,
    preset_by_name,
)

# --- 14.1 / 14.2 catalogue completeness -------------------------------------


_REQUIRED_PERSONAS = ("neutral", "professor", "socratic", "tabloid", "politician", "comedian")
_REQUIRED_BEHAVIORS = (
    "standard",
    "steelman",
    "closing",
    "cite_evidence",
    "concise",
    "analytical",
)


@pytest.mark.parametrize("name", _REQUIRED_PERSONAS)
def test_persona_loads_from_registry(name: str) -> None:
    persona = load_persona(name)
    assert persona.name == name
    # Non-default personas all carry at least one extra directive.
    if name != "neutral":
        assert persona.extra_directives, f"{name} should ship with directives"


@pytest.mark.parametrize("name", _REQUIRED_BEHAVIORS)
def test_behavior_loads_from_registry(name: str) -> None:
    behavior = load_behavior(name)
    assert behavior.name == name
    # Non-default behaviors all carry at least one directive.
    if name != "standard":
        assert behavior.directives, f"{name} should ship with directives"


def test_persona_catalogue_has_at_least_five() -> None:
    personas = list_fragments("personas")
    assert len(personas) >= 5
    for required in _REQUIRED_PERSONAS:
        assert required in personas


def test_behavior_catalogue_has_at_least_four() -> None:
    behaviors = list_fragments("behaviors")
    # Phase 14 ships 6 (standard, steelman, closing, cite_evidence, concise, analytical).
    assert len(behaviors) >= 4
    for required in _REQUIRED_BEHAVIORS:
        assert required in behaviors


# --- 14.3 compatibility heuristic -------------------------------------------


def test_check_compatibility_clean_pair_has_no_warnings() -> None:
    assert check_compatibility(persona="professor", behavior="cite_evidence") == []


def test_check_compatibility_flags_concise_plus_analytical() -> None:
    warnings = check_compatibility(
        persona="neutral",
        behavior="concise",
        other_persona="professor",
        other_behavior="analytical",
    )
    assert any("analytical" in w and "concise" in w for w in warnings)


def test_check_compatibility_flags_concise_plus_cite_evidence() -> None:
    warnings = check_compatibility(persona="tabloid", behavior="cite_evidence")
    # cite_evidence on its own is fine; only paired with concise should it flag.
    assert warnings == []
    paired = check_compatibility(
        persona="tabloid",
        behavior="cite_evidence",
        other_persona="neutral",
        other_behavior="concise",
    )
    assert any("cite_evidence" in w for w in paired)


def test_check_compatibility_dedupes_when_both_sides_match_pair() -> None:
    """Same incompatibility shouldn't be reported twice."""
    warnings = check_compatibility(
        persona="neutral",
        behavior="analytical",
        other_persona="neutral",
        other_behavior="concise",
    )
    assert len(warnings) == 1


# --- 14.4 presets ------------------------------------------------------------


def test_built_in_presets_have_at_least_three() -> None:
    presets = list_presets()
    assert len(presets) >= 3


def test_preset_by_name_round_trips() -> None:
    for preset in BUILTIN_PRESETS:
        assert preset_by_name(preset.name) is preset
    assert preset_by_name("does-not-exist") is None


def test_every_preset_references_existing_fragments() -> None:
    available_personas = set(list_fragments("personas"))
    available_behaviors = set(list_fragments("behaviors"))
    for preset in BUILTIN_PRESETS:
        for side in (preset.offender, preset.defender):
            assert side.persona in available_personas, (
                f"{preset.name} references unknown persona {side.persona!r}"
            )
            assert side.behavior in available_behaviors, (
                f"{preset.name} references unknown behavior {side.behavior!r}"
            )


# --- 14.5 reproducibility / persona-drift snapshots --------------------------
#
# We cannot run a live gemma3:4b in CI, so we snapshot the *composed system
# prompt* for each persona instead. This catches accidental edits to a
# persona JSON file (drift) without depending on Ollama. The snapshot
# values pin the directive text — bumping a persona's wording requires
# updating these constants on purpose.


_PROMPT_SNAPSHOTS: dict[str, tuple[str, ...]] = {
    "neutral": (),  # no directives → no signature snippet to pin
    "professor": (
        "Speak as a tenured academic",
        "concrete examples and named studies",
    ),
    "socratic": (
        "pointed question",
        "Define key terms before disputing them",
    ),
    "tabloid": (
        "short, punchy sentences",
        "front-page headline",
    ),
    "politician": (
        "values the audience already holds",
        "rule of three",
    ),
    "comedian": (
        "wry observation",
        "concrete, slightly silly analogy",
    ),
}


@pytest.mark.parametrize("persona_name", list(_PROMPT_SNAPSHOTS))
def test_persona_directive_snapshot(persona_name: str) -> None:
    persona = load_persona(persona_name)
    composer = PromptComposer(word_limit=120)
    rendered = composer.compose(
        role=OFFENDER_ROLE,
        topic="Should renewable energy expand?",
        persona=persona,
        behavior=load_behavior("standard"),
    )
    for fragment in _PROMPT_SNAPSHOTS[persona_name]:
        assert fragment in rendered, (
            f"persona {persona_name!r} drifted: {fragment!r} no longer appears"
        )


# --- 14.4 engine integration: per-agent overrides ----------------------------


def test_engine_per_agent_overrides_change_defender_prompt(tmp_path: object) -> None:
    """Defender-side persona/behavior overrides flow into its system prompt."""
    from collections.abc import Iterator
    from typing import Any

    from auto_debate.config import Settings
    from auto_debate.engine import DebateEngine

    class _Client:
        def __init__(self) -> None:
            self.calls: list[list[dict[str, Any]]] = []

        def stream_chat(
            self,
            messages: list[dict[str, Any]],
            *,
            options: dict[str, Any] | None = None,
            model: str | None = None,
        ) -> Iterator[str]:
            self.calls.append([dict(m) for m in messages])
            yield "ok."

    settings = Settings(
        ollama_host="http://localhost:11434",
        model_name="gemma3:4b",
        max_turns=2,
        temperature=0.7,
        top_p=0.9,
        word_limit=120,
    )
    client = _Client()
    engine = DebateEngine(
        settings,
        client,
        topic="Is X good?",
        persona=load_persona("tabloid"),
        behavior=load_behavior("concise"),
        defender_persona=load_persona("professor"),
        defender_behavior=load_behavior("cite_evidence"),
    )
    list(engine.run_one_turn("offender"))
    list(engine.run_one_turn("defender"))

    offender_sys = client.calls[0][0]["content"]
    defender_sys = client.calls[1][0]["content"]
    assert "front-page headline" in offender_sys  # tabloid
    assert "tenured academic" in defender_sys  # professor
    assert "concrete piece of evidence" in defender_sys  # cite_evidence
    assert "concrete piece of evidence" not in offender_sys
