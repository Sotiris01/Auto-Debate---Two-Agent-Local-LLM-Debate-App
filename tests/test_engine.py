"""
tests/test_engine.py — Tests for the debate engine orchestration.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.
"""

# TODO(phase-5): with a mocked llm_client yielding fixed tokens, assert
#   that after one turn the offender history has 2 messages and the
#   defender history has 2 (system + user-mirror).
# TODO(phase-5): test that a stop callback returning True halts within
#   one token.
# TODO(phase-5): test that roles always alternate across run().
