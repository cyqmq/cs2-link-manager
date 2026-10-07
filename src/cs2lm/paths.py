"""Path helpers and validation.

All "target" paths stored in manifests are relative to the server root.
This module guarantees that resolved paths never escape the server directory.

Note: we use ``os.path.abspath`` (which normalizes ``..`` but does *not*
follow symlinks) so that legitimate symlinks pointing from the server into the
repository are not mistaken for path escapes.
"""
from __future__ import annotations

import os
from pathlib import Path


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        Path(os.path.abspath(path)).relative_to(Path(os.path.abspath(parent)))
        return True
    except ValueError:
        return False


def resolve_within(root: str | Path, rel: str | Path) -> Path:
    """Resolve a server-relative path inside ``root``; raise if it escapes."""
    root_abs = os.path.abspath(root)
    candidate = os.path.abspath(os.path.join(root_abs, rel))
    try:
        Path(candidate).relative_to(Path(root_abs))
    except ValueError as exc:
        raise ValueError(f"Path escapes server root: {rel}") from exc
    return Path(candidate)


def safe_rel(path: str | Path) -> str:
    """Return a normalized relative posix path, rejecting absolute/unsafe paths."""
    p = Path(path)
    if os.path.isabs(p):
        raise ValueError(f"Expected relative path, got absolute: {p}")
    if any(part in ("..", "~") for part in p.parts):
        raise ValueError(f"Path contains unsafe component: {p}")
    return p.as_posix()


def find_csgo_rel(server_path: str | Path) -> str:
    """Detect the csgo directory relative to the server root.

    Returns e.g. ``game/csgo``. Prefers existing directories, falls back to the
    standard layout when the server is not yet populated.
    """
    server = Path(server_path)
    candidates = [
        ("game/csgo", server / "game" / "csgo"),
        ("csgo", server / "csgo"),
    ]
    for rel, cand in candidates:
        if cand.is_dir():
            return rel
    return "game/csgo"