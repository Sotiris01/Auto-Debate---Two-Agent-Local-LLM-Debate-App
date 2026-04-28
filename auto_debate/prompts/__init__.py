"""
prompts — Composable prompt architecture for Auto Debate.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.

Phase 9 turns the original flat ``prompts.py`` module into a package with
three swappable fragment kinds (role / persona / behavior) and a single
``PromptComposer`` assembly point. The legacy ``build_system_prompt``
helper still exists as a thin shim over the composer with the default
``NEUTRAL`` persona and ``STANDARD`` behavior so output is byte-identical
to v0.1.0 — every existing test, every external script (dry_run, bench),
and the engine itself keep working unchanged.

Public API exported here:
    * Legacy (v0.1.0) — ``build_system_prompt``, ``sanitize_topic``,
      ``OFFENDER_SYSTEM_TEMPLATE``, ``DEFENDER_SYSTEM_TEMPLATE``,
      ``OPENING_USER_MESSAGE``, ``MAX_TOPIC_LENGTH``, ``Role``.
    * New (Phase 9) — ``PromptComposer``, ``PromptCompositionError``,
      ``RoleFragment``, ``PersonaFragment``, ``BehaviorFragment``,
      ``load_fragment``, ``list_fragments``, ``load_role``,
      ``load_persona``, ``load_behavior``,
      ``DEFAULT_PERSONA_NAME``, ``DEFAULT_BEHAVIOR_NAME``,
      ``OFFENDER_ROLE``, ``DEFENDER_ROLE``, ``NEUTRAL_PERSONA``,
      ``STANDARD_BEHAVIOR``.
"""

from __future__ import annotations

from typing import Final

from .composer import (
    MAX_TOPIC_LENGTH,
    OPENING_USER_MESSAGE,
    PromptComposer,
    PromptCompositionError,
    Role,
    sanitize_topic,
)
from .fragments import (
    CLOSING_BEHAVIOR,
    DEFAULT_BEHAVIOR_NAME,
    DEFAULT_PERSONA_NAME,
    DEFENDER_ROLE,
    NEUTRAL_PERSONA,
    OFFENDER_ROLE,
    STANDARD_BEHAVIOR,
    BehaviorFragment,
    FragmentKind,
    PersonaFragment,
    RoleFragment,
)
from .presets import (
    BUILTIN_PRESETS,
    AgentPreset,
    DebatePreset,
    check_compatibility,
    list_presets,
    preset_by_name,
)
from .registry import (
    FragmentNotFoundError,
    InvalidFragmentError,
    default_library_root,
    list_fragments,
    load_behavior,
    load_fragment,
    load_persona,
    load_role,
)

__all__ = [
    "BUILTIN_PRESETS",
    "CLOSING_BEHAVIOR",
    "DEFAULT_BEHAVIOR_NAME",
    "DEFAULT_PERSONA_NAME",
    "DEFENDER_ROLE",
    "DEFENDER_SYSTEM_TEMPLATE",
    "MAX_TOPIC_LENGTH",
    "NEUTRAL_PERSONA",
    "OFFENDER_ROLE",
    "OFFENDER_SYSTEM_TEMPLATE",
    "OPENING_USER_MESSAGE",
    "STANDARD_BEHAVIOR",
    "AgentPreset",
    "BehaviorFragment",
    "DebatePreset",
    "FragmentKind",
    "FragmentNotFoundError",
    "InvalidFragmentError",
    "PersonaFragment",
    "PromptComposer",
    "PromptCompositionError",
    "Role",
    "RoleFragment",
    "build_system_prompt",
    "check_compatibility",
    "default_library_root",
    "list_fragments",
    "list_presets",
    "load_behavior",
    "load_fragment",
    "load_persona",
    "load_role",
    "preset_by_name",
    "sanitize_topic",
]


# --- legacy template constants ---------------------------------------------
#
# Re-exported as plain strings (not RoleFragment) for backwards compat with
# tests that do ``from prompts import OFFENDER_SYSTEM_TEMPLATE``. They are
# the .system_text of the default role fragments.

OFFENDER_SYSTEM_TEMPLATE: Final[str] = OFFENDER_ROLE.system_text
DEFENDER_SYSTEM_TEMPLATE: Final[str] = DEFENDER_ROLE.system_text


# --- legacy v0.1.0 builder shim --------------------------------------------


def build_system_prompt(role: Role, topic: str, word_limit: int) -> str:
    """Build the system prompt for ``role`` on ``topic`` (legacy v0.1.0 API).

    Thin wrapper around :class:`PromptComposer` with the default
    ``NEUTRAL`` persona and ``STANDARD`` behavior. By construction the
    output is byte-identical to the original v0.1.0 builder so the entire
    Phase-3 test suite, all snapshot tests, and the engine's internal
    history continue to work unchanged.

    Raises:
        ValueError: when ``role`` is unknown, ``topic`` is empty, or
            ``word_limit`` is not a positive integer.
    """
    if role == "offender":
        role_fragment = OFFENDER_ROLE
    elif role == "defender":
        role_fragment = DEFENDER_ROLE
    else:
        raise ValueError(f"role must be 'offender' or 'defender', got {role!r}")

    try:
        composer = PromptComposer(word_limit=word_limit)
    except PromptCompositionError as exc:
        # Preserve the v0.1.0 error type so external callers that catch
        # ValueError keep working.
        raise ValueError(str(exc)) from exc

    return composer.compose(role=role_fragment, topic=topic)
