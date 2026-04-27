"""Phase-4 manual smoke: ensure_model_available + 1 streamed chat against real Ollama."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_settings  # noqa: E402
from llm import OllamaClient  # noqa: E402

settings = load_settings()
print(f"settings: {settings}")

client = OllamaClient(settings)
client.ensure_model_available()
print(f"OK — '{settings.model_name}' is available.")

print("\nStreaming a 1-turn chat (say hi):")
buf: list[str] = []
for tok in client.stream_chat(
    [
        {"role": "system", "content": "Reply in one short sentence."},
        {"role": "user", "content": "Say hi."},
    ],
):
    sys.stdout.write(tok)
    sys.stdout.flush()
    buf.append(tok)
print()
print(f"\n[smoke] received {sum(len(t) for t in buf)} chars in {len(buf)} chunks.")
