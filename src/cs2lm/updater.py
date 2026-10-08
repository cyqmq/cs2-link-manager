"""Plugin update mechanism using registry sources and SHA-256 comparison.

``cs2lm update [name...]`` downloads each plugin's registry URL, extracts the
new package, computes the new file set (SHA-256 per file), and compares it
against the current manifest:

* no file changed -> "up to date";
* some files changed -> show a diff summary, then (after confirmation)
  replace the repository files, regenerate the manifest, and re-sync the
  server links if the plugin was installed.

Only files that are recorded in the old manifest are removed during an
update — nothing outside the plugin's ``files/`` directory is ever touched.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from cs2lm.config import load_config
from cs2lm.logutil import Logger
from cs2lm.manifest import (
    FILES_DIR,
    _collect_css_links,
    _collect_metamod_links,
    _copy_source,
    _detect_dependencies,
    _now,
    _target_for,
    _validate_no_core_overwrites,
    _walk_files,
    classify_plugin,
    load_manifest,
    plugin_dir,
    save_manifest,
)

_META_FIELDS = ("author", "description", "license", "homepage", "repository")


class UpdateError(Exception):
    """Raised for user-facing update errors."""


def _confirm(prompt: str) -> bool:
    try:
        answer = input(f"{prompt} [y/N]: ").strip().lower()
    except (EOFError, OSError):
        return False
    return answer in ("y", "yes")


def _find_pkg_meta(extract_dir: Path) -> dict | None:
    """Look for a ``cs2pkg.json`` inside the extracted archive."""
    for candidate in sorted(extract_dir.rglob("cs2pkg.json")):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def update_plugin(
    repo: str | Path,
    name: str,
    entry: dict,
    dry_run: bool = False,
    yes: bool = False,
    logger: Logger | None = None,
) -> dict:
    """Update one plugin from its registry entry.

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
                "'cs2lm install <name> --from-registry' to add it first"
            ),
        }

    old_manifest = load_manifest(repo, name)
    cfg = load_config(repo)
    csgo_rel = cfg["csgo_rel"]

    from cs2lm.url_add import download_and_extract, resolve_addons_subdir

    try:
        with tempfile.TemporaryDirectory(prefix="cs2lm-upd-") as tmp:
            tmp_path = Path(tmp)
            source = download_and_extract(
                entry["url"], tmp_path, expected_sha256=entry.get("sha256")
            )
            if entry.get("addons_subdir"):
                source = resolve_addons_subdir(tmp_path, entry["addons_subdir"])

            plugin_type = classify_plugin(source, entry.get("type"))
            plugins = entry.get("plugins") or []
            if len(plugins) > 1:
                from cs2lm.manifest import split_css_plugins

                split_sources = split_css_plugins(source, [name], tmp_path)
                plugin_source = split_sources[0][1]
            else:
                plugin_source = source
            files_root = tmp_path / FILES_DIR
            _copy_source(plugin_type, plugin_source, name, files_root)
            new_files = _walk_files(files_root)
            _validate_no_core_overwrites(new_files)
            for f in new_files:
                f["target"] = _target_for(f["source"], csgo_rel)

            if plugin_type == "css":
                new_links = _collect_css_links(files_root, name, csgo_rel)
                new_ini_lines: list[str] = []
            else:
                new_links, new_ini_lines = _collect_metamod_links(
                    files_root, name, csgo_rel
                )
            new_deps = _detect_dependencies(plugin_type, files_root)

            pkg_meta = _find_pkg_meta(tmp_path)
            new_version = (pkg_meta or entry).get("version") or old_manifest.get(
                "version"
            )

            old_files = old_manifest.get("files", [])
            old_by_source = {f["source"]: f for f in old_files}
            new_by_source = {f["source"]: f for f in new_files}

            added = sorted(set(new_by_source) - set(old_by_source))
            removed = sorted(set(old_by_source) - set(new_by_source))
            changed = sorted(
                s
                for s in set(old_by_source) & set(new_by_source)
                if old_by_source[s].get("sha256") != new_by_source[s].get("sha256")
            )
            unchanged = len(
                [
                    s
                    for s in set(old_by_source) & set(new_by_source)
                    if old_by_source[s].get("sha256") == new_by_source[s].get("sha256")
                ]
            )

            if not added and not removed and not changed:
                logger.info("update", f"{name}: already up to date")
                return {"name": name, "status": "up-to-date"}

            report: dict = {
                "name": name,
                "status": "changed",
                "old_version": old_manifest.get("version"),
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
                f"Update '{name}'? "
                f"({len(added)} added, {len(removed)} removed, "
                f"{len(changed)} changed)"
            ):
                logger.info("update", f"{name}: aborted by user")
                return {"name": name, "status": "aborted"}

            # --- apply: replace repo files with the new package -------------
            files_dir = pdir / FILES_DIR
            for entry_old in old_files:
                old_path = pdir / Path(entry_old["source"])
                if old_path.is_file() or old_path.is_symlink():
                    old_path.unlink()
            if files_dir.is_dir():
                for d in sorted(
                    files_dir.rglob("*"),
                    key=lambda p: len(p.parts),
                    reverse=True,
                ):
                    if d.is_dir() and not any(d.iterdir()):
                        d.rmdir()

            for f in new_files:
                rel = Path(f["source"])
                src = files_root / f["source"].removeprefix("files/")
                dst = pdir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

            # --- regenerate manifest ----------------------------------------
            new_manifest = dict(old_manifest)
            new_manifest.update(
                {
                    "version": new_version or "1.0.0",
                    "plugin_type": plugin_type,
                    "updated_at": _now(),
                    "files": new_files,
                    "links": new_links,
                    "ini_lines": new_ini_lines,
                    "dependencies": new_deps,
                }
            )
            if pkg_meta:
                for field in _META_FIELDS:
                    if pkg_meta.get(field):
                        new_manifest[field] = pkg_meta[field]
                if isinstance(pkg_meta.get("dependencies"), dict):
                    for assembly, req in pkg_meta["dependencies"].items():
                        new_manifest["dependencies"].setdefault(assembly, req)
                if isinstance(pkg_meta.get("requires"), (list, tuple)) and pkg_meta["requires"]:
                    new_manifest["requires"] = [str(r) for r in pkg_meta["requires"]]
            save_manifest(repo, name, new_manifest)

            # --- re-sync server links if the plugin was installed ----------
            from cs2lm.installer import PluginManager

            manager = PluginManager(repo, logger=logger)
            was_installed = manager.plugin_has_links(name)
            if was_installed:
                manager.uninstall(name)
                manager.install(name)
                report["reinstalled"] = True
            else:
                report["reinstalled"] = False

            logger.info(
                "update",
                f"{name}: updated "
                f"({len(added)} added, {len(removed)} removed, "
                f"{len(changed)} changed)",
            )
            return report

    except Exception as exc:  # noqa: BLE001 - wrap for the CLI
        logger.error("update", f"{name}: update failed: {exc}")
        return {"name": name, "status": "error", "message": str(exc)}