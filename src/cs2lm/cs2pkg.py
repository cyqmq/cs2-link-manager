""".cs2pkg packaging: a standard zip format for cs2-link-manager plugins.

A ``.cs2pkg`` file is a zip archive containing:

* ``cs2pkg.json`` — package metadata (name, version, plugin_type, ini_lines);
* the plugin file tree (an ``addons/`` tree mirroring the CS2 server layout).

This lets plugin authors publish a single, self-describing package that the
tool can install directly (``cs2lm add --pkg file.cs2pkg``) and lets repository
plugins be exported back into a distributable archive (``cs2lm pack``).
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

PKG_META_FILENAME = "cs2pkg.json"
PKG_EXTENSION = ".cs2pkg"


def load_pkg_meta(zip_path: str | Path) -> dict | None:
    """Read ``cs2pkg.json`` from a ``.cs2pkg`` archive.

    Returns ``None`` when the archive is not a readable zip or the metadata
    file is absent/invalid.
    """
    try:
        with zipfile.ZipFile(zip_path) as zf:
            try:
                info = zf.getinfo(PKG_META_FILENAME)
            except KeyError:
                return None
            data = json.loads(zf.read(info).decode("utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError):
        return None


def extract_pkg(zip_path: str | Path, dest_dir: str | Path) -> tuple[Path, dict | None]:
    """Extract a ``.cs2pkg`` archive into ``dest_dir``.

    Returns ``(plugin_root, meta)`` where ``plugin_root`` is the directory
    containing the ``addons/`` tree (or the plugin files) and ``meta`` is the
    parsed ``cs2pkg.json`` (or ``None``). Content packages (``kind ==
    "content"``) return the package root so ``add_content`` can see every
    declared root (``cfg/``, ``overrides/``, ``game/``, ...).
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    meta = load_pkg_meta(zip_path)
    if (meta or {}).get("kind") == "content":
        return dest, meta
    return _find_pkg_root(dest), meta


def find_addons_root(extract_dir: str | Path, max_depth: int = 5) -> Path | None:
    """Recursively find the directory whose ``addons/`` subtree holds the plugin.

    GitHub source zips often nest the compiled output under ``public/addons``,
    ``.Compiled/addons``, ``release/addons`` etc. This walks a limited depth
    and returns the parent directory of the first matching ``addons`` tree, or
    ``None`` when no ``addons/`` directory is found.
    """
    root = Path(extract_dir)
    if not root.is_dir():
        return None
    if (root / "addons").is_dir():
        return root
    for child in sorted(root.rglob("addons")):
        if not child.is_dir():
            continue
        depth = len(child.relative_to(root).parts)
        if depth <= max_depth:
            return child.parent
    return None


def _find_pkg_root(extract_dir: Path) -> Path:
    """Locate the package root after extraction (addons/ tree or wrapper)."""
    addons_root = find_addons_root(extract_dir)
    if addons_root is not None:
        return addons_root
    dirs = sorted(p for p in extract_dir.iterdir() if p.is_dir())
    if len(dirs) == 1:
        child = dirs[0]
        if list(child.glob("*.dll")) or list(child.glob("*.deps.json")):
            return child
        if (child / "bin").exists():
            return child
    return extract_dir


def build_pkg(
    repo: str | Path,
    names: str | list[str],
    out_path: str | Path,
    pack_name: str | None = None,
) -> Path:
    """Package one or more repository entries into a ``.cs2pkg`` file.

    ``names`` may be a single plugin name or a list. When several plugin
    entries are packed together the resulting package is a multi-plugin
    package: ``cs2pkg.json`` carries a ``plugins`` list and the ``addons/``
    trees of every plugin are merged into one archive. Content packages
    (``kind == "content"``) are re-rooted back to their package layout
    (``addons/``, ``cfg/``, ``overrides/``, ...) using the manifest's
    ``roots`` mapping.

    ``out_path`` may be an output directory (the file is written as
    ``<out>/<pack_name>.cs2pkg``) or a full file path. Returns the written
    path.
    """
    from cs2lm.manifest import FILES_DIR, load_manifest, plugin_dir

    if isinstance(names, str):
        names = [names]
    names = [str(n) for n in names]
    if not names:
        raise ValueError("No plugin names given for packaging")

    manifests = [load_manifest(repo, n) for n in names]
    for n, manifest in zip(names, manifests):
        files_root = plugin_dir(repo, n) / FILES_DIR
        if not files_root.is_dir():
            raise FileNotFoundError(
                f"Plugin files not found for '{n}': {files_root}"
            )

    content = manifests[0].get("kind") == "content"
    if content and len(names) > 1:
        raise ValueError("Content packages cannot be combined into one archive.")

    label = pack_name or (names[0] if len(names) == 1 else "plugins")
    out = Path(out_path)
    if out.suffix.lower() != PKG_EXTENSION:
        out = out / f"{label}{PKG_EXTENSION}"
    out.parent.mkdir(parents=True, exist_ok=True)

    if content:
        manifest = manifests[0]
        meta = {
            "kind": "content",
            "name": names[0],
            "version": manifest.get("version", "1.0.0"),
        }
        if manifest.get("roots"):
            meta["roots"] = dict(manifest["roots"])
        if manifest.get("requires_frameworks"):
            meta["requires_frameworks"] = list(manifest["requires_frameworks"])
        if manifest.get("platform") and manifest.get("platform") != "all":
            meta["platform"] = manifest["platform"]
        for field in ("author", "description", "license", "homepage", "repository"):
            if manifest.get(field):
                meta[field] = manifest[field]
    else:
        meta = {
            "name": label,
            "version": manifests[0].get("version", "1.0.0"),
            "plugin_type": manifests[0].get("plugin_type", "css"),
            "ini_lines": manifests[0].get("ini_lines", []),
        }
        if len(names) > 1:
            # Multi-plugin package: keep `name` as a label and declare every
            # contained plugin so `add --pkg` can split them again. `requires`
            # is intentionally not merged because dependencies are per-plugin.
            meta["plugins"] = list(names)
        # Preserve optional metadata so a .cs2pkg round trip keeps author,
        # description, license, homepage, repository and API dependency info.
        first = manifests[0]
        for field in ("author", "description", "license", "homepage", "repository"):
            if first.get(field):
                meta[field] = first[field]
        deps = first.get("dependencies") or {}
        if deps:
            meta["dependencies"] = deps
        requires = first.get("requires")
        if requires:
            if isinstance(requires, dict):
                meta["requires"] = dict(requires)
            else:
                meta["requires"] = list(requires)
        if first.get("api_version") is not None:
            meta["api_version"] = first["api_version"]
        if first.get("entry"):
            meta["entry"] = first["entry"]

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(PKG_META_FILENAME, json.dumps(meta, indent=2) + "\n")
        for n, manifest in zip(names, manifests):
            files_root = plugin_dir(repo, n) / FILES_DIR
            roots = manifest.get("roots") or {}
            for f in sorted(files_root.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(files_root).as_posix()
                    arc = (
                        _content_archive_rel(rel, roots)
                        if content
                        else rel
                    )
                    zf.write(f, arc)
    return out


def _content_archive_rel(rel: str, roots: dict) -> str:
    """Map a content file's ``files/<server-rel>`` path back to a package path.

    Content packages store repository files under ``files/`` mirroring the
    server root (for example ``files/game/csgo/cfg/server.cfg``). When
    packaging, each file is re-rooted to the package layout declared by
    ``roots`` (for example ``cfg/server.cfg``).
    """
    server_rel = rel.removeprefix("files/").lstrip("/")
    for root_name, rel_target in roots.items():
        rel_target = str(rel_target).strip("/")
        if not rel_target:
            continue
        if server_rel == rel_target:
            return str(root_name)
        if server_rel.startswith(rel_target + "/"):
            return f"{root_name}/{server_rel[len(rel_target) + 1:]}"
    return server_rel