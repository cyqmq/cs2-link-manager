"""Download and extract a plugin zip package from a URL."""
from __future__ import annotations

import hashlib
import urllib.request
import zipfile
from pathlib import Path

from cs2lm.cs2pkg import find_addons_root


class DownloadError(Exception):
    """Raised when a plugin package cannot be downloaded or extracted."""


def download_and_extract(
    url: str,
    dest_dir: str | Path,
    expected_sha256: str | None = None,
) -> Path:
    """Download a zip from ``url`` and extract it into ``dest_dir``.

    When ``expected_sha256`` is given, the downloaded bytes are verified
    against it before extraction (registry ``--sha256`` integrity check).
    Returns the plugin package root directory inside ``dest_dir`` (a path that
    can be passed to ``manifest.add_plugin``). Raises :class:`DownloadError`
    on network, HTTP, checksum, or zip failures.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest / "download.zip"
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
    except Exception as exc:  # noqa: BLE001 - wrap all network errors
        raise DownloadError(f"Failed to download {url}: {exc}") from exc
    if expected_sha256:
        actual = hashlib.sha256(data).hexdigest()
        if actual.lower() != expected_sha256.lower():
            raise DownloadError(
                f"Checksum mismatch for {url}: expected {expected_sha256}, "
                f"got {actual}."
            )
    try:
        zip_path.write_bytes(data)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest)
    except (OSError, zipfile.BadZipFile) as exc:
        raise DownloadError(f"Failed to extract {url}: {exc}") from exc
    finally:
        zip_path.unlink(missing_ok=True)
    return _find_plugin_root(dest)


def resolve_addons_subdir(extract_dir: str | Path, subdir: str | Path) -> Path:
    """Resolve an explicit ``--addons-subdir`` inside an extracted zip.

    The subdir should be the directory whose ``addons/`` subtree holds the
    plugin (e.g. ``public`` for ``public/addons``). Passing the ``addons``
    directory itself is also accepted and normalized to its parent.
    """
    candidate = Path(extract_dir) / subdir
    if not candidate.is_dir():
        raise ValueError(
            f"--addons-subdir not found in archive: {subdir} (looked at "
            f"{candidate})."
        )
    if (candidate / "addons").is_dir():
        return candidate
    if candidate.name == "addons" and candidate.is_dir():
        return candidate.parent
    raise ValueError(
        f"--addons-subdir {subdir} does not contain an addons/ tree. Point "
        "it at the directory whose addons/ subtree holds the plugin (e.g. "
        "--addons-subdir public for public/addons)."
    )


def _find_plugin_root(extract_dir: Path) -> Path:
    """Locate the package root after extraction.

    The zip may contain the ``addons/`` tree at the top level, a nested
    ``addons/`` (GitHub source zips put build output under ``public/addons``
    or ``.Compiled/addons``), or a single wrapping directory that contains
    the plugin files.
    """
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