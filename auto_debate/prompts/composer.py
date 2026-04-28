"""
prompts.composer — Single assembly point for system prompts.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.

Phase 9: every later phase (memory, web research, judge agent, persona
library) plugs into ``PromptComposer.compose`` instead of growing string
templates. Composition order is fixed:

    role.system_text  (with {topic} / {word_limit} filled)
    + persona block   (only if persona has non-empty directives)
    + behavior block  (only if behavior has non-empty directives)
    + <MEMORY> block  (only if a non-empty memory string is supplied)

When persona == NEUTRAL_PERSONA and behavior == STANDARD_BEHAVIOR and no
memory is supplied, the output is byte-identical to the v0.1.0
``build_system_prompt`` so existing snapshot/regression tests keep passing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

from .fragments import (
    STANDARD_BEHAVIOR,
    BehaviorFragment,
    PersonaFragment,
    RoleFragment,
    extract_placeholders,
)

__all__ = [
    "MAX_TOPIC_LENGTH",
    "OPENING_USER_MESSAGE",
    "PromptComposer",
    "PromptCompositionError",
    "Role",
    "sanitize_topic",
]

Role = Literal["offender", "defender"]

MAX_TOPIC_LENGTH: Final[int] = 300

OPENING_USER_MESSAGE: Final[str] = "Open the debate with your first argument."

_WHITESPACE_RE = re.compile(r"\s+")


class PromptCompositionError(ValueError):
    """Raised when composer inputs cannot be assembled into a valid prompt."""


def sanitize_topic(topic: str) -> str:
    """Strip, collapse whitespace, and truncate the user-supplied topic.

    Identical contract to the v0.1.0 helper of the same name.

    Raises:
        TypeError: when ``topic`` is not a ``str``.
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


def _render_persona_block(persona: PersonaFragment) -> str | None:
    if not persona.extra_directives:
        return None
    body = "\n".join(f"- {line}" for line in persona.extra_directives)
    return f"# Persona: {persona.name}\n{body}"


def _render_behavior_block(behavior: BehaviorFragment) -> str | None:
    if not behavior.directives:
        return None
    body = "\n".join(f"- {line}" for line in behavior.directives)
    return f"# Behavior: {behavior.name}\n{body}"


def _render_memory_block(memory: str | None) -> str | None:
    if memory is None:
        return None
    stripped = memory.strip()
    if not stripped:
        return None
    return f"<MEMORY>\n{stripped}\n</MEMORY>"


@dataclass(frozen=True)
class PromptComposer:
    """Assembles system prompts from role + persona + behavior fragments.

    The composer is intentionally a thin orchestration object — it owns no
    fragment registry, holds no state, and never touches the network or
    the filesystem. ``compose`` is a pure function of its inputs so unit
    tests can pin its output deterministically.
    """

    word_limit: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.word_limit, int)
            or isinstance(self.word_limit, bool)
            or self.word_limit < 1
        ):
            raise PromptCompositionError(
                f"word_limit must be a positive int, got {self.word_limit!r}",
            )

    def compose(
        self,
        *,
        role: RoleFragment,
        topic: str,
        persona: PersonaFragment | None = None,
        behavior: BehaviorFragment | None = None,
        memory: str | None = None,
    ) -> str:
        """Build the final system prompt for a single agent.

        Raises:
            PromptCompositionError: when ``role.system_text`` references a
                placeholder that the composer cannot fill, or when the
                topic / word_limit fail validation.
        """
        if persona is None:
            from .fragments import NEUTRAL_PERSONA

            persona = NEUTRAL_PERSONA
        if behavior is None:
            behavior = STANDARD_BEHAVIOR

        clean_topic = sanitize_topic(topic)

        substitutions = {"topic": clean_topic, "word_limit": self.word_limit}

        # The composer fills exactly two placeholders. Anything else is a
        # registry / fragment-author bug; surface it loudly rather than
        # silently leaving raw `{foo}` literals in the prompt.
        unknown = role.placeholders - substitutions.keys()
        if unknown:
            raise PromptCompositionError(
                f"role fragment {role.name!r} references unknown placeholders: {sorted(unknown)}",
            )

        try:
            head = role.system_text.format(**substitutions)
        except KeyError as exc:
            # Defensive: extract_placeholders should have caught this at
            # __post_init__, but a hand-built RoleFragment could bypass it.
            raise PromptCompositionError(
                f"role fragment {role.name!r} missing placeholder {exc.args[0]!r}",
            ) from exc

        # Reject any remaining unfilled placeholders that survived format()
        # (e.g. literal '{}' fragments in the source text).
        if extract_placeholders(head):
            raise PromptCompositionError(
                f"role fragment {role.name!r} has unfilled placeholders after format",
            )

        parts: list[str] = [head]
        for block in (
            _render_persona_block(persona),
            _render_behavior_block(behavior),
            _render_memory_block(memory),
        ):
            if block is not None:
                parts.append(block)

        return "\n\n".join(parts)
