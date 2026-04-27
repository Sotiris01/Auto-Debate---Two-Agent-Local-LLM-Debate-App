"""
tests/test_config.py — Tests for the typed configuration loader.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.
"""

# TODO(phase-2): test that load_settings() returns defaults when env is empty.
# TODO(phase-2): test that env vars override defaults (each field).
# TODO(phase-2): test that ConfigError is raised for each invalid field
#   (max_turns < 1, temperature out of range, top_p out of range,
#   word_limit < 30, ollama_host missing http scheme).
