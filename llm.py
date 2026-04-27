"""
llm.py — Thin, mockable wrapper around the Ollama Python client.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.
No business logic lives here — only transport + error translation.
"""

# TODO(phase-4): define `OllamaClient` wrapping `ollama.Client(host=...)`
#   constructed from `Settings`.
# TODO(phase-4): implement `ensure_model_available(model_name)` that calls
#   `client.list()` and raises `ModelNotFoundError(model_name)` with the
#   exact `ollama pull` command in the message. Never auto-pull.
# TODO(phase-4): implement `stream_chat(messages, *, options) -> Iterator[str]`
#   yielding chunk["message"]["content"] only; wrap connection errors in
#   `OllamaUnavailableError`.
# TODO(phase-4): implement `chat_options(settings) -> dict` returning
#   {"temperature", "top_p", "num_predict"} (num_predict derived from
#   word_limit).
