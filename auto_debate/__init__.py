"""Auto Debate package.

Top-level package introduced in Phase 16 (Repository Layout Refactor).

Until Phase 16, every source module lived at the repository root
(``config.py``, ``engine.py`` …). They are now grouped under this
package without behavioural changes; sub-packages such as
:mod:`auto_debate.research` are split into their own modules to make
room for the v0.3 research rework (Phases 17-21).
"""

from __future__ import annotations

__all__: list[str] = []
