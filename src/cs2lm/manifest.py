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

import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from cs2lm.frameworks import (
    ROOT_TO_ID,
    framework_info,
    framework_ids,
    normalize_framework,
)

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
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid manifest for plugin '{name}' at {p}: {exc.msg} "
            f"(line {exc.lineno}, column {exc.colno}). Re-add the plugin or "
            "restore this file from a backup."
        ) from exc


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
    """Classify a plugin package as ``css``, ``metamod``, ``swiftly``, ..."""
    canonical = normalize_framework(type_hint)
    if canonical:
        return canonical
    src = Path(source)
    if src.is_dir():
        addons = src / "addons"
        if addons.is_dir():
            for child in sorted(addons.iterdir()):
                fw_id = ROOT_TO_ID.get(child.name)
                if fw_id:
                    return fw_id
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
        "Could not detect plugin type (expected a plugin folder or an "
        "addons/ tree). Use --type "
        + "|".join(framework_ids())
        + " to override."
    )


# ---------------------------------------------------------------------------
# Copying plugin content into the repository
# ---------------------------------------------------------------------------

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


def _copy_framework_source(
    info: dict,
    source: Path,
    name: str,
    files_root: Path,
) -> None:
    """Copy a non-Metamod framework plugin (CSS, Swiftly, Plugify, ModSharp)."""
    addons = source / "addons"
    if source.is_dir() and addons.is_dir():
        shutil.copytree(addons, files_root / "addons")
        _normalize_framework_plugin_dirs(files_root, name, info)
    else:
        plugin_rel = info.get("plugin_rel") or "plugins"
        dest = files_root / "addons" / info["root"] / plugin_rel / name
        if source.is_dir():
            shutil.copytree(source, dest)
        else:
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest / source.name)


def _copy_source(plugin_type: str, source: Path, name: str, files_root: Path) -> None:
    info = framework_info(plugin_type)
    if info is not None and info["id"] == "metamod":
        _copy_metamod_source(source, name, files_root)
    else:
        if info is None:
            # Legacy: any non-css package was treated as metamod; fall back.
            info = framework_info("metamod")
            _copy_metamod_source(source, name, files_root)
            return
        _copy_framework_source(info, source, name, files_root)


def _rename_framework_entries(
    root_dir: Path,
    old: str,
    new: str,
    plugin_rel: str = "plugins",
) -> None:
    """Rename plugin-specific entries from ``old`` to ``new``.

    Covers the standard plugin locations that
    :func:`_collect_framework_links` scans: ``<plugin_rel>/``,
    ``configs/<plugin_rel>/``, ``configs/``, ``lang/``, ``gamedata/`` and
    ``gamedata/<plugin_rel>/``.
    """
    roots = [
        root_dir / plugin_rel,
        root_dir / "configs" / plugin_rel,
        root_dir / "configs",
        root_dir / "lang",
        root_dir / "gamedata",
        root_dir / "gamedata" / plugin_rel,
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.name == old or child.name.startswith(old + "."):
                child.rename(root / (new + child.name[len(old):]))


def _normalize_framework_plugin_dirs(
    files_root: Path,
    name: str,
    info: dict,
) -> None:
    """Rename the plugin directories inside a copied ``addons/`` tree to ``name``.

    A package may ship as ``addons/<root>/plugins/DemoPlugin/`` while the
    user adds it as ``cs2lm add Renamed ./DemoPlugin/``. Without normalization
    the manifest is stored as ``Renamed`` but links point at
    ``plugins/DemoPlugin``, which breaks install/uninstall and profile
    switching. When exactly one plugin directory is present, it (and its
    matching configs/lang/gamedata entries) are renamed to the repository
    name.
    """
    root_dir = files_root / "addons" / info["root"]
    if not root_dir.is_dir():
        return
    plugin_rel = info.get("plugin_rel")
    if not plugin_rel:
        return
    plugins_dir = root_dir / plugin_rel
    if not plugins_dir.is_dir():
        return
    plugin_dirs = [p for p in plugins_dir.iterdir() if p.is_dir()]
    if len(plugin_dirs) != 1:
        names = ", ".join(p.name for p in plugin_dirs)
        raise ValueError(
            f"Package contains {len(plugin_dirs)} plugin directories under "
            f"'{plugin_rel}/': {names}. Use '--plugins "
            f"{','.join(p.name for p in plugin_dirs)}' to split it into "
            f"separate repository entries, or extract and add each plugin "
            "separately."
        )
    old_name = plugin_dirs[0].name
    if old_name == name or not old_name:
        return
    _rename_framework_entries(root_dir, old_name, name, plugin_rel)


# ---------------------------------------------------------------------------
# Manifest generation
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    """Compute the SHA-256 hex digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _walk_files(files_root: Path) -> list[dict]:
    files: list[dict] = []
    for f in sorted(files_root.rglob("*")):
        if f.is_file() and not f.is_symlink():
            rel = f.relative_to(files_root).as_posix()
            files.append(
                {"source": f"files/{rel}", "sha256": _sha256(f)}
            )
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


def _collect_framework_links(
    files_root: Path,
    root_name: str,
    plugin_name: str,
    csgo_rel: str,
) -> list[dict]:
    """Collect link entries mirroring a framework's ``addons/`` file tree."""
    links: list[dict] = []
    addons = files_root / "addons"
    if not addons.is_dir():
        return links
    root_dir = addons / root_name
    if not root_dir.is_dir():
        return links

    plugins_dir = root_dir / "plugins"
    if plugins_dir.is_dir():
        for child in sorted(plugins_dir.iterdir()):
            if child.is_dir():
                links.append(_dir_link(files_root, child, csgo_rel))

    configs_dir = root_dir / "configs"
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

    gamedata_dir = root_dir / "gamedata"
    if gamedata_dir.is_dir():
        for child in sorted(gamedata_dir.iterdir()):
            if child.name == plugin_name:
                links.append(_dir_link(files_root, child, csgo_rel))
            elif child.is_dir() and child.name == "plugins":
                for sub in sorted(child.iterdir()):
                    if sub.name == plugin_name or sub.name.startswith(plugin_name):
                        links.append(_dir_link(files_root, sub, csgo_rel))

    lang_dir = root_dir / "lang"
    if lang_dir.is_dir():
        for child in sorted(lang_dir.iterdir()):
            if child.name == plugin_name:
                links.append(_dir_link(files_root, child, csgo_rel))

    shared_dir = root_dir / "shared"
    if shared_dir.is_dir():
        for child in sorted(shared_dir.iterdir()):
            if child.is_dir():
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


def split_framework_plugins(
    source: str | Path,
    names: list[str],
    dest_base: str | Path,
    framework: str = "css",
) -> list[tuple[str, Path]]:
    """Split a multi-plugin package into per-plugin ``addons/`` trees.

    Works for every standard framework layout
    (``addons/<root>/plugins/<Name>``): CSS, Swiftly, Plugify and ModSharp.
    Builds one ``addons/`` tree per plugin under ``dest_base``, mirroring
    exactly what :func:`_collect_framework_links` would link for a single
    plugin: ``plugins/<name>``, ``configs/plugins/<name>``,
    ``configs/<name>.*``, ``lang/<name>``, ``gamedata/<name>`` and
    ``gamedata/plugins/<name>`` (when present).  A ``shared/`` directory in
    the package is reported on stderr but not copied into the split trees
    (each split plugin would otherwise install conflicting links to the same
    server path).

    Returns ``(name, source_dir)`` pairs that can be passed to
    :func:`add_plugin`.
    """
    fw = normalize_framework(framework) or "css"
    info = framework_info(fw)
    if info is None:
        raise ValueError(f"Unsupported framework for splitting: {framework}")
    root_name = info["root"]
    src = Path(source)
    base = Path(dest_base)
    fw_root = src / "addons" / root_name
    if not fw_root.is_dir():
        raise ValueError(
            f"Package does not contain a {info['name']} addons/ tree; "
            "cannot split into plugins."
        )
    plugins_dir = fw_root / "plugins"
    if not plugins_dir.is_dir():
        raise ValueError("Package has no plugins/ directory to split.")
    available = sorted(p.name for p in plugins_dir.iterdir() if p.is_dir())
    missing = [n for n in names if n not in available]
    if missing:
        raise ValueError(
            f"Plugin(s) not found in package: {', '.join(missing)}. "
            f"Available: {', '.join(available)}."
        )

    results: list[tuple[str, Path]] = []
    for name in names:
        out = base / name
        dest_fw = out / "addons" / root_name
        shutil.copytree(plugins_dir / name, dest_fw / "plugins" / name)

        cplugins = fw_root / "configs" / "plugins"
        if (cplugins / name).is_dir():
            shutil.copytree(
                cplugins / name, dest_fw / "configs" / "plugins" / name
            )

        cfg_root = fw_root / "configs"
        if cfg_root.is_dir():
            for child in sorted(cfg_root.iterdir()):
                if child.name == "plugins":
                    continue
                if child.name == name or child.name.startswith(name + "."):
                    (dest_fw / "configs").mkdir(parents=True, exist_ok=True)
                    if child.is_dir():
                        shutil.copytree(child, dest_fw / "configs" / child.name)
                    else:
                        shutil.copy2(child, dest_fw / "configs" / child.name)

        lang = fw_root / "lang"
        if (lang / name).is_dir():
            shutil.copytree(lang / name, dest_fw / "lang" / name)

        gamedata = fw_root / "gamedata"
        if (gamedata / name).exists():
            (dest_fw / "gamedata").mkdir(parents=True, exist_ok=True)
            if (gamedata / name).is_dir():
                shutil.copytree(gamedata / name, dest_fw / "gamedata" / name)
            else:
                shutil.copy2(gamedata / name, dest_fw / "gamedata" / name)
        if (gamedata / "plugins" / name).is_dir():
            shutil.copytree(
                gamedata / "plugins" / name,
                dest_fw / "gamedata" / "plugins" / name,
            )

        shared = fw_root / "shared"
        if shared.is_dir():
            print(
                "Warning: this package contains a shared/ directory. Split "
                "plugins do not include shared files; add them to the server "
                "manually if the plugin needs them.",
                file=sys.stderr,
            )

        results.append((name, out))
    return results


def split_css_plugins(
    source: str | Path,
    names: list[str],
    dest_base: str | Path,
) -> list[tuple[str, Path]]:
    """Split a multi-plugin CSS package into per-plugin ``addons/`` trees.

    Backwards-compatible wrapper around
    :func:`split_framework_plugins` for the CounterStrikeSharp layout.
    """
    return split_framework_plugins(source, names, dest_base, framework="css")


def split_metamod_addons(
    source: str | Path,
    names: list[str],
    dest_base: str | Path,
) -> list[tuple[str, Path]]:
    """Split a multi-addon Metamod package into per-plugin ``addons/`` trees.

    Metamod plugins live in top-level addon directories (``addons/<Name>/``
    containing a ``bin/`` folder). Each requested addon is copied into its
    own ``addons/`` tree under ``dest_base``.
    """
    src = Path(source)
    base = Path(dest_base)
    addons = src / "addons"
    available: list[str] = []
    if addons.is_dir():
        for child in sorted(addons.iterdir()):
            if child.is_dir() and (child / "bin").exists():
                available.append(child.name)
    missing = [n for n in names if n not in available]
    if missing:
        raise ValueError(
            f"Metamod addon(s) not found in package: {', '.join(missing)}. "
            f"Available: {', '.join(available)}."
        )

    results: list[tuple[str, Path]] = []
    for name in names:
        out = base / name
        dest_addons = out / "addons"
        shutil.copytree(addons / name, dest_addons / name)
        results.append((name, out))
    return results


def _available_framework_plugins(src: Path) -> dict[str, str]:
    """Map plugin names found in standard framework layouts to framework ids."""
    found: dict[str, str] = {}
    for fw_id in framework_ids():
        info = framework_info(fw_id)
        if info is None or info["plugin_rel"] is None:
            continue
        plugins_dir = src / "addons" / info["root"] / "plugins"
        if plugins_dir.is_dir():
            for child in sorted(plugins_dir.iterdir()):
                if child.is_dir():
                    found.setdefault(child.name, fw_id)
    return found


def _available_metamod_addons(src: Path) -> list[str]:
    addons = src / "addons"
    if not addons.is_dir():
        return []
    return sorted(
        child.name
        for child in addons.iterdir()
        if child.is_dir() and (child / "bin").exists()
    )


def split_package_plugins(
    source: str | Path,
    names: list[str],
    dest_base: str | Path,
) -> list[tuple[str, Path]]:
    """Split a mixed-framework package into per-plugin trees.

    Supports standard framework plugins (``addons/<root>/plugins/<Name>``)
    and Metamod addons (``addons/<Name>/bin``) in the same package. Each name
    is routed to the splitter matching its layout.
    """
    src = Path(source)
    base = Path(dest_base)
    standard = _available_framework_plugins(src)
    metamod = _available_metamod_addons(src)
    missing = [n for n in names if n not in standard and n not in metamod]
    if missing:
        raise ValueError(
            f"Plugin(s) not found in package: {', '.join(missing)}. "
            f"Available standard plugins: {', '.join(sorted(standard)) or '(none)'}; "
            f"available Metamod addons: {', '.join(metamod) or '(none)'}."
        )

    results: list[tuple[str, Path]] = []
    by_fw: dict[str, list[str]] = {}
    mm_names: list[str] = []
    for n in names:
        if n in standard:
            by_fw.setdefault(standard[n], []).append(n)
        else:
            mm_names.append(n)
    for fw, group in by_fw.items():
        results.extend(split_framework_plugins(src, group, base, framework=fw))
    if mm_names:
        results.extend(split_metamod_addons(src, mm_names, base))
    return results


def add_plugin(
    repo: str | Path,
    name: str,
    source: str | Path,
    type_hint: str | None = None,
    version: str | None = None,
    meta: dict | None = None,
) -> dict:
    """Copy a plugin package into the repository and generate its manifest.

    ``meta`` is optional package metadata read from ``cs2pkg.json`` (or a
    registry entry). Recognized fields are ``author``, ``description``,
    ``license``, ``homepage``, ``repository`` and ``dependencies`` (a dict of
    ``assembly -> version`` constraints). These are stored on the manifest
    so the metadata survives ``pack``/``import`` round trips.
    """
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

        if plugin_type == "metamod":
            links, ini_lines = _collect_metamod_links(files_root, name, csgo_rel)
        else:
            info = framework_info(plugin_type)
            root_name = info["root"] if info else "counterstrikesharp"
            links = _collect_framework_links(files_root, root_name, name, csgo_rel)
            ini_lines: list[str] = []

        manifest = {
            "name": name,
            "display_name": name,
            "version": version or _detect_version(plugin_type, name, files_root),
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
        if meta:
            for field in ("author", "description", "license", "homepage", "repository"):
                if meta.get(field):
                    manifest[field] = meta[field]
            if meta.get("api_version") is not None:
                manifest["api_version"] = meta["api_version"]
            if meta.get("entry"):
                manifest["entry"] = str(meta["entry"])
            requires_fw = [
                r
                for r in (normalize_framework(x) for x in (meta.get("requires_frameworks") or []))
                if r
            ]
            if requires_fw:
                manifest["requires_frameworks"] = requires_fw
            if meta.get("platform"):
                manifest["platform"] = str(meta["platform"]).lower()
            pkg_deps = meta.get("dependencies")
            if isinstance(pkg_deps, dict):
                for assembly, req in pkg_deps.items():
                    manifest["dependencies"].setdefault(assembly, req)
            requires = meta.get("requires")
            if isinstance(requires, dict) and requires:
                manifest["requires"] = dict(requires)
            elif isinstance(requires, (list, tuple)) and requires:
                manifest["requires"] = [str(r) for r in requires]
        save_manifest(repo, name, manifest)
        return manifest
    except Exception:
        shutil.rmtree(pdir, ignore_errors=True)
        raise


# ---------------------------------------------------------------------------
# Game-content packages (kind == "content")
# ---------------------------------------------------------------------------

def _resolve_content_roots(meta: dict, source_path: Path, csgo_rel: str) -> dict:
    """Resolve a content package's ``roots`` mapping.

    ``roots`` maps a package top-level entry to a server-root-relative
    target (for example ``cfg -> game/csgo/cfg``). When the package declares
    none, every top-level directory maps to ``<csgo_rel>/<dir>`` and a
    ``game/`` directory maps to ``game``.
    """
    declared = meta.get("roots")
    if isinstance(declared, dict) and declared:
        roots: dict = {}
        for key, value in declared.items():
            k = str(key).strip("/")
            v = str(value).replace("\\", "/").strip("/")
            if k:
                roots[k] = v
        return roots
    roots = {}
    for child in sorted(source_path.iterdir()):
        if child.name.startswith(".") or child.name.startswith("_"):
            continue
        if child.name == "game":
            roots["game"] = "game"
        else:
            roots[child.name] = f"{csgo_rel}/{child.name}"
    return roots


def _copy_content_tree(source_path: Path, roots: dict, files_root: Path) -> None:
    """Copy a content package into ``files/`` mirroring the server root."""
    for root_name, rel_target in roots.items():
        pkg_root = source_path / root_name
        if not pkg_root.exists():
            continue
        dest = files_root / rel_target
        if pkg_root.is_dir():
            shutil.copytree(pkg_root, dest, dirs_exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pkg_root, dest)


def _content_target(source: str) -> str:
    """Server-root-relative target for a content ``files/`` source path."""
    return source.removeprefix("files/").lstrip("/")


def _validate_no_core_targets(files: list[dict], csgo_rel: str) -> None:
    """Reject content packages that try to manage core framework files."""
    forbidden = (
        f"{csgo_rel}/addons/counterstrikesharp/bin/",
        f"{csgo_rel}/addons/counterstrikesharp/api/",
        f"{csgo_rel}/addons/counterstrikesharp/dotnet/",
        f"{csgo_rel}/addons/metamod/bin/",
        f"{csgo_rel}/addons/counterstrikesharp/gamedata/gamedata.json",
        f"{csgo_rel}/addons/metamod/metaplugins.ini",
        f"{csgo_rel}/addons/metamod.vdf",
        f"{csgo_rel}/addons/metamod_x64.vdf",
    )
    for entry in files:
        target = entry.get("target", "").replace("\\", "/")
        for prefix in forbidden:
            if target.startswith(prefix):
                raise ValueError(
                    f"Content package contains core framework file '{target}'; "
                    "refusing to manage core files."
                )


def add_content(
    repo: str | Path,
    name: str,
    source: str | Path,
    version: str | None = None,
    meta: dict | None = None,
) -> dict:
    """Import a game-content mod (``kind == "content"``) into the repository.

    Content packages have no plugin manifest, no ``plugin_type`` and no
    framework binaries. They contain arbitrary server files (``cfg/``,
    ``overrides/``, ``addons/``, ...) declared through a ``roots`` mapping.
    Files are installed by copying them to the server (``kind: "copy"``)
    so game/configuration files can be modified in place without touching the
    repository copy.
    """
    source_path = Path(source).expanduser()
    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")
    name = sanitize_name(name)
    pdir = plugin_dir(repo, name)
    if pdir.exists():
        raise FileExistsError(
            f"Content package already exists in repository: {name}"
        )
    meta = meta or {}
    cfg = _load_config(repo)
    csgo_rel = cfg["csgo_rel"]
    roots = _resolve_content_roots(meta, source_path, csgo_rel)
    files_root = pdir / FILES_DIR
    pdir.mkdir(parents=True, exist_ok=True)
    try:
        _copy_content_tree(source_path, roots, files_root)
        files = _walk_files(files_root)
        for entry in files:
            entry["target"] = _content_target(entry["source"])
        _validate_no_core_targets(files, csgo_rel)
        requires_fw = [
            r
            for r in (normalize_framework(x) for x in (meta.get("requires_frameworks") or []))
            if r
        ]
        manifest = {
            "name": name,
            "kind": "content",
            "version": version or str(meta.get("version") or "1.0.0"),
            "plugin_type": None,
            "created_at": _now(),
            "updated_at": _now(),
            "enabled": True,
            "imported": False,
            "source_root": FILES_DIR,
            "roots": roots,
            "files": files,
            "links": [
                {"source": f["source"], "target": f["target"], "kind": "copy"}
                for f in files
            ],
            "ini_lines": [],
            "dependencies": {},
            "requires_frameworks": requires_fw,
            "platform": (meta.get("platform") or "all").lower(),
        }
        for field in ("author", "description", "license", "homepage", "repository"):
            if meta.get(field):
                manifest[field] = meta[field]
        save_manifest(repo, name, manifest)
        return manifest
    except Exception:
        shutil.rmtree(pdir, ignore_errors=True)
        raise


def _detect_version(plugin_type: str, name: str, files_root: Path) -> str:
    """Best-effort plugin version detection, defaulting to ``1.0.0``."""
    if plugin_type != "css":
        return "1.0.0"
    from cs2lm.deps import detect_plugin_version

    return detect_plugin_version(files_root, name) or "1.0.0"


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