"""Adopt plugins that already exist on the server into the repository.

This is the "landing layer" integration: external managers (or manual
installs) drop plugin files into the server; this tool copies them into the
repository and manages them with symlinks from then on.
"""
from __future__ import annotations

from pathlib import Path

from cs2lm import linking
from cs2lm.config import load_config
from cs2lm.importer import import_plugin
from cs2lm.logutil import Logger
from cs2lm.manifest import list_plugins


def find_css_plugins(repo: str | Path, logger: Logger | None = None) -> list[tuple[str, Path]]:
    """Return ``(name, path)`` for every real CSS plugin directory on the server.

    Symbolic links / junctions are skipped: they are usually managed by this
    tool or by another repository, and importing through a symlink would
    resolve outside the server directory.
    """
    logger = logger or Logger()
    cfg = load_config(repo)
    server = Path(cfg["server_path"]).resolve()
    csgo_rel = cfg["csgo_rel"]
    plugins_dir = server / csgo_rel / "addons" / "counterstrikesharp" / "plugins"
    if not plugins_dir.is_dir():
        return []
    found: list[tuple[str, Path]] = []
    for child in sorted(plugins_dir.iterdir()):
        if child.is_symlink() or linking.is_junction(child):
            logger.info(
                "adopt",
                f"skipping symlinked plugin directory (likely managed by "
                f"another repository): {child.name}",
            )
            continue
        if not child.is_dir():
            continue
        if list(child.glob("*.dll")) or list(child.glob("*.deps.json")):
            found.append((child.name, child))
    return found


def adopt_css_plugins(
    repo: str | Path,
    only: str | None = None,
    logger: Logger | None = None,
) -> list[str]:
    """Import CSS plugins found on the server into the repository.

    Returns the names of plugins that were newly adopted. Plugins already in
    the repository are skipped.
    """
    logger = logger or Logger()
    existing = set(list_plugins(repo))
    adopted: list[str] = []
    for name, path in find_css_plugins(repo, logger=logger):
        if only and name != only:
            continue
        if name in existing:
            logger.info("adopt", f"plugin already in repository, skipping: {name}")
            continue
        import_plugin(repo, name, path, type_hint="css", logger=logger)
        adopted.append(name)
    return adopted