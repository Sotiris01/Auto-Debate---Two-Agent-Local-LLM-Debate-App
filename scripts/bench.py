"""scripts/bench.py — Phase 7.5 performance sanity.

Runs one debate turn against the configured model, measures wall time and
token throughput, and verifies that the ``num_predict`` cap (derived from
``word_limit``) clips runaway generations. Intended as a manual benchmark,
not part of pytest.

Usage:
    python scripts/bench.py
    python scripts/bench.py --topic "Pineapple belongs on pizza" --turns 4
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auto_debate.config import configure_logging, load_settings
from auto_debate.engine import DebateEngine
from auto_debate.llm import OllamaClient, chat_options


def bench_single_turn(topic: str) -> None:
    settings = load_settings()
    client = OllamaClient(settings)
    eng = DebateEngine(settings=settings, llm_client=client, topic=topic)

    print(f"model: {settings.model_name}")
    print(f"word_limit: {settings.word_limit}")

    opts = chat_options(settings)
    print(f"num_predict cap: {opts['num_predict']}  (= word_limit * 2)")

    print("\n--- streaming first turn ---")
    t0 = time.perf_counter()
    tokens = 0
    chars = 0
    for tok in eng.run_one_turn("offender"):
        tokens += 1
        chars += len(tok)
    elapsed = time.perf_counter() - t0

    last = eng.transcript()[-1]
    words = len(last.content.split())
    print(
        f"\nturn 1 ({last.speaker}): {tokens} chunks, {chars} chars, {words} words, {elapsed:.2f}s"
    )
    if elapsed > 0:
        print(
            f"throughput: {tokens / elapsed:.1f} chunks/s, "
            f"{chars / elapsed:.0f} chars/s, "
            f"~{words / elapsed:.1f} words/s"
        )
    cap_ok = words <= settings.word_limit + 30  # soft cap (model may overshoot a bit)
    print(
        f"num_predict cap respected: {cap_ok}  "
        f"(words={words}, soft-limit={settings.word_limit + 30})"
    )


def bench_full_debate(topic: str, max_turns: int) -> None:
    settings = load_settings()
    settings = replace(settings, max_turns=max_turns)
    client = OllamaClient(settings)
    eng = DebateEngine(settings=settings, llm_client=client, topic=topic)

    t0 = time.perf_counter()
    chars = 0
    tokens = 0
    for _speaker, tok in eng.run():
        tokens += 1
        chars += len(tok)
    elapsed = time.perf_counter() - t0

    total_words = sum(len(t.content.split()) for t in eng.transcript())
    print(f"\n--- full debate, {len(eng.transcript())} turns ---")
    print(f"total: {tokens} chunks, {chars} chars, {total_words} words, {elapsed:.2f}s")
    if elapsed > 0:
        print(f"throughput: ~{total_words / elapsed:.1f} words/s ({chars / elapsed:.0f} chars/s)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Auto Debate perf sanity.")
    parser.add_argument(
        "--topic",
        default="Remote work is better than office work for most knowledge workers.",
        help="Debate topic (defaults to a generic prompt).",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=0,
        help="If > 0, run a full debate of this length after the single-turn bench.",
    )
    args = parser.parse_args(argv)

    configure_logging()

    bench_single_turn(args.topic)
    if args.turns > 0:
        bench_full_debate(args.topic, args.turns)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
