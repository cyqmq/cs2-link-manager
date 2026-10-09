"""Supported plugin frameworks and server-side detection.

The manager can host plugins for several CS2 frameworks. Each framework is
identified by a canonical id (with aliases) and maps to a directory under
the server's ``<game>/addons`` tree.

Frameworks currently supported:

* ``metamod``  — Metamod:Source          -> ``addons/metamod``
* ``css``      — CounterStrikeSharp (CS#) -> ``addons/counterstrikesharp``
* ``swiftly``  — SwiftlyS2                -> ``addons/swiftly``
* ``plugify``  — Plugify                 -> ``addons/plugify``
* ``modsharp``  — ModSharp               -> ``addons/modsharp``

``plugin_type`` values in manifests / index.json accept the canonical id or any
alias (e.g. ``counterstrikesharp`` or ``cs#`` resolve to ``css``).
"""
from __future__ import annotations

import sys
from pathlib import Path

FRAMEWORKS: tuple[dict, ...] = (
    {
        "id": "css",
        "aliases": ("counterstrikesharp", "cs#", "css2"),
        "name": "CounterStrikeSharp (CS#)",
        "root": "counterstrikesharp",
        "plugin_rel": "plugins",
        "marker": "api/CounterStrikeSharp.API.dll",
    },
    {
        "id": "metamod",
        "aliases": ("metamod-source", "metamodsource", "mm"),
        "name": "Metamod:Source",
        "root": "metamod",
        "plugin_rel": None,
        "marker": None,
    },
    {
        "id": "swiftly",
        "aliases": ("swiftlys2", "swiftly-s2", "swiftly-s2"),
        "name": "SwiftlyS2",
        "root": "swiftly",
        "plugin_rel": "plugins",
        "marker": None,
    },
    {
        "id": "plugify",
        "aliases": ("plugify-s2", "plugifys2"),
        "name": "Plugify",
        "root": "plugify",
        "plugin_rel": "plugins",
        "marker": None,
    },
    {
        "id": "modsharp",
        "aliases": ("mod-sharp",),
        "name": "ModSharp",
        "root": "modsharp",
        "plugin_rel": "plugins",
        "marker": None,
    },
)

# Map an addons/ directory name to a canonical framework id.
ROOT_TO_ID: dict[str, str] = {fw["root"]: fw["id"] for fw in FRAMEWORKS}


def normalize_framework(value: str | None) -> str | None:
    """Resolve a plugin_type value (id or alias) to a canonical framework id."""
    if not value:
        return None
    v = str(value).strip().lower()
    for fw in FRAMEWORKS:
        if v == fw["id"] or v in fw["aliases"]:
            return fw["id"]
    return None


def framework_info(framework_id: str) -> dict | None:
    """Return the framework definition for an id/alias, or ``None``."""
    canonical = normalize_framework(framework_id)
    if canonical is None:
        return None
    return next(fw for fw in FRAMEWORKS if fw["id"] == canonical)


def framework_root(framework_id: str) -> str:
    """Return the addons/ directory name for a framework id."""
    info = framework_info(framework_id)
    if info is None:
        raise ValueError(f"Unsupported framework: {framework_id}")
    return info["root"]


def framework_ids() -> list[str]:
    """Canonical ids of every supported framework."""
    return [fw["id"] for fw in FRAMEWORKS]


def _framework_installed_at(root: Path, fw: dict) -> bool:
    """Return ``True`` when a framework is genuinely installed at ``root``.

    Frameworks with a ``marker`` require that file. Frameworks without one
    (plugify/swiftly/modsharp) require some framework-owned entry besides
    ``plugins``/``configs``, because a force-installed plugin creates only
    those two directories under the root (via its links); a real framework
    install always ships binaries/core files in the root.
    """
    if not root.is_dir():
        return False
    if fw["marker"]:
        return (root / fw["marker"]).exists()
    try:
        own_entries = [
            e.name for e in root.iterdir() if e.name not in ("plugins", "configs")
        ]
    except OSError:
        own_entries = []
    return bool(own_entries)


def detect_frameworks(
    server: str | Path,
    csgo_rel: str = "game/csgo",
) -> list[dict]:
    """Detect which frameworks are installed on the server.

    Scans ``<server>/<csgo_rel>/addons`` and returns one entry per known
    framework with ``id``, ``name`` and ``installed``. A framework is present
    when its root directory exists (plus its marker file when defined) — and
    for marker-less frameworks, when it contains framework-owned files beyond
    what plugin links create under ``plugins``/``configs``.
    """
    addons = Path(server) / csgo_rel / "addons"
    result: list[dict] = []
    for fw in FRAMEWORKS:
        root = addons / fw["root"]
        installed = _framework_installed_at(root, fw)
        result.append(
            {
                "id": fw["id"],
                "name": fw["name"],
                "root": fw["root"],
                "installed": installed,
            }
        )
    return result


def installed_framework_ids(
    server: str | Path,
    csgo_rel: str = "game/csgo",
) -> list[str]:
    """Ids of frameworks actually present on the server."""
    return [
        entry["id"]
        for entry in detect_frameworks(server, csgo_rel)
        if entry["installed"]
    ]


class FrameworkMissingError(Exception):
    """Raised when a plugin's framework is not installed on the server."""


def require_framework_present(
    server: str | Path,
    csgo_rel: str,
    plugin_type: str | None,
) -> None:
    """Raise :class:`FrameworkMissingError` if the plugin's framework is absent.

    Unknown ``plugin_type`` values are not blocked (they are not managed).
    """
    info = framework_info(plugin_type or "")
    if info is None:
        return
    addons = Path(server) / csgo_rel / "addons"
    root = addons / info["root"]
    if not _framework_installed_at(root, info):
        raise FrameworkMissingError(
            f"plugin requires {info['name']} but it is not installed on the "
            f"server (expected {root}). Install the framework first, or use "
            "--force to override."
        )


def current_platform() -> str:
    """Detect the current platform as ``windows`` or ``linux``."""
    return "windows" if sys.platform.startswith("win") else "linux"


def platform_matches(value: str | None) -> bool:
    """Return ``True`` when a package's ``platform`` field fits this host.

    ``None``/``""``/``"all"`` are compatible with every platform.
    """
    if not value:
        return True
    v = str(value).strip().lower()
    if v in ("", "all", "any"):
        return True
    return v == current_platform()