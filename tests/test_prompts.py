"""
tests/test_prompts.py — Tests for the prompt builder.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.
"""

from __future__ import annotations

import pytest

from auto_debate.prompts import (
    DEFENDER_SYSTEM_TEMPLATE,
    MAX_TOPIC_LENGTH,
    OFFENDER_SYSTEM_TEMPLATE,
    OPENING_USER_MESSAGE,
    build_system_prompt,
    sanitize_topic,
)

# --- sanitize_topic ---------------------------------------------------------


def test_sanitize_strips_and_collapses() -> None:
    assert sanitize_topic("  hello   world\n") == "hello world"


def test_sanitize_truncates_long_topic() -> None:
    long_topic = "x" * (MAX_TOPIC_LENGTH + 50)
    assert len(sanitize_topic(long_topic)) == MAX_TOPIC_LENGTH


@pytest.mark.parametrize("bad", ["", "   ", "\n\t  "])
def test_sanitize_rejects_empty(bad: str) -> None:
    with pytest.raises(ValueError):
        sanitize_topic(bad)


def test_sanitize_rejects_non_string() -> None:
    with pytest.raises(TypeError):
        sanitize_topic(123)  # type: ignore[arg-type]


# --- build_system_prompt ----------------------------------------------------


@pytest.mark.parametrize("role", ["offender", "defender"])
def test_build_contains_topic_and_word_limit(role) -> None:
    prompt = build_system_prompt(role, "Pineapple belongs on pizza", 80)
    assert "Pineapple belongs on pizza" in prompt
    assert "<=80 words" in prompt


def test_offender_and_defender_differ() -> None:
    off = build_system_prompt("offender", "AI ethics", 100)
    dfn = build_system_prompt("defender", "AI ethics", 100)
    assert off != dfn
    assert "OFFENDER" in off
    assert "DEFENDER" in dfn
    assert "AGAINST" in off
    assert "IN FAVOR" in dfn


def test_build_truncates_long_topic() -> None:
    long_topic = "a" * (MAX_TOPIC_LENGTH + 100)
    prompt = build_system_prompt("offender", long_topic, 120)
    # The full original (>MAX) string must NOT appear; the truncated one must.
    assert "a" * (MAX_TOPIC_LENGTH + 1) not in prompt
    assert "a" * MAX_TOPIC_LENGTH in prompt


@pytest.mark.parametrize("bad", ["", "   "])
def test_build_rejects_empty_topic(bad: str) -> None:
    with pytest.raises(ValueError):
        build_system_prompt("offender", bad, 120)


def test_build_rejects_unknown_role() -> None:
    with pytest.raises(ValueError):
        build_system_prompt("judge", "anything", 120)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_limit", [0, -1, 1.5, True])
def test_build_rejects_bad_word_limit(bad_limit) -> None:
    with pytest.raises(ValueError):
        build_system_prompt("offender", "topic", bad_limit)  # type: ignore[arg-type]


# --- constants --------------------------------------------------------------


def test_opening_user_message_exact() -> None:
    assert OPENING_USER_MESSAGE == "Open the debate with your first argument."


def test_templates_have_placeholders() -> None:
    for tpl in (OFFENDER_SYSTEM_TEMPLATE, DEFENDER_SYSTEM_TEMPLATE):
        assert "{topic}" in tpl
        assert "{word_limit}" in tpl
