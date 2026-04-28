"""
tests/test_smoke.py — Phase-1 import smoke test.

Guarantees the empty scaffolding is at least syntactically valid Python
and that every top-level module imports cleanly. See ROADMAP.md Step 1.3.
"""

from __future__ import annotations


def test_imports() -> None:
    from auto_debate import config, engine, llm, prompts

    assert config is not None
    assert engine is not None
    assert llm is not None
    assert prompts is not None
