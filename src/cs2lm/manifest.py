"""Plugin manifests: detection, import into the repository, and serialization.

A manifest describes:
  * plugin metadata (name, version, type, timestamps)
  * every file that belongs to the plugin (source path in the repo,
    target path relative to the server root)
  * the actual "links" that the installer creates (directory symlinks,
    file symlinks, copies)
  * optional `metaplugins.ini` lines for Metamod plugins
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_FILENAME = "manifest.json"
PLUGIN_ROOT = "plugins"
FILES_DIR = "files"

# Core framework files that must never be managed/symlinked by the tool.
CORE_FORBIDDEN_PREFIXES = (
    "files/addons/counterstrikesharp/bin/",
    "files/addons/counterstrikesharp/api/",
    "files/addons/counterstrikesharp/dotnet/",
    "files/addons/metamod/bin/",
    "files/addons/counterstrikesharp/gamedata/gamedata.json",
    "files/addons/metamod/metaplugins.ini",
    "files/addons/metamod.vdf",
    "files/addons/metamod_x64.vdf",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sanitize_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("Plugin name cannot be empty")
    if any(c in name for c in '\\/:*?"<>|'):
        raise ValueError(f"Invalid plugin name: {name!r}")
    if name in (".", ".."):
        raise ValueError(f"Invalid plugin name: {name!r}")
    return name


def plugin_dir(repo: str | Path, name: str) -> Path:
    return Path(repo) / PLUGIN_ROOT / sanitize_name(name)


def list_plugins(repo: str | Path) -> list[str]:
    base = Path(repo) / PLUGIN_ROOT
    if not base.is_dir():
        return []
    return sorted(
        p.name for p in base.iterdir()
        if p.is_dir() and (p / MANIFEST_FILENAME).exists()
    )


def load_manifest(repo: str | Path, name: str) -> dict:
    p = plugin_dir(repo, name) / MANIFEST_FILENAME
    if not p.exists():
        raise FileNotFoundError(f"Plugin not found in repository: {name}")
    return json.loads(p.read_text(encoding="utf-8"))


def save_manifest(repo: str | Path, name: str, manifest: dict) -> None:
    p = plugin_dir(repo, name) / MANIFEST_FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Plugin type detection
# ---------------------------------------------------------------------------

def classify_plugin(source: str | Path, type_hint: str | None = None) -> str:
    """Classify a plugin package as ``css`` or ``metamod``."""
    if type_hint in ("css", "metamod"):
        return type_hint
    src = Path(source)
    if src.is_dir():
        if (src / "addons" / "counterstrikesharp").exists():
            return "css"
        if (src / "addons" / "metamod").exists():
            return "metamod"
        if list(src.glob("*.dll")) or list(src.glob("*.deps.json")):
            return "css"
        # Metamod addon tree: addons/<name>/bin contains native binaries.
        if (src / "addons").is_dir():
            natives = list((src / "addons").rglob("*.so")) + list((src / "addons").rglob("*.dll"))
            if natives:
                return "metamod"
        if (src / "bin").exists():
            native = list((src / "bin").rglob("*.so")) + list((src / "bin").rglob("*.dll"))
            if native:
                return "metamod"
    else:
        if src.suffix.lower() == ".dll":
            return "css"
        if src.suffix.lower() in (".so", ".dll", ".vdf"):
            return "metamod"
    raise ValueError(
        "Could not detect plugin type (expected a CSS plugin folder or an "
        "addons/ tree). Use --type css|metamod to override."
    )


# ---------------------------------------------------------------------------
# Copying plugin content into the repository
# ---------------------------------------------------------------------------

def _copy_css_source(source: Path, name: str, files_root: Path) -> None:
    if source.is_dir() and (source / "addons").is_dir():
        shutil.copytree(source / "addons", files_root / "addons")
        _normalize_css_plugin_dirs(files_root, name)
    else:
        dest = files_root / "addons" / "counterstrikesharp" / "plugins" / name
        if source.is_dir():
            shutil.copytree(source, dest)
        else:
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest / source.name)


def _rename_css_entries(css: Path, old: str, new: str) -> None:
    """Rename plugin-specific entries from ``old`` to ``new``.

    Covers the standard CSS plugin locations that
    :func:`_collect_css_links` scans: ``plugins/``, ``configs/plugins/``,
    ``configs/``, ``lang/``, ``gamedata/`` and ``gamedata/plugins/``.
    """
    roots = [
        css / "plugins",
        css / "configs" / "plugins",
        css / "configs",
        css / "lang",
        css / "gamedata",
        css / "gamedata" / "plugins",
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.name == old or child.name.startswith(old + "."):
                child.rename(root / (new + child.name[len(old):]))


def _normalize_css_plugin_dirs(files_root: Path, name: str) -> None:
    """Rename the plugin directories inside a copied ``addons/`` tree to ``name``.

    A package may ship as ``addons/counterstrikesharp/plugins/DemoPlugin/``
    while the user adds it as ``cs2lm add Renamed ./DemoPlugin/``. Without
    normalization the manifest is stored as ``Renamed`` but links point at
    ``plugins/DemoPlugin``, which breaks install/uninstall and profile
    switching. When exactly one plugin directory is present, it (and its
    matching configs/lang/gamedata entries) are renamed to the repository
    name.
    """
    css = files_root / "addons" / "counterstrikesharp"
    if not css.is_dir():
        return
    plugins_dir = css / "plugins"
    if not plugins_dir.is_dir():
        return
    plugin_dirs = [p for p in plugins_dir.iterdir() if p.is_dir()]
    if len(plugin_dirs) != 1:
        return  # Multiple plugin dirs: package layout wins, cannot rename.
    old_name = plugin_dirs[0].name
    if old_name == name or not old_name:
        return
    _rename_css_entries(css, old_name, name)


def _copy_metamod_source(source: Path, name: str, files_root: Path) -> None:
    if source.is_dir() and (source / "addons").is_dir():
        shutil.copytree(source / "addons", files_root / "addons")
    elif source.is_file() and source.suffix.lower() == ".vdf":
        dest = files_root / "addons" / "metamod"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest / source.name)
    else:
        raise ValueError(
            "Metamod plugin package must contain an addons/ tree or a .vdf file."
        )


def _copy_source(plugin_type: str, source: Path, name: str, files_root: Path) -> None:
    if plugin_type == "css":
        _copy_css_source(source, name, files_root)
    else:
        _copy_metamod_source(source, name, files_root)


# ---------------------------------------------------------------------------
# Manifest generation
# ---------------------------------------------------------------------------

def _walk_files(files_root: Path) -> list[dict]:
    files: list[dict] = []
    for f in sorted(files_root.rglob("*")):
        if f.is_file() and not f.is_symlink():
            rel = f.relative_to(files_root).as_posix()
            files.append({"source": f"files/{rel}"})
    return files


def _target_for(source: str, csgo_rel: str) -> str:
    """Map a repo-relative source path to a server-root-relative target."""
    if source.startswith("files/addons/"):
        return f"{csgo_rel}/{source.removeprefix('files/')}"
    return f"{csgo_rel}/{source}"


def _dir_link(files_root: Path, child: Path, csgo_rel: str, kind: str | None = None) -> dict:
    addons = files_root / "addons"
    rel = child.relative_to(addons).as_posix()
    return {
        "source": f"files/addons/{rel}",
        "target": f"{csgo_rel}/addons/{rel}",
        "kind": kind or ("symlink-dir" if child.is_dir() else "symlink-file"),
    }


def _collect_css_links(files_root: Path, plugin_name: str, csgo_rel: str) -> list[dict]:
    """Collect link entries for a CSS plugin's file tree (mirroring addons/)."""
    links: list[dict] = []
    addons = files_root / "addons"
    if not addons.is_dir():
        return links
    css = addons / "counterstrikesharp"
    if not css.is_dir():
        return links

    plugins_dir = css / "plugins"
    if plugins_dir.is_dir():
        for child in sorted(plugins_dir.iterdir()):
            if child.is_dir():
                links.append(_dir_link(files_root, child, csgo_rel))

    configs_dir = css / "configs"
    if configs_dir.is_dir():
        cplugins = configs_dir / "plugins"
        if cplugins.is_dir():
            for child in sorted(cplugins.iterdir()):
                if child.is_dir():
                    links.append(_dir_link(files_root, child, csgo_rel))
        for child in sorted(configs_dir.iterdir()):
            if child.name == "plugins":
                continue
            if child.name == plugin_name or child.name.startswith(plugin_name + "."):
                links.append(_dir_link(files_root, child, csgo_rel))

    gamedata_dir = css / "gamedata"
    if gamedata_dir.is_dir():
        for child in sorted(gamedata_dir.iterdir()):
            if child.name == plugin_name:
                links.append(_dir_link(files_root, child, csgo_rel))
            elif child.is_dir() and child.name == "plugins":
                for sub in sorted(child.iterdir()):
                    if sub.name == plugin_name or sub.name.startswith(plugin_name):
                        links.append(_dir_link(files_root, sub, csgo_rel))

    lang_dir = css / "lang"
    if lang_dir.is_dir():
        for child in sorted(lang_dir.iterdir()):
            if child.name == plugin_name:
                links.append(_dir_link(files_root, child, csgo_rel))

    return _dedupe_links(links)


def _collect_metamod_links(files_root: Path, plugin_name: str, csgo_rel: str) -> tuple[list[dict], list[str]]:
    links: list[dict] = []
    ini_lines: list[str] = []
    addons = files_root / "addons"
    if not addons.is_dir():
        return links, ini_lines

    mm = addons / "metamod"
    has_vdf = False
    if mm.is_dir():
        for child in sorted(mm.iterdir()):
            if child.is_file() and child.suffix.lower() == ".vdf":
                has_vdf = True
                links.append(
                    {
                        "source": f"files/addons/{child.relative_to(addons).as_posix()}",
                        "target": f"{csgo_rel}/addons/{child.relative_to(addons).as_posix()}",
                        "kind": "copy",
                    }
                )

    for child in sorted(addons.iterdir()):
        if child.name in ("metamod", "counterstrikesharp"):
            continue
        if (child / "bin").exists():
            links.append(_dir_link(files_root, child, csgo_rel))
            if not has_vdf:
                ini_lines.append(f"addons/{child.name}")

    return _dedupe_links(links), sorted(set(ini_lines))


def _dedupe_links(links: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for link in links:
        key = (link["source"], link["target"])
        if key in seen:
            continue
        seen.add(key)
        out.append(link)
    return out


def _validate_no_core_overwrites(files: list[dict]) -> None:
    for entry in files:
        src = entry["source"]
        for prefix in CORE_FORBIDDEN_PREFIXES:
            if src.startswith(prefix):
                raise ValueError(
                    f"Plugin package contains core framework file '{src}'; "
                    "refusing to manage core files."
                )


def add_plugin(
    repo: str | Path,
    name: str,
    source: str | Path,
    type_hint: str | None = None,
    version: str | None = None,
) -> dict:
    """Copy a plugin package into the repository and generate its manifest."""
    source_path = Path(source).expanduser()
    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")
    name = sanitize_name(name)
    pdir = plugin_dir(repo, name)
    if pdir.exists():
        raise FileExistsError(f"Plugin already exists in repository: {name}")

    plugin_type = classify_plugin(source_path, type_hint)
    files_root = pdir / FILES_DIR
    pdir.mkdir(parents=True, exist_ok=True)
    try:
        _copy_source(plugin_type, source_path, name, files_root)
        files = _walk_files(files_root)
        _validate_no_core_overwrites(files)
        cfg = _load_config(repo)
        csgo_rel = cfg["csgo_rel"]
        for entry in files:
            entry["target"] = _target_for(entry["source"], csgo_rel)

        if plugin_type == "css":
            links = _collect_css_links(files_root, name, csgo_rel)
            ini_lines: list[str] = []
        else:
            links, ini_lines = _collect_metamod_links(files_root, name, csgo_rel)

        manifest = {
            "name": name,
            "display_name": name,
            "version": version or "1.0.0",
            "plugin_type": plugin_type,
            "created_at": _now(),
            "updated_at": _now(),
            "enabled": True,
            "imported": False,
            "source_root": FILES_DIR,
            "files": files,
            "links": links,
            "ini_lines": ini_lines,
            "dependencies": _detect_dependencies(plugin_type, files_root),
        }
        save_manifest(repo, name, manifest)
        return manifest
    except Exception:
        shutil.rmtree(pdir, ignore_errors=True)
        raise


def _detect_dependencies(plugin_type: str, files_root: Path) -> dict:
    """Detect runtime dependencies declared by the plugin package."""
    if plugin_type != "css":
        return {}
    from cs2lm.deps import CSS_API_ASSEMBLY, read_api_dependency

    api_version = read_api_dependency(files_root)
    if not api_version:
        return {}
    return {CSS_API_ASSEMBLY: api_version}


def _load_config(repo: str | Path) -> dict:
    from cs2lm.config import load_config

    return load_config(repo)