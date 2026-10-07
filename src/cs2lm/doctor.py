"""Diagnostics: broken links, missing targets, permissions, conflicts."""
from __future__ import annotations

import json
import os
from pathlib import Path

from cs2lm import linking
from cs2lm.config import load_config
from cs2lm.logutil import Logger
from cs2lm.manifest import list_plugins, load_manifest
from cs2lm.paths import resolve_within

STATE_REL = "state/links.json"


def load_state(repo: str | Path) -> dict:
    p = Path(repo) / STATE_REL
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"links": []}


def _iter_tool_links(repo: Path, server: Path, csgo_rel: str):
    """Yield (plugin, record, target_abs, source_abs) from the state database."""
    state = load_state(repo)
    for rec in state.get("links", []):
        plugin = rec.get("plugin")
        try:
            target = resolve_within(server, rec["target"])
            source = (repo / "plugins" / plugin / rec["source"])
        except (ValueError, KeyError):
            continue
        yield plugin, rec, target, source


def _iter_orphan_links(repo: Path, server: Path, csgo_rel: str):
    """Scan known addon directories for symlinks pointing into the repo."""
    known_dirs = [
        server / csgo_rel / "addons" / "counterstrikesharp" / "plugins",
        server / csgo_rel / "addons" / "counterstrikesharp" / "configs" / "plugins",
        server / csgo_rel / "addons" / "counterstrikesharp" / "configs",
        server / csgo_rel / "addons" / "counterstrikesharp" / "gamedata",
        server / csgo_rel / "addons" / "counterstrikesharp" / "lang",
        server / csgo_rel / "addons" / "metamod",
    ]
    repo_resolved = repo.resolve()
    seen_targets = {
        str(rec.get("target", "")) for rec in load_state(repo).get("links", [])
    }
    for base in known_dirs:
        if not base.is_dir():
            continue
        for child in base.iterdir():
            if not (linking.is_link(child) or linking.is_junction(child)):
                continue
            try:
                real = Path(os.path.realpath(child)).resolve()
            except OSError:
                continue
            if real.is_relative_to(repo_resolved) or repo_resolved in real.parents:
                rel_target = child.relative_to(server).as_posix()
                if rel_target not in seen_targets:
                    yield child, real


def run_doctor(repo: str | Path, logger: Logger | None = None) -> list[dict]:
    """Run diagnostics and return a list of issue dicts."""
    logger = logger or Logger()
    issues: list[dict] = []
    repo_path = Path(repo).resolve()
    cfg = load_config(repo_path)
    server = Path(cfg["server_path"]).resolve()
    csgo_rel = cfg["csgo_rel"]
    csgo_dir = server / csgo_rel

    if not csgo_dir.is_dir():
        issues.append(
            {
                "severity": "error",
                "code": "missing-csgo",
                "message": f"CS2 game directory not found: {csgo_dir}",
            }
        )
        return issues

    addons = csgo_dir / "addons"
    if not addons.is_dir():
        issues.append(
            {
                "severity": "error",
                "code": "missing-addons",
                "message": f"addons directory not found: {addons}",
            }
        )

    if not (addons / "counterstrikesharp").is_dir():
        issues.append(
            {
                "severity": "warn",
                "code": "missing-css",
                "message": "CounterStrikeSharp not found under addons/counterstrikesharp",
            }
        )
    if not (addons / "metamod").is_dir():
        issues.append(
            {
                "severity": "warn",
                "code": "missing-metamod",
                "message": "Metamod not found under addons/metamod",
            }
        )

    # -- managed links ------------------------------------------------------
    for plugin, rec, target, source in _iter_tool_links(repo_path, server, csgo_rel):
        if not source.exists():
            issues.append(
                {
                    "severity": "error",
                    "code": "missing-source",
                    "plugin": plugin,
                    "message": f"repo source missing: {source}",
                }
            )
        if not linking.path_exists(target):
            issues.append(
                {
                    "severity": "error",
                    "code": "broken-link",
                    "plugin": plugin,
                    "message": f"link target missing: {target}",
                }
            )
        elif linking.is_link(target):
            real = Path(os.path.realpath(target)).resolve()
            if real != source.resolve():
                issues.append(
                    {
                        "severity": "warn",
                        "code": "wrong-target",
                        "plugin": plugin,
                        "message": f"link {target} points to {real}, expected {source}",
                    }
                )
        else:
            issues.append(
                {
                    "severity": "warn",
                    "code": "replaced-by-real",
                    "plugin": plugin,
                    "message": (
                        f"expected link at {target} but found real content "
                        "(it may have been replaced or copied over)"
                    ),
                }
            )
        parent = target.parent
        if not os.access(parent, os.W_OK):
            issues.append(
                {
                    "severity": "warn",
                    "code": "permission",
                    "plugin": plugin,
                    "message": f"no write permission on {parent}",
                }
            )

    # -- orphan links -------------------------------------------------------
    for orphan, real in _iter_orphan_links(repo_path, server, csgo_rel):
        issues.append(
            {
                "severity": "warn",
                "code": "orphan-link",
                "message": f"unmanaged symlink {orphan} -> {real}",
            }
        )

    # -- conflicts for plugins that are not currently installed ---------------
    state = load_state(repo_path)
    installed_plugins = {r.get("plugin") for r in state.get("links", [])}
    for plugin in list_plugins(repo_path):
        if plugin in installed_plugins:
            continue
        manifest = load_manifest(repo_path, plugin)
        for link in manifest.get("links", []):
            try:
                target = resolve_within(server, link["target"])
            except ValueError:
                continue
            if linking.path_exists(target):
                issues.append(
                    {
                        "severity": "warn",
                        "code": "conflict",
                        "plugin": plugin,
                        "message": (
                            f"plugin '{plugin}' is not installed but unmanaged "
                            f"content exists at {target}; install may conflict"
                        ),
                    }
                )

    return issues