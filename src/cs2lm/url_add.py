"""Download and extract a plugin zip package from a URL."""
from __future__ import annotations

import urllib.request
import zipfile
from pathlib import Path


class DownloadError(Exception):
    """Raised when a plugin package cannot be downloaded or extracted."""


def download_and_extract(url: str, dest_dir: str | Path) -> Path:
    """Download a zip from ``url`` and extract it into ``dest_dir``.

    Returns the plugin package root directory inside ``dest_dir`` (a path that
    can be passed to ``manifest.add_plugin``). Raises :class:`DownloadError`
    on network, HTTP, or zip failures.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest / "download.zip"
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
    except Exception as exc:  # noqa: BLE001 - wrap all network errors
        raise DownloadError(f"Failed to download {url}: {exc}") from exc
    try:
        zip_path.write_bytes(data)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest)
    except (OSError, zipfile.BadZipFile) as exc:
        raise DownloadError(f"Failed to extract {url}: {exc}") from exc
    finally:
        zip_path.unlink(missing_ok=True)
    return _find_plugin_root(dest)


def _find_plugin_root(extract_dir: Path) -> Path:
    """Locate the package root after extraction.

    The zip may contain the ``addons/`` tree at the top level, or a single
    wrapping directory that itself contains ``addons/`` or the plugin files.
    """
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