"""
tests/test_llm.py — Tests for the Ollama wrapper.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.
"""

# TODO(phase-4): patch ollama.Client and assert that
#   ensure_model_available raises ModelNotFoundError when list is empty.
# TODO(phase-4): assert that stream_chat yields the right strings from
#   a fake stream.
# TODO(phase-4): assert that a connection-refused error is wrapped in
#   OllamaUnavailableError.
