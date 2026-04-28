"""
scripts/dry_run.py — Run a full debate from the command line, no Streamlit.

Phase 5 exit-criterion harness. Invoke with:

    python -m scripts.dry_run "AI is dangerous"

Reads :func:`config.load_settings` for model + Ollama host, verifies the
model is present, and streams every token of every turn straight to stdout
prefixed with the speaker. This proves the engine is wired correctly without
touching the UI layer.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python scripts/dry_run.py "..."` (no -m) to also work.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auto_debate.config import load_settings
from auto_debate.engine import DebateEngine
from auto_debate.llm import ModelNotFoundError, OllamaClient, OllamaUnavailableError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an Auto Debate from the CLI.")
    parser.add_argument("topic", help="Debate topic (1-300 chars).")
    parser.add_argument("--max-turns", type=int, default=None, help="Override max_turns.")
    args = parser.parse_args(argv)

    settings = load_settings()
    if args.max_turns is not None:
        # Frozen dataclass; rebuild with override.
        from dataclasses import replace

        settings = replace(settings, max_turns=args.max_turns)

    client = OllamaClient(settings)
    try:
        client.ensure_model_available()
    except (OllamaUnavailableError, ModelNotFoundError) as exc:
        print(f"[dry_run] {exc}", file=sys.stderr)
        return 2

    engine = DebateEngine(settings, client, args.topic)
    print(f"[dry_run] topic: {args.topic}")
    print(f"[dry_run] model: {settings.model_name}  max_turns: {settings.max_turns}\n")

    current: str | None = None
    for speaker, token in engine.run():
        if speaker != current:
            if current is not None:
                sys.stdout.write("\n\n")
            label = "OFFENDER" if speaker == "offender" else "DEFENDER"
            sys.stdout.write(f"--- {label} ---\n")
            current = speaker
        sys.stdout.write(token)
        sys.stdout.flush()
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
