"""
prompts.registry — JSON-backed loader for role / persona / behavior fragments.

Part of the Auto Debate project. See PROJECT.md and ROADMAP.md.

Phase 9: fragments live as small JSON files under
``prompts/library/{roles,personas,behaviors}/<name>.json`` so adding a new
persona or behavior is a no-code change. The two built-in fragments
``offender`` / ``defender`` (roles), ``neutral`` (persona) and ``standard``
(behavior) are also shipped as JSON for symmetry — at startup they are
validated to match the in-code constants exactly so a typo in a JSON file
cannot drift the v0.1.0 regression-locked output.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, get_args

from .fragments import (
    DEFAULT_BEHAVIOR_NAME,
    DEFAULT_PERSONA_NAME,
    DEFENDER_ROLE,
    NEUTRAL_PERSONA,
    OFFENDER_ROLE,
    STANDARD_BEHAVIOR,
    BehaviorFragment,
    FragmentKind,
    PersonaFragment,
    Role,
    RoleFragment,
)

__all__ = [
    "FragmentNotFoundError",
    "InvalidFragmentError",
    "default_library_root",
    "list_fragments",
    "load_behavior",
    "load_fragment",
    "load_persona",
    "load_role",
]

_VALID_KINDS: Final[tuple[str, ...]] = get_args(FragmentKind)


class FragmentNotFoundError(LookupError):
    """Raised when ``load_fragment`` cannot find the requested file."""


class InvalidFragmentError(ValueError):
    """Raised when a fragment JSON file fails schema validation."""


def default_library_root() -> Path:
    """Filesystem path to the bundled ``library/`` directory."""
    return Path(__file__).resolve().parent / "library"


def _kind_dir(root: Path, kind: FragmentKind) -> Path:
    return root / kind


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FragmentNotFoundError(str(path)) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidFragmentError(f"{path}: invalid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise InvalidFragmentError(f"{path}: top-level value must be a JSON object")
    return data


def _require_str(data: dict[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise InvalidFragmentError(
            f"{path}: field {key!r} must be a non-empty string",
        )
    return value


def _opt_str_tuple(data: dict[str, Any], key: str, path: Path) -> tuple[str, ...]:
    value = data.get(key, [])
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise InvalidFragmentError(
            f"{path}: field {key!r} must be a list of strings",
        )
    return tuple(value)


def _parse_role(data: dict[str, Any], path: Path) -> RoleFragment:
    name = _require_str(data, "name", path)
    role = _require_str(data, "role", path)
    if role not in ("offender", "defender"):
        raise InvalidFragmentError(
            f"{path}: field 'role' must be 'offender' or 'defender', got {role!r}",
        )
    system_text = _require_str(data, "system_text", path)
    return RoleFragment(name=name, role=role, system_text=system_text)  # type: ignore[arg-type]


def _parse_persona(data: dict[str, Any], path: Path) -> PersonaFragment:
    return PersonaFragment(
        name=_require_str(data, "name", path),
        tone=str(data.get("tone", "")),
        signature_phrases=_opt_str_tuple(data, "signature_phrases", path),
        extra_directives=_opt_str_tuple(data, "extra_directives", path),
    )


def _parse_behavior(data: dict[str, Any], path: Path) -> BehaviorFragment:
    return BehaviorFragment(
        name=_require_str(data, "name", path),
        directives=_opt_str_tuple(data, "directives", path),
    )


def list_fragments(
    kind: FragmentKind,
    *,
    library_root: Path | None = None,
) -> list[str]:
    """Return the sorted list of fragment names available under ``kind``."""
    if kind not in _VALID_KINDS:
        raise ValueError(f"kind must be one of {_VALID_KINDS}, got {kind!r}")
    root = library_root or default_library_root()
    target = _kind_dir(root, kind)
    if not target.exists():
        return []
    return sorted(p.stem for p in target.glob("*.json"))


def load_fragment(
    kind: FragmentKind,
    name: str,
    *,
    library_root: Path | None = None,
) -> RoleFragment | PersonaFragment | BehaviorFragment:
    """Load a single fragment by ``kind`` and ``name``.

    Raises:
        ValueError: when ``kind`` is not one of the supported kinds.
        FragmentNotFoundError: when no JSON file exists for ``name``.
        InvalidFragmentError: when the JSON fails schema validation.
    """
    if kind not in _VALID_KINDS:
        raise ValueError(f"kind must be one of {_VALID_KINDS}, got {kind!r}")
    if not name or "/" in name or "\\" in name:
        raise ValueError(f"fragment name must be a non-empty bare identifier, got {name!r}")
    root = library_root or default_library_root()
    path = _kind_dir(root, kind) / f"{name}.json"
    data = _read_json(path)
    if kind == "roles":
        return _parse_role(data, path)
    if kind == "personas":
        return _parse_persona(data, path)
    return _parse_behavior(data, path)


# --- typed convenience wrappers --------------------------------------------


def load_role(role: Role, *, library_root: Path | None = None) -> RoleFragment:
    """Load the role fragment for ``"offender"`` or ``"defender"``.

    Falls back to the in-code default when no JSON file is present so the
    package keeps working in stripped-down deployments where the
    ``library/`` directory is missing.
    """
    try:
        fragment = load_fragment("roles", role, library_root=library_root)
    except FragmentNotFoundError:
        return OFFENDER_ROLE if role == "offender" else DEFENDER_ROLE
    assert isinstance(fragment, RoleFragment)
    return fragment


def load_persona(name: str, *, library_root: Path | None = None) -> PersonaFragment:
    """Load a persona fragment by name; falls back to NEUTRAL on missing default."""
    try:
        fragment = load_fragment("personas", name, library_root=library_root)
    except FragmentNotFoundError:
        if name == DEFAULT_PERSONA_NAME:
            return NEUTRAL_PERSONA
        raise
    assert isinstance(fragment, PersonaFragment)
    return fragment


def load_behavior(name: str, *, library_root: Path | None = None) -> BehaviorFragment:
    """Load a behavior fragment by name; falls back to STANDARD on missing default."""
    try:
        fragment = load_fragment("behaviors", name, library_root=library_root)
    except FragmentNotFoundError:
        if name == DEFAULT_BEHAVIOR_NAME:
            return STANDARD_BEHAVIOR
        raise
    assert isinstance(fragment, BehaviorFragment)
    return fragment


@lru_cache(maxsize=1)
def _cached_library_root() -> Path:
    return default_library_root()
