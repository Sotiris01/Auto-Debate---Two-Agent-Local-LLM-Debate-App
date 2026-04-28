"""
tests/test_prompt_composer.py — Tests for the Phase 9 composable prompt layer.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.

Covers:
    * default composition is byte-identical to v0.1.0 build_system_prompt
    * persona / behavior directives are inserted in the right order
    * memory block is included only when non-empty
    * placeholder validation (unfillable -> PromptCompositionError)
    * registry round-trip (list / load / fall-through to defaults)
    * registry rejects malformed JSON / unsafe names
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_debate.prompts import (
    DEFAULT_BEHAVIOR_NAME,
    DEFAULT_PERSONA_NAME,
    DEFENDER_ROLE,
    NEUTRAL_PERSONA,
    OFFENDER_ROLE,
    STANDARD_BEHAVIOR,
    BehaviorFragment,
    FragmentNotFoundError,
    InvalidFragmentError,
    PersonaFragment,
    PromptComposer,
    PromptCompositionError,
    RoleFragment,
    build_system_prompt,
    list_fragments,
    load_behavior,
    load_fragment,
    load_persona,
    load_role,
)

# --- regression: defaults match v0.1.0 -------------------------------------


def test_default_composition_matches_v0_1_0_offender() -> None:
    """PromptComposer with NEUTRAL/STANDARD must reproduce the v0.1.0 string."""
    composer = PromptComposer(word_limit=120)
    expected = (
        'You are THE OFFENDER in a structured debate on the topic: "Pineapple on pizza".\n'
        "You argue strictly AGAINST the topic / criticize it.\n"
        "Rules:\n"
        "- Stay in character. Never agree with the Defender.\n"
        "- Respond in <=120 words, plain prose, no bullet lists, no headers.\n"
        "- Always attack the Defender's most recent argument before adding a new point.\n"
        "- Be sharp but civil. No slurs, no personal attacks on the user.\n"
        "- Do not mention that you are an AI or that this is a prompt.\n"
        "- Do not restate the topic verbatim."
    )
    assert composer.compose(role=OFFENDER_ROLE, topic="Pineapple on pizza") == expected


def test_default_composition_matches_v0_1_0_defender() -> None:
    composer = PromptComposer(word_limit=80)
    out = composer.compose(role=DEFENDER_ROLE, topic="Remote work is better")
    assert "THE DEFENDER" in out
    assert "Remote work is better" in out
    assert "<=80 words" in out
    # No persona / behavior / memory sections present at all.
    assert "# Persona" not in out
    assert "# Behavior" not in out
    assert "<MEMORY>" not in out


def test_legacy_shim_matches_composer() -> None:
    """``build_system_prompt`` is a pure shim — output must equal composer."""
    composer = PromptComposer(word_limit=100)
    direct = composer.compose(role=OFFENDER_ROLE, topic="x")
    shim = build_system_prompt("offender", "x", 100)
    assert direct == shim


# --- persona / behavior overlays -------------------------------------------


def test_persona_directives_render_when_present() -> None:
    composer = PromptComposer(word_limit=100)
    persona = PersonaFragment(
        name="snarky",
        tone="snarky",
        extra_directives=("Roll your eyes audibly.", "Use deadpan irony."),
    )
    out = composer.compose(role=OFFENDER_ROLE, topic="cats", persona=persona)
    assert "# Persona: snarky" in out
    assert "- Roll your eyes audibly." in out
    assert "- Use deadpan irony." in out
    # Persona section comes after the role section.
    assert out.index("THE OFFENDER") < out.index("# Persona: snarky")


def test_behavior_directives_render_when_present() -> None:
    composer = PromptComposer(word_limit=100)
    behavior = BehaviorFragment(
        name="cite_evidence",
        directives=("Cite at least one specific year.",),
    )
    out = composer.compose(role=OFFENDER_ROLE, topic="cats", behavior=behavior)
    assert "# Behavior: cite_evidence" in out
    assert "- Cite at least one specific year." in out


def test_persona_then_behavior_ordering() -> None:
    composer = PromptComposer(word_limit=100)
    persona = PersonaFragment(name="p", extra_directives=("p-line",))
    behavior = BehaviorFragment(name="b", directives=("b-line",))
    out = composer.compose(
        role=OFFENDER_ROLE,
        topic="t",
        persona=persona,
        behavior=behavior,
    )
    assert out.index("# Persona: p") < out.index("# Behavior: b")


def test_memory_block_included_only_when_non_empty() -> None:
    composer = PromptComposer(word_limit=100)
    out_empty = composer.compose(role=OFFENDER_ROLE, topic="t", memory="   ")
    assert "<MEMORY>" not in out_empty
    out_full = composer.compose(
        role=OFFENDER_ROLE,
        topic="t",
        memory="opp said X.\nopp said Y.",
    )
    assert "<MEMORY>" in out_full
    assert "opp said X." in out_full
    assert "</MEMORY>" in out_full


# --- placeholder validation -------------------------------------------------


def test_role_with_unknown_placeholder_rejected() -> None:
    composer = PromptComposer(word_limit=100)
    bad = RoleFragment(
        name="bad",
        role="offender",
        system_text="topic={topic}, mystery={mystery}",
    )
    with pytest.raises(PromptCompositionError, match="unknown placeholders"):
        composer.compose(role=bad, topic="t")


def test_word_limit_must_be_positive_int() -> None:
    with pytest.raises(PromptCompositionError):
        PromptComposer(word_limit=0)
    with pytest.raises(PromptCompositionError):
        PromptComposer(word_limit=-5)


# --- registry --------------------------------------------------------------


def test_list_fragments_returns_default_names() -> None:
    roles = list_fragments("roles")
    personas = list_fragments("personas")
    behaviors = list_fragments("behaviors")
    assert "offender" in roles and "defender" in roles
    assert DEFAULT_PERSONA_NAME in personas
    assert DEFAULT_BEHAVIOR_NAME in behaviors


def test_list_fragments_rejects_bad_kind() -> None:
    with pytest.raises(ValueError):
        list_fragments("snacks")  # type: ignore[arg-type]


def test_load_role_returns_role_fragment() -> None:
    fragment = load_role("offender")
    assert isinstance(fragment, RoleFragment)
    assert fragment.role == "offender"
    assert "{topic}" in fragment.system_text


def test_load_persona_default_falls_back_to_neutral_when_missing(tmp_path: Path) -> None:
    # Empty library root: no neutral.json exists -> should still return NEUTRAL.
    (tmp_path / "personas").mkdir()
    fragment = load_persona(DEFAULT_PERSONA_NAME, library_root=tmp_path)
    assert fragment is NEUTRAL_PERSONA


def test_load_behavior_default_falls_back_to_standard_when_missing(
    tmp_path: Path,
) -> None:
    (tmp_path / "behaviors").mkdir()
    fragment = load_behavior(DEFAULT_BEHAVIOR_NAME, library_root=tmp_path)
    assert fragment is STANDARD_BEHAVIOR


def test_load_persona_non_default_missing_raises(tmp_path: Path) -> None:
    (tmp_path / "personas").mkdir()
    with pytest.raises(FragmentNotFoundError):
        load_persona("ghost", library_root=tmp_path)


def test_load_fragment_rejects_path_traversal() -> None:
    with pytest.raises(ValueError):
        load_fragment("personas", "../etc/passwd")


def test_invalid_json_raises_invalid_fragment(tmp_path: Path) -> None:
    target = tmp_path / "personas"
    target.mkdir()
    (target / "broken.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(InvalidFragmentError):
        load_fragment("personas", "broken", library_root=tmp_path)


def test_role_json_with_bad_role_field_raises(tmp_path: Path) -> None:
    target = tmp_path / "roles"
    target.mkdir()
    (target / "bogus.json").write_text(
        json.dumps(
            {
                "name": "bogus",
                "role": "judge",  # invalid
                "system_text": "x",
            },
        ),
        encoding="utf-8",
    )
    with pytest.raises(InvalidFragmentError):
        load_fragment("roles", "bogus", library_root=tmp_path)


def test_round_trip_loaded_role_matches_in_code_default() -> None:
    """JSON role fragments must produce the same prompt as the in-code defaults."""
    composer = PromptComposer(word_limit=120)
    loaded = load_role("offender")
    assert loaded.system_text == OFFENDER_ROLE.system_text
    a = composer.compose(role=loaded, topic="x")
    b = composer.compose(role=OFFENDER_ROLE, topic="x")
    assert a == b


def test_extra_persona_and_behavior_are_loadable() -> None:
    """Sanity check the two non-default examples we ship."""
    professor = load_persona("professor")
    assert isinstance(professor, PersonaFragment)
    assert professor.extra_directives  # non-empty
    steelman = load_behavior("steelman")
    assert isinstance(steelman, BehaviorFragment)
    assert steelman.directives  # non-empty
