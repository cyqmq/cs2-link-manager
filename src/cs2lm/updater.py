"""Index-based plugin update mechanism.

``cs2lm update`` keeps locally installed plugins current (see
``docs/INDEX.md`` for the index schema):

1. fetch every configured source's ``index.json`` (ETag-cached),
2. merge them into one "latest available plugin table",
3. scan local plugin manifests to learn each plugin's current version,
4. compare: remote newer -> update, same/higher -> skip,
5. plugins absent from every source are orphans (kept or removed),
6. execute updates with staged, atomic directory replacement.

Missing plugins are **reported, not installed**: ``cs2lm update`` only lists
them and points the user to ``cs2lm install <name>``, which pulls a plugin
straight from the merged index (dependencies included). See
``cs2lm.catalog`` for the browse-and-install flow.

A plugin directory is replaced atomically: the new package is built in a
temporary repository, copied to ``.<name>.new``, then the current directory
is renamed to ``.<name>.old`` and the staging directory is renamed into
place — a failed rename rolls back from ``.old``.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cs2lm.config import load_config
from cs2lm.installer import PluginManager
from cs2lm.logutil import Logger
from cs2lm.manifest import (
    add_plugin,
    list_plugins,
    load_manifest,
    plugin_dir,
    sanitize_name,
    save_manifest,
)
from cs2lm.url_add import DownloadError, download_and_extract, resolve_addons_subdir
from cs2lm.versions import version_gt

_META_FIELDS = ("author", "description", "license", "homepage", "repository")
_PKG_META_FILENAMES = ("manifest.json", "cs2pkg.json")


class UpdateError(Exception):
    """Raised for user-facing update errors."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _confirm(prompt: str) -> bool:
    try:
        answer = input(f"{prompt} [y/N]: ").strip().lower()
    except (EOFError, OSError):
        return False
    return answer in ("y", "yes")


def _find_pkg_meta(extract_dir: Path) -> dict | None:
    """Look for the package's authoritative manifest.

    Searches for ``manifest.json`` (index.json spec) or ``cs2pkg.json``
    (legacy .cs2pkg metadata) anywhere under the extracted archive.
    """
    for filename in _PKG_META_FILENAMES:
        for candidate in sorted(extract_dir.rglob(filename)):
            try:
                data = json.loads(candidate.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                return data
    return None


def _validate_pkg_identity(
    pkg_meta: dict | None, name: str, version: str | None
) -> None:
    """Ensure the downloaded package matches the index entry (id/version)."""
    if not pkg_meta:
        return
    pkg_id = pkg_meta.get("id") or pkg_meta.get("name")
    if pkg_id and sanitize_name(str(pkg_id)) != sanitize_name(name):
        raise UpdateError(
            f"Package id mismatch: index says '{name}', package manifest "
            f"says '{pkg_id}'. Refusing to install an inconsistent package."
        )
    pkg_version = pkg_meta.get("version")
    if pkg_version and version and str(pkg_version) != str(version):
        raise UpdateError(
            f"Package version mismatch: index says {version}, package "
            f"manifest says {pkg_version}. Refusing to install an "
            "inconsistent package."
        )


def _resolve_plugin_source(
    entry: dict, source: Path, name: str, tmp_path: Path
) -> Path:
    """For a multi-plugin package, return only the target plugin's addons tree."""
    plugins = entry.get("plugins") or []
    if len(plugins) > 1:
        from cs2lm.manifest import split_css_plugins

        split_sources = split_css_plugins(source, [name], tmp_path)
        return split_sources[0][1]
    return source


# ---------------------------------------------------------------------------
# Local scan & action computation
# ---------------------------------------------------------------------------


def scan_local(repo: str | Path) -> dict[str, str]:
    """Map plugin id -> installed version from local manifests."""
    result: dict[str, str] = {}
    for name in list_plugins(repo):
        try:
            manifest = load_manifest(repo, name)
            result[name] = str(manifest.get("version") or "1.0.0")
        except Exception:  # noqa: BLE001 - skip unreadable manifests
            continue
    return result


def expand_requires(
    merged: dict, names: list[str], local: dict[str, str]
) -> list[str]:
    """Return ``names`` plus missing required plugins, dependencies first.

    Required plugins are resolved recursively from the merged index and
    ordered before their dependents so ``manager.install`` never trips over
    an absent dependency.  Cycles are skipped defensively (the installer
    reports a real dependency cycle error).
    """
    result: list[str] = []
    visited: set[str] = set()

    def visit(plugin_id: str, stack: set[str]) -> None:
        if plugin_id in visited:
            return
        if plugin_id in stack:
            return  # cycle guard
        stack.add(plugin_id)
        entry = merged.get(plugin_id, {})
        req = entry.get("requires") or {}
        if isinstance(req, dict):
            deps = [str(k) for k in req.keys()]
        elif isinstance(req, (list, tuple)):
            deps = [str(r) for r in req]
        else:
            deps = []
        for dep in deps:
            if dep not in local:
                visit(dep, stack)
        stack.discard(plugin_id)
        if plugin_id not in local:
            visited.add(plugin_id)
            result.append(plugin_id)

    for name in names:
        visit(name, set())
    return result


def compute_actions(
    merged: dict, local: dict[str, str]
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Compare merged remote plugins against local manifests.

    Returns ``(install, update, skip, orphans)``:
    * remote has it, local missing -> install;
    * remote version > local -> update;
    * remote version <= local -> skip;
    * local only -> orphan.
    """
    install: list[str] = []
    update: list[str] = []
    skip: list[str] = []
    for plugin_id in sorted(merged):
        version = str(merged[plugin_id].get("version") or "")
        if plugin_id not in local:
            install.append(plugin_id)
        elif version_gt(version, local[plugin_id]):
            update.append(plugin_id)
        else:
            skip.append(plugin_id)
    orphans = sorted(set(local) - set(merged))
    return install, update, skip, orphans


# ---------------------------------------------------------------------------
# Update log
# ---------------------------------------------------------------------------


def _log_update(repo: str | Path, record: dict) -> None:
    path = Path(repo) / "state" / "update_log.json"
    logs: list[dict] = []
    if path.exists():
        try:
            logs = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            logs = []
    logs.append(record)
    path.write_text(
        json.dumps(logs, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Installing from the merged index
# ---------------------------------------------------------------------------


def install_plugin_from_index(
    repo: str | Path,
    name: str,
    entry: dict,
    dry_run: bool = False,
    manager=None,
    logger: Logger | None = None,
) -> dict:
    """Download, verify and add a plugin that is missing locally."""
    logger = logger or Logger()
    if dry_run:
        return {
            "name": name,
            "status": "would-install",
            "version": entry.get("version"),
            "dry_run": True,
        }
    url = entry.get("download_url") or entry.get("url")
    try:
        with tempfile.TemporaryDirectory(prefix="cs2lm-inst-") as tmp:
            tmp_path = Path(tmp)
            source = download_and_extract(
                url,
                tmp_path,
                expected_sha256=entry.get("sha256"),
                headers=entry.get("headers") or {},
                timeout=int(entry.get("timeout") or 60),
            )
            if entry.get("addons_subdir"):
                source = resolve_addons_subdir(tmp_path, entry["addons_subdir"])
            pkg_meta = _find_pkg_meta(tmp_path)
            _validate_pkg_identity(pkg_meta, name, str(entry.get("version") or ""))
            source = _resolve_plugin_source(entry, source, name, tmp_path)
            add_plugin(
                repo,
                name,
                source,
                type_hint=entry.get("plugin_type") or entry.get("type"),
                version=entry.get("version"),
                meta=entry,
            )
        manager = manager or PluginManager(repo, logger=logger)
        manager.install(name)
        _log_update(
            repo,
            {
                "id": name,
                "action": "install",
                "old_version": None,
                "new_version": entry.get("version"),
                "source": entry.get("source"),
                "status": "ok",
                "timestamp": _now(),
            },
        )
        return {"name": name, "status": "installed", "version": entry.get("version")}
    except Exception as exc:  # noqa: BLE001 - wrap for the CLI
        logger.error("update", f"{name}: install failed: {exc}")
        return {"name": name, "status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# Updating an existing plugin (atomic directory replacement)
# ---------------------------------------------------------------------------


def update_plugin(
    repo: str | Path,
    name: str,
    entry: dict,
    dry_run: bool = False,
    yes: bool = False,
    logger: Logger | None = None,
) -> dict:
    """Update one plugin from its index/registry entry.

    Returns a report dict with ``status`` in
    ``{"up-to-date", "changed", "aborted", "not-in-repo", "error"}``.
    ``dry_run`` only reports; ``yes`` skips the confirmation prompt.
    """
    logger = logger or Logger()
    pdir = plugin_dir(repo, name)
    if not pdir.exists():
        return {
            "name": name,
            "status": "not-in-repo",
            "message": (
                "plugin is not in the repository; use "
                "'cs2lm install <name>' to install it from the index first"
            ),
        }

    old_manifest = load_manifest(repo, name)
    old_version = old_manifest.get("version")
    new_version = str(entry.get("version") or old_version or "1.0.0")
    url = entry.get("download_url") or entry.get("url")

    try:
        with tempfile.TemporaryDirectory(prefix="cs2lm-upd-") as tmp:
            tmp_path = Path(tmp)
            source = download_and_extract(
                url,
                tmp_path,
                expected_sha256=entry.get("sha256"),
                headers=entry.get("headers") or {},
                timeout=int(entry.get("timeout") or 60),
            )
            if entry.get("addons_subdir"):
                source = resolve_addons_subdir(tmp_path, entry["addons_subdir"])
            pkg_meta = _find_pkg_meta(tmp_path)
            _validate_pkg_identity(pkg_meta, name, new_version)
            source = _resolve_plugin_source(entry, source, name, tmp_path)

            # Build the new plugin directory inside a throwaway repository.
            build_repo = tmp_path / "build-repo"
            (build_repo / "plugins").mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(repo) / "config.json", build_repo / "config.json")
            new_manifest = add_plugin(
                build_repo,
                name,
                source,
                type_hint=entry.get("plugin_type") or entry.get("type"),
                version=new_version,
                meta=entry,
            )
            # Carry over metadata that the index does not provide.
            for field in _META_FIELDS:
                if not new_manifest.get(field) and old_manifest.get(field):
                    new_manifest[field] = old_manifest[field]
                save_manifest(build_repo, name, new_manifest)

            old_files = {f["source"]: f for f in old_manifest.get("files", [])}
            new_files = {f["source"]: f for f in new_manifest["files"]}
            added = sorted(set(new_files) - set(old_files))
            removed = sorted(set(old_files) - set(new_files))
            changed = sorted(
                s
                for s in set(old_files) & set(new_files)
                if old_files[s].get("sha256") != new_files[s].get("sha256")
            )
            unchanged = len(
                [
                    s
                    for s in set(old_files) & set(new_files)
                    if old_files[s].get("sha256") == new_files[s].get("sha256")
                ]
            )

            if not added and not removed and not changed and str(old_version) == str(new_version):
                logger.info("update", f"{name}: already up to date")
                return {"name": name, "status": "up-to-date"}

            report: dict = {
                "name": name,
                "status": "changed",
                "old_version": old_version,
                "new_version": new_version,
                "added": added,
                "removed": removed,
                "changed": changed,
                "unchanged": unchanged,
            }

            if dry_run:
                report["dry_run"] = True
                return report

            if not yes and not _confirm(
                f"Update '{name}' {old_version} -> {new_version}? "
                f"({len(added)} added, {len(removed)} removed, "
                f"{len(changed)} changed)"
            ):
                logger.info("update", f"{name}: aborted by user")
                return {"name": name, "status": "aborted"}

            _atomic_replace(repo, name, build_repo, tmp_path)

            from cs2lm.installer import PluginManager

            manager = PluginManager(repo, logger=logger)
            was_installed = manager.plugin_has_links(name)
            if was_installed:
                manager.uninstall(name)
                manager.install(name)
                report["reinstalled"] = True
            else:
                report["reinstalled"] = False

            _log_update(
                repo,
                {
                    "id": name,
                    "action": "update",
                    "old_version": old_version,
                    "new_version": new_version,
                    "source": entry.get("source"),
                    "status": "ok",
                    "timestamp": _now(),
                },
            )

            logger.info(
                "update",
                f"{name}: updated {old_version} -> {new_version} "
                f"({len(added)} added, {len(removed)} removed, "
                f"{len(changed)} changed)",
            )
            return report

    except Exception as exc:  # noqa: BLE001 - wrap for the CLI
        logger.error("update", f"{name}: update failed: {exc}")
        return {"name": name, "status": "error", "message": str(exc)}


def _atomic_replace(
    repo: str | Path,
    name: str,
    build_repo: Path,
    tmp_path: Path,
) -> None:
    """Swap ``plugins/<name>`` with the freshly built package.

    The new directory is copied to ``.<name>.new``, the live directory is
    renamed to ``.<name>.old``, the staging directory is renamed into place,
    and ``.old`` is removed.  A failed swap rolls back from ``.old``.
    """
    plugins_root = plugin_dir(repo, name).parent
    staging = plugins_root / f".{name}.new"
    old_dir = plugins_root / f".{name}.old"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(old_dir, ignore_errors=True)

    built = build_repo / "plugins" / name
    shutil.copytree(built, staging)
    pdir = plugin_dir(repo, name)
    pdir.rename(old_dir)
    try:
        staging.rename(pdir)
    except Exception:
        # Roll back so the previous version stays intact.
        old_dir.rename(pdir)
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(old_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Orphan removal
# ---------------------------------------------------------------------------


def remove_orphans(
    repo: str | Path,
    names: list[str],
    manager=None,
    logger: Logger | None = None,
) -> list[str]:
    """Uninstall and move orphaned plugin dirs into the repo trash."""
    from cs2lm.installer import PluginManager

    logger = logger or Logger()
    manager = manager or PluginManager(repo, logger=logger)
    removed: list[str] = []
    for name in sorted(names):
        try:
            if manager.plugin_has_links(name):
                manager.uninstall(name)
            pdir = plugin_dir(repo, name)
            if pdir.exists():
                trash = Path(repo) / "trash" / "plugins"
                trash.mkdir(parents=True, exist_ok=True)
                dest = trash / f"{name}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                shutil.move(str(pdir), str(dest))
            _log_update(
                repo,
                {
                    "id": name,
                    "action": "remove-orphan",
                    "old_version": None,
                    "new_version": None,
                    "source": None,
                    "status": "ok",
                    "timestamp": _now(),
                },
            )
            removed.append(name)
        except Exception as exc:  # noqa: BLE001
            logger.error("update", f"{name}: orphan removal failed: {exc}")
    return removed