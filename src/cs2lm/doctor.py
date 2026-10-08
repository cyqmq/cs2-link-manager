"""Diagnostics: broken links, missing targets, permissions, conflicts."""
from __future__ import annotations

import json
import os
from pathlib import Path

from cs2lm import linking
from cs2lm.config import load_config
from cs2lm.deps import CSS_API_ASSEMBLY, read_dotnet_assembly_version
from cs2lm.logutil import Logger
from cs2lm.manifest import list_plugins, load_manifest
from cs2lm.paths import resolve_within

STATE_REL = "state/links.json"


def _version_tuple(version: str) -> tuple[int, ...]:
    """Parse ``major.minor.build.revision`` into a tuple of ints."""
    parts: list[int] = []
    for part in version.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _versions_equal(a: str, b: str) -> bool:
    """Compare .NET assembly versions, ignoring trailing zero parts.

    CSS releases are usually three-part (``1.0.376``) while the .NET
    assembly version of ``CounterStrikeSharp.API.dll`` is four-part
    (``1.0.376.0``). A plain string comparison would false-positive.
    """
    ta = _version_tuple(a)
    tb = _version_tuple(b)
    width = max(len(ta), len(tb))
    ta += (0,) * (width - len(ta))
    tb += (0,) * (width - len(tb))
    return ta == tb


def load_state(repo: str | Path) -> dict:
    p = Path(repo) / STATE_REL
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8-sig"))
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


def _doctor_core_checks(
    csgo_dir: Path,
    addons: Path,
    issues: list[dict],
) -> None:
    """Verify the CS2 server structure and Metamod/CSS wiring.

    These checks are read-only: the doctor never modifies core files. They
    help a server owner confirm the layout is correct before relying on
    plugin links.
    """
    gameinfo = csgo_dir / "gameinfo.gi"
    if not gameinfo.is_file():
        issues.append(
            {
                "severity": "error",
                "code": "missing-gameinfo",
                "message": f"gameinfo.gi not found at {gameinfo}",
            }
        )
    else:
        try:
            text = gameinfo.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            issues.append(
                {
                    "severity": "warn",
                    "code": "unreadable-gameinfo",
                    "message": f"cannot read {gameinfo}: {exc}",
                }
            )
        else:
            if "addons/metamod" not in text:
                issues.append(
                    {
                        "severity": "warn",
                        "code": "metamod-not-in-gameinfo",
                        "message": (
                            f"{gameinfo} does not reference 'addons/metamod'; "
                            "Metamod will not be loaded by the engine. Add "
                            "'Game csgo/addons/metamod' to the SearchPaths "
                            "section."
                        ),
                    }
                )

    metamod_dir = addons / "metamod"
    if metamod_dir.is_dir():
        # CS2 loads Metamod from bin/linuxsteamrt64/metamod.2.cs2.so on
        # Linux and bin/win64/metamod.2.cs2.dll on Windows. Use a glob so a
        # future naming change does not cause false warnings.
        native_bins = [
            p
            for p in (metamod_dir / "bin").rglob("*")
            if p.is_file()
            and p.suffix.lower() in (".so", ".dll")
            and "metamod" in p.name.lower()
        ]
        if not native_bins:
            issues.append(
                {
                    "severity": "warn",
                    "code": "missing-metamod-bin",
                    "message": (
                        f"no Metamod native binary found under "
                        f"{metamod_dir / 'bin'} (expected "
                        "linuxsteamrt64/metamod.2.cs2.so or "
                        "win64/metamod.2.cs2.dll)"
                    ),
                }
            )
        if not (metamod_dir / "counterstrikesharp.vdf").is_file():
            issues.append(
                {
                    "severity": "warn",
                    "code": "missing-css-vdf",
                    "message": (
                        "counterstrikesharp.vdf not found under "
                        f"{metamod_dir}; CounterStrikeSharp will not be "
                        "loaded by Metamod"
                    ),
                }
            )

    css_dir = addons / "counterstrikesharp"
    if css_dir.is_dir():
        api_dll = css_dir / "api" / "CounterStrikeSharp.API.dll"
        if not api_dll.exists():
            issues.append(
                {
                    "severity": "warn",
                    "code": "missing-css-api",
                    "message": (
                        f"CounterStrikeSharp.API.dll not found at {api_dll}; "
                        "CSS may be installed incorrectly"
                    ),
                }
            )


def run_doctor(repo: str | Path, logger: Logger | None = None, verbose: bool = False) -> list[dict]:
    """Run diagnostics and return a list of issue dicts.

    When ``verbose`` is True, informational entries (severity ``"info"``)
    are appended, e.g. the symlink/junction/copy mode each installed plugin
    is actually using.
    """
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

    # -- core framework / server structure ----------------------------------
    # These checks confirm the server is laid out correctly and Metamod is
    # actually wired into the engine. Core files are never modified.
    if addons.is_dir():
        _doctor_core_checks(csgo_dir, addons, issues)

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

    if verbose:
        # Report the link mode each installed plugin actually uses
        # (symlink / junction / copy), so users can see link quality at a
        # glance without inspecting the state database.
        kinds_by_plugin: dict[str, set[str]] = {}
        for plugin, rec, _target, _source in _iter_tool_links(
            repo_path, server, csgo_rel
        ):
            kind = rec.get("kind_used") or rec.get("kind") or "unknown"
            kinds_by_plugin.setdefault(plugin, set()).add(kind)
        for plugin in sorted(kinds_by_plugin):
            kinds = ", ".join(sorted(kinds_by_plugin[plugin]))
            issues.append(
                {
                    "severity": "info",
                    "code": "link-mode",
                    "plugin": plugin,
                    "message": f"installed links use mode(s): {kinds}",
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

    # -- CSS API dependency checks -------------------------------------------
    for plugin in sorted(installed_plugins):
        try:
            manifest = load_manifest(repo_path, plugin)
        except FileNotFoundError:
            continue
        if manifest.get("plugin_type") != "css":
            continue
        api_ver = manifest.get("dependencies", {}).get(CSS_API_ASSEMBLY)
        if not api_ver:
            continue
        api_dll = (
            csgo_dir
            / "addons"
            / "counterstrikesharp"
            / "api"
            / "CounterStrikeSharp.API.dll"
        )
        server_ver = read_dotnet_assembly_version(api_dll)
        if server_ver is None:
            issues.append(
                {
                    "severity": "warn",
                    "code": "api-version-unverifiable",
                    "plugin": plugin,
                    "message": (
                        f"plugin '{plugin}' declares CounterStrikeSharp.API "
                        f"{api_ver} but the installed API version could not be "
                        "verified automatically; check it manually"
                    ),
                }
            )
        elif not _versions_equal(server_ver, api_ver):
            issues.append(
                {
                    "severity": "warn",
                    "code": "api-version-mismatch",
                    "plugin": plugin,
                    "message": (
                        f"plugin '{plugin}' declares CounterStrikeSharp.API "
                        f"{api_ver} but the server has {server_ver}; the plugin "
                        "may not work"
                    ),
                }
            )

    return issues