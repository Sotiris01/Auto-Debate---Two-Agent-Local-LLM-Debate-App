"""
prompts.py — Centralized system-prompt templates and builders.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.
"""

# TODO(phase-3): define `OFFENDER_SYSTEM_TEMPLATE` and
#   `DEFENDER_SYSTEM_TEMPLATE` with `{topic}` and `{word_limit}` placeholders
#   (exact strings from PROJECT.md §6).
# TODO(phase-3): define `OPENING_USER_MESSAGE` constant used to seed turn 1.
# TODO(phase-3): implement `build_system_prompt(role, topic, word_limit)`
#   that sanitizes the topic (strip, collapse whitespace, max 300 chars,
#   reject empty) and formats the right template.
