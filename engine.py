"""
engine.py — Pure debate orchestration. Knows nothing about Streamlit.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.
Drivable from a plain Python script (see scripts/dry_run.py in Phase 5).
"""

# TODO(phase-5): define `DebateTurn` dataclass with
#   speaker: Literal["offender", "defender"], content: str, index: int.
# TODO(phase-5): implement `DebateEngine(settings, llm_client, topic)`
#   that builds `_offender_msgs` / `_defender_msgs` system histories and
#   seeds the offender with `OPENING_USER_MESSAGE`.
# TODO(phase-5): implement `run_one_turn(speaker) -> Iterator[str]` that
#   streams tokens and on completion mirrors the assistant turn into the
#   opponent history (alternating-role trick).
# TODO(phase-5): implement `run(stop_check) -> Iterator[Tuple[str, str]]`
#   top-level loop honoring max_turns and the cooperative stop callback.
# TODO(phase-5): add `transcript()` and `to_markdown()` helpers (the
#   latter is consumed by the Phase 8 download button).
