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
    parsed ``cs2pkg.json`` (or ``None``).
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    meta = load_pkg_meta(zip_path)
    return _find_pkg_root(dest), meta


def _find_pkg_root(extract_dir: Path) -> Path:
    """Locate the package root after extraction (addons/ tree or wrapper)."""
    if (extract_dir / "addons").is_dir():
        return extract_dir
    dirs = sorted(p for p in extract_dir.iterdir() if p.is_dir())
    if len(dirs) == 1:
        child = dirs[0]
        if (child / "addons").is_dir():
            return child
        if list(child.glob("*.dll")) or list(child.glob("*.deps.json")):
            return child
        if (child / "bin").exists():
            return child
    return extract_dir


def build_pkg(repo: str | Path, name: str, out_path: str | Path) -> Path:
    """Package a repository plugin into a ``.cs2pkg`` file.

    ``out_path`` may be an output directory (the file is written as
    ``<out>/<Name>.cs2pkg``) or a full file path. Returns the written path.
    """
    from cs2lm.manifest import FILES_DIR, load_manifest, plugin_dir

    manifest = load_manifest(repo, name)
    files_root = plugin_dir(repo, name) / FILES_DIR
    if not files_root.is_dir():
        raise FileNotFoundError(f"Plugin files not found: {files_root}")

    out = Path(out_path)
    if out.suffix.lower() != PKG_EXTENSION:
        out = out / f"{name}{PKG_EXTENSION}"
    out.parent.mkdir(parents=True, exist_ok=True)

    meta = {
        "name": name,
        "version": manifest.get("version", "1.0.0"),
        "plugin_type": manifest.get("plugin_type", "css"),
        "ini_lines": manifest.get("ini_lines", []),
    }
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(PKG_META_FILENAME, json.dumps(meta, indent=2) + "\n")
        for f in sorted(files_root.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(files_root).as_posix())
    return out