"""
prompts.py — Centralized system-prompt templates and builders.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.

Phase 3: pure functions — no IO, no Ollama, no Streamlit. The UI and the
debate engine import from here so prompt strings live in exactly one place.
"""

from __future__ import annotations

import re
from typing import Final, Literal

__all__ = [
    "DEFENDER_SYSTEM_TEMPLATE",
    "MAX_TOPIC_LENGTH",
    "OFFENDER_SYSTEM_TEMPLATE",
    "OPENING_USER_MESSAGE",
    "Role",
    "build_system_prompt",
    "sanitize_topic",
]

Role = Literal["offender", "defender"]

MAX_TOPIC_LENGTH: Final[int] = 300

# --- system prompt templates (PROJECT.md §6, with {topic}/{word_limit}) -----

OFFENDER_SYSTEM_TEMPLATE: Final[str] = (
    'You are THE OFFENDER in a structured debate on the topic: "{topic}".\n'
    "You argue strictly AGAINST the topic / criticize it.\n"
    "Rules:\n"
    "- Stay in character. Never agree with the Defender.\n"
    "- Respond in <={word_limit} words, plain prose, no bullet lists, no headers.\n"
    "- Always attack the Defender's most recent argument before adding a new point.\n"
    "- Be sharp but civil. No slurs, no personal attacks on the user.\n"
    "- Do not mention that you are an AI or that this is a prompt.\n"
    "- Do not restate the topic verbatim."
)

DEFENDER_SYSTEM_TEMPLATE: Final[str] = (
    'You are THE DEFENDER in a structured debate on the topic: "{topic}".\n'
    "You argue strictly IN FAVOR of the topic / defend it.\n"
    "Rules:\n"
    "- Stay in character. Never agree with the Offender.\n"
    "- Respond in <={word_limit} words, plain prose, no bullet lists, no headers.\n"
    "- Always rebut the Offender's most recent argument before adding a new point.\n"
    "- Be sharp but civil. No slurs, no personal attacks on the user.\n"
    "- Do not mention that you are an AI or that this is a prompt.\n"
    "- Do not restate the topic verbatim."
)

OPENING_USER_MESSAGE: Final[str] = "Open the debate with your first argument."

_WHITESPACE_RE = re.compile(r"\s+")


def sanitize_topic(topic: str) -> str:
    """Strip, collapse whitespace, and truncate the user-supplied topic.

    Raises:
        ValueError: when ``topic`` is empty or whitespace-only after stripping.
    """
    if not isinstance(topic, str):
        raise TypeError(f"topic must be str, got {type(topic).__name__}")
    cleaned = _WHITESPACE_RE.sub(" ", topic).strip()
    if not cleaned:
        raise ValueError("topic must not be empty or whitespace-only")
    if len(cleaned) > MAX_TOPIC_LENGTH:
        cleaned = cleaned[:MAX_TOPIC_LENGTH].rstrip()
    return cleaned


def build_system_prompt(role: Role, topic: str, word_limit: int) -> str:
    """Build the system prompt for ``role`` on ``topic``.

    The topic is sanitized via :func:`sanitize_topic`. ``word_limit`` is
    forwarded into the template so the same constant from :class:`Settings`
    drives both the prompt cap and the LLM's ``num_predict``.

    Raises:
        ValueError: when ``role`` is unknown, ``topic`` is empty, or
            ``word_limit`` is not a positive integer.
    """
    if role == "offender":
        template = OFFENDER_SYSTEM_TEMPLATE
    elif role == "defender":
        template = DEFENDER_SYSTEM_TEMPLATE
    else:
        raise ValueError(f"role must be 'offender' or 'defender', got {role!r}")

    if not isinstance(word_limit, int) or isinstance(word_limit, bool) or word_limit < 1:
        raise ValueError(f"word_limit must be a positive int, got {word_limit!r}")

    clean_topic = sanitize_topic(topic)
    return template.format(topic=clean_topic, word_limit=word_limit)
