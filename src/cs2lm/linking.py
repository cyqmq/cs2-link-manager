"""Create and remove links (symlink / junction / copy) safely.

Cross-platform strategy:
  * Linux: ``os.symlink`` for files and directories.
  * Windows: try ``os.symlink`` first; on failure fall back to a directory
    junction (``mklink /J``), then to a plain copy. The user is warned about
    the permission requirement (Administrator or Developer Mode) when a
    symlink cannot be created.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from cs2lm.logutil import Logger


class LinkError(Exception):
    """Raised when a link operation fails."""


class ConflictError(LinkError):
    """Raised when a target already exists and is not managed by the tool."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_link(path: str | Path) -> bool:
    try:
        return os.path.islink(path)
    except OSError:
        return False


def is_junction(path: str | Path) -> bool:
    """Best-effort detection of Windows directory junctions/reparse points."""
    if sys.platform != "win32":
        return False
    try:
        st = os.lstat(path)
        return bool(getattr(st, "st_file_attributes", 0) & 0x400)  # REPARSE_POINT
    except OSError:
        return False


def path_exists(path: str | Path) -> bool:
    return Path(path).exists() or is_link(path) or is_junction(path)


def create_link(
    kind: str,
    source: Path,
    target: Path,
    dry_run: bool = False,
    logger: Logger | None = None,
) -> str:
    """Create a link of the given kind. Returns the kind actually used."""
    logger = logger or Logger()
    if kind in ("symlink-dir", "symlink-file"):
        return _create_symlink(kind == "symlink-dir", source, target, dry_run, logger)
    if kind == "copy":
        return _copy(source, target, dry_run, logger)
    raise LinkError(f"Unknown link kind: {kind}")


def _create_symlink(
    is_dir: bool,
    source: Path,
    target: Path,
    dry_run: bool,
    logger: Logger,
) -> str:
    if dry_run:
        logger.action(f"would create symlink {target} -> {source}")
        return "symlink"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(str(source), str(target), target_is_directory=is_dir)
        return "symlink"
    except OSError as exc:
        if sys.platform == "win32" and is_dir:
            try:
                return _create_junction(source, target, logger)
            except Exception as junc_exc:  # noqa: BLE001
                logger.warn(
                    "link",
                    "directory symlink failed and junction also failed "
                    f"({junc_exc}); falling back to copy mode",
                    target=str(target),
                )
        if sys.platform == "win32":
            logger.warn(
                "link",
                f"symlink creation failed ({exc}); falling back to copy mode. "
                "On Windows, run as Administrator or enable Developer Mode to "
                "create real symlinks.",
                target=str(target),
            )
            return _copy(source, target, dry_run, logger)
        raise LinkError(
            f"Failed to create symlink {target} -> {source}: {exc}"
        ) from exc


def _create_junction(source: Path, target: Path, logger: Logger) -> str:
    cmd = ["cmd", "/c", "mklink", "/J", str(target), str(source)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise LinkError(
            f"junction creation failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    logger.info("link", f"created directory junction {target} -> {source}")
    return "junction"


def _copy(source: Path, target: Path, dry_run: bool, logger: Logger) -> str:
    if dry_run:
        logger.action(f"would copy {source} -> {target}")
        return "copy"
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        shutil.copy2(source, target)
    logger.info("link", f"copied {source} -> {target}")
    return "copy"


def remove_link(
    kind: str,
    target: Path,
    trash_dir: Path | None = None,
    dry_run: bool = False,
    logger: Logger | None = None,
) -> None:
    """Remove a link created by the tool.

    * symlink / junction: remove only the link itself, never the contents.
    * copy: move the copied file/directory into ``trash_dir`` instead of
      hard-deleting it, so data can be recovered.
    """
    logger = logger or Logger()
    if dry_run:
        logger.action(f"would remove {kind} {target}")
        return

    if not path_exists(target):
        logger.warn("remove", f"target does not exist: {target}")
        return

    if kind == "copy":
        if trash_dir is None:
            raise LinkError("trash_dir is required to remove copy-kind links")
        trash_dir.mkdir(parents=True, exist_ok=True)
        dest = _unique_path(trash_dir / target.name)
        shutil.move(str(target), str(dest))
        logger.info("remove", f"moved copy {target} -> {dest}")
        return

    # symlink or junction: remove only the link itself.
    removed = False
    try:
        os.unlink(target)
        removed = True
    except OSError:
        pass
    if not removed:
        try:
            os.rmdir(target)
            removed = True
        except OSError as exc:
            raise LinkError(
                f"Failed to remove link {target}. It may have been replaced by "
                f"real content; refusing to delete unmanaged data. ({exc})"
            ) from exc
    logger.info("remove", f"removed {kind} {target}")


def _unique_path(path: Path) -> Path:
    if not path_exists(path):
        return path
    counter = 1
    while True:
        candidate = path.with_name(f"{path.name}.{counter}")
        if not path_exists(candidate):
            return candidate
        counter += 1


def backup_target(
    target: Path,
    backup_root: Path,
    server_root: Path,
    dry_run: bool = False,
    logger: Logger | None = None,
) -> None:
    """Move an unmanaged target to a timestamped backup location."""
    logger = logger or Logger()
    server_abs = Path(os.path.abspath(server_root))
    rel = target.relative_to(server_abs)
    dest = backup_root / _now().replace(":", "-") / rel
    if dry_run:
        logger.action(f"would back up unmanaged target {target} -> {dest}")
        return
    if not path_exists(target):
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(target), str(dest))
    logger.info("backup", f"backed up {target} -> {dest}")