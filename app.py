"""
app.py — Streamlit UI for the Auto Debate two-agent app.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.

Phase 1: this module exists but does nothing — running
``streamlit run app.py`` should produce a blank page without crashing.
"""

# TODO(phase-6): st.set_page_config(...) + title + subtitle.
# TODO(phase-6): sidebar — model selector, max turns, temperature,
#   "Check Ollama" status badge.
# TODO(phase-6): session-state init (messages, running, stop_flag,
#   engine, topic).
# TODO(phase-6): topic input + Start / Stop buttons (mutually disabled).
# TODO(phase-6): replay loop rendering st.session_state.messages.
# TODO(phase-6): live streaming loop wiring DebateEngine → st.empty()
#   placeholders with cursor effect; check stop_flag between tokens.
# TODO(phase-6): error UI for OllamaUnavailableError / ModelNotFoundError
#   showing exact remediation commands.
# TODO(phase-8): "Download transcript (.md)" button via engine.to_markdown().
