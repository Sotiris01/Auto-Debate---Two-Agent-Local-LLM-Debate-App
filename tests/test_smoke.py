"""
tests/test_smoke.py — Phase-1 import smoke test.

Guarantees the empty scaffolding is at least syntactically valid Python
and that every top-level module imports cleanly. See ROADMAP.md Step 1.3.
"""

from __future__ import annotations


def test_imports() -> None:
    import config  # noqa: F401
    import engine  # noqa: F401
    import llm  # noqa: F401
    import prompts  # noqa: F401

    assert True
