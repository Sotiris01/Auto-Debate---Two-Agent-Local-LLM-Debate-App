"""
prompts.fragments — Typed dataclasses for the three composable prompt layers.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.

Phase 9: a system prompt is assembled from three swappable fragments —
``RoleFragment`` (offender / defender), ``PersonaFragment`` (tone, voice,
signature phrases), ``BehaviorFragment`` (procedural directives like
"cite evidence" or "steelman first"). Default ``NEUTRAL`` / ``STANDARD``
fragments have empty directive lists so their composition reproduces the
v0.1.0 output byte-for-byte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final, Literal

__all__ = [
    "DEFAULT_BEHAVIOR_NAME",
    "DEFAULT_PERSONA_NAME",
    "DEFENDER_ROLE",
    "NEUTRAL_PERSONA",
    "OFFENDER_ROLE",
    "STANDARD_BEHAVIOR",
    "BehaviorFragment",
    "FragmentKind",
    "PersonaFragment",
    "RoleFragment",
    "extract_placeholders",
]

FragmentKind = Literal["roles", "personas", "behaviors"]
Role = Literal["offender", "defender"]

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

DEFAULT_PERSONA_NAME: Final[str] = "neutral"
DEFAULT_BEHAVIOR_NAME: Final[str] = "standard"


def extract_placeholders(text: str) -> set[str]:
    """Return the set of ``{name}`` placeholders found in ``text``."""
    return set(_PLACEHOLDER_RE.findall(text))


@dataclass(frozen=True)
class RoleFragment:
    """A debate-side fragment carrying the system text and its placeholders."""

    name: str
    role: Role
    system_text: str
    placeholders: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.role not in ("offender", "defender"):
            raise ValueError(
                f"role must be 'offender' or 'defender', got {self.role!r}",
            )
        # Auto-derive placeholders if not supplied.
        if not self.placeholders:
            object.__setattr__(
                self,
                "placeholders",
                frozenset(extract_placeholders(self.system_text)),
            )


@dataclass(frozen=True)
class PersonaFragment:
    """A voice / tone overlay applied on top of a role."""

    name: str
    tone: str = ""
    signature_phrases: tuple[str, ...] = ()
    extra_directives: tuple[str, ...] = ()


@dataclass(frozen=True)
class BehaviorFragment:
    """A procedural-rule overlay applied on top of role + persona."""

    name: str
    directives: tuple[str, ...] = ()


# --- v0.1.0 verbatim defaults ----------------------------------------------
#
# The two role templates below are byte-identical to the original
# OFFENDER_SYSTEM_TEMPLATE / DEFENDER_SYSTEM_TEMPLATE from prompts.py
# (Phase 3). The default NEUTRAL persona and STANDARD behavior carry no
# directives, so PromptComposer with these defaults produces byte-identical
# output to v0.1.0's build_system_prompt(). Regression-locked by
# tests/test_prompt_composer.py::test_default_composition_matches_v0_1_0.

_OFFENDER_SYSTEM_TEXT: Final[str] = (
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

_DEFENDER_SYSTEM_TEXT: Final[str] = (
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

OFFENDER_ROLE: Final[RoleFragment] = RoleFragment(
    name="offender",
    role="offender",
    system_text=_OFFENDER_SYSTEM_TEXT,
)

DEFENDER_ROLE: Final[RoleFragment] = RoleFragment(
    name="defender",
    role="defender",
    system_text=_DEFENDER_SYSTEM_TEXT,
)

NEUTRAL_PERSONA: Final[PersonaFragment] = PersonaFragment(
    name=DEFAULT_PERSONA_NAME,
    tone="neutral",
    signature_phrases=(),
    extra_directives=(),
)

STANDARD_BEHAVIOR: Final[BehaviorFragment] = BehaviorFragment(
    name=DEFAULT_BEHAVIOR_NAME,
    directives=(),
)
