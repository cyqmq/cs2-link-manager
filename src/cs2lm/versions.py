"""Lightweight semantic version comparison (stdlib only).

The index-based update flow compares plugin versions across multiple
sources.  A small semver-like parser is used instead of pulling in a
third-party dependency: ``x.y.z`` numeric parts plus optional prerelease
suffixes (``-alpha``/``-beta``/``-rc``) and build metadata (``+...``).

Rules:

* numeric parts compare numerically (``1.10.0 > 1.9.0``);
* missing parts compare as ``0`` (``1.2 == 1.2.0``);
* a release beats a prerelease when all numeric parts are equal
  (``1.0.0 > 1.0.0-beta``);
* prerelease strings compare lexicographically (``alpha < beta``);
* build metadata is ignored.
"""
from __future__ import annotations


def parse_version(value: str) -> tuple:
    """Parse ``value`` into a comparable tuple.

    Returns a tuple of ``(major, minor, patch, ...)`` where each part is
    ``(int_part, release_rank, pre_text)`` — ``release_rank`` is ``1`` for a
    plain release part and ``0`` for the part that carries a prerelease
    suffix (so ``1.0.0 > 1.0.0-beta``).
    """
    text = str(value).strip()
    if "+" in text:  # drop build metadata
        text = text.split("+", 1)[0]
    core = text
    pre = ""
    if "-" in text:  # everything after the first '-' is prerelease text
        core, pre = text.split("-", 1)
    parts: list[tuple[int, int, str]] = []
    for chunk in core.split("."):
        parts.append((int(chunk) if chunk.isdigit() else 0, 1, ""))
    if not parts:
        parts.append((0, 1, ""))
    if pre:
        last_num = parts[-1][0]
        parts[-1] = (last_num, 0, pre)
    return tuple(parts)


def _padded(a: tuple, b: tuple) -> tuple[tuple, tuple]:
    """Pad two parsed versions with zero release parts so they compare evenly."""
    width = max(len(a), len(b))
    pad = ((0, 1, ""),)
    return a + pad * (width - len(a)), b + pad * (width - len(b))


def version_gt(a: str, b: str) -> bool:
    aa, bb = _padded(parse_version(a), parse_version(b))
    return aa > bb


def version_lt(a: str, b: str) -> bool:
    aa, bb = _padded(parse_version(a), parse_version(b))
    return aa < bb


def version_eq(a: str, b: str) -> bool:
    aa, bb = _padded(parse_version(a), parse_version(b))
    return aa == bb


def version_gte(a: str, b: str) -> bool:
    return version_gt(a, b) or version_eq(a, b)


def version_lte(a: str, b: str) -> bool:
    return version_lt(a, b) or version_eq(a, b)


def version_satisfies(version: str, requirement: str) -> bool:
    """Check ``version`` against a simple requirement string.

    Supports bare versions (``1.2.3``), operators (``>=1.2.0``, ``>1.2``,
    ``<=1.3``, ``<1.3.0``, ``=1.2.3``) and inclusive ranges
    (``1.0.0 - 2.0.0``).  Multiple constraints joined by spaces or commas
    must all be satisfied.
    """
    req = requirement.strip()
    if not req:
        return True
    if " - " in req:
        low, high = (part.strip() for part in req.split(" - ", 1))
        return version_gte(version, low) and version_lte(version, high)
    if "," in req:
        return all(version_satisfies(version, r.strip()) for r in req.split(",") if r.strip())
    if " " in req:
        return all(version_satisfies(version, r) for r in req.split() if r.strip())
    for op in (">=", "<=", ">", "<", "="):
        if req.startswith(op):
            target = req[len(op):].strip()
            if op == ">=":
                return version_gte(version, target)
            if op == "<=":
                return version_lte(version, target)
            if op == ">":
                return version_gt(version, target)
            if op == "<":
                return version_lt(version, target)
            return version_eq(version, target)
    return version_eq(version, req)