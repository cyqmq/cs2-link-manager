"""Install, uninstall, enable and disable plugins.

The installer is the orchestrator: it reads manifests, consults the link
state database, creates/removes links, edits `metaplugins.ini` for Metamod
plugins, and rolls back on failure.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from cs2lm import linking
from cs2lm.config import load_config
from cs2lm.logutil import Logger
from cs2lm.manifest import list_plugins, load_manifest, save_manifest
from cs2lm.paths import resolve_within

STATE_DIR = "state"
STATE_FILENAME = "links.json"
BACKUP_DIRNAME = ".cs2lm-backups"
TRASH_DIRNAME = "trash"


class InstallError(Exception):
    """Raised for user-facing installation errors."""


class PluginManager:
    def __init__(
        self,
        repo: str | Path,
        dry_run: bool = False,
        backup: bool = False,
        force: bool = False,
        yes: bool = False,
        logger: Logger | None = None,
    ):
        self.repo = Path(repo).resolve()
        self.cfg = load_config(self.repo)
        self.server = Path(self.cfg["server_path"]).resolve()
        self.csgo_rel = self.cfg["csgo_rel"]
        self.dry_run = dry_run
        self.backup = backup
        self.force = force
        self.yes = yes
        self.logger = logger or Logger()
        self.state_path = self.repo / STATE_DIR / STATE_FILENAME
        self.trash_dir = self.repo / TRASH_DIRNAME
        self.backup_root = self.server / BACKUP_DIRNAME

    # -- state --------------------------------------------------------------

    def _load_state(self) -> dict:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise InstallError(f"Invalid state file: {self.state_path}") from exc
        return {"links": []}

    def _save_state(self, state: dict) -> None:
        if self.dry_run:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(state, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _state_links_for(self, state: dict, plugin: str) -> list[dict]:
        return [r for r in state.get("links", []) if r.get("plugin") == plugin]

    def _state_has_link(self, state: dict, plugin: str, link: dict) -> bool:
        for rec in self._state_links_for(state, plugin):
            if rec.get("target") == link["target"]:
                return True
        return False

    def plugin_has_links(self, name: str) -> bool:
        state = self._load_state()
        return bool(self._state_links_for(state, name))

    # -- install ------------------------------------------------------------

    def install(self, name: str) -> None:
        manifest = load_manifest(self.repo, name)
        state = self._load_state()
        created: list[dict] = []
        try:
            for link in manifest.get("links", []):
                if self._state_has_link(state, name, link):
                    self.logger.info(
                        "install",
                        f"{name}: link already installed, skipping",
                        target=link["target"],
                    )
                    continue

                source_abs = self.repo / "plugins" / name / link["source"]
                target_abs = resolve_within(self.server, link["target"])

                if not source_abs.exists():
                    raise InstallError(f"Source missing in repository: {source_abs}")

                if linking.path_exists(target_abs):
                    if self._is_managed_link(target_abs, source_abs):
                        self.logger.info(
                            "install",
                            f"{name}: existing link points to repo source, skipping",
                            target=str(target_abs),
                        )
                        continue
                    self._handle_conflict(name, link, target_abs)

                kind_used = linking.create_link(
                    link["kind"],
                    source_abs,
                    target_abs,
                    dry_run=self.dry_run,
                    logger=self.logger,
                )
                record = {
                    "plugin": name,
                    "source": link["source"],
                    "target": link["target"],
                    "kind": link["kind"],
                    "kind_used": kind_used,
                    "created_at": _now(),
                }
                created.append(record)
                if not self.dry_run:
                    state["links"].append(record)

            self._apply_ini_lines(manifest, name, state, install=True)

            if not self.dry_run:
                manifest["enabled"] = True
                manifest["updated_at"] = _now()
                save_manifest(self.repo, name, manifest)
                self._save_state(state)
            self.logger.info("install", f"installed {name}")
        except Exception:
            self._rollback(created)
            raise

    def _is_managed_link(self, target: Path, expected_source: Path) -> bool:
        """Return True if the existing link points at our repo source."""
        if linking.is_link(target):
            try:
                return Path(os.path.realpath(target)).resolve() == expected_source.resolve()
            except OSError:
                return False
        if linking.is_junction(target):
            return Path(target).resolve() == expected_source.resolve()
        return False

    def _handle_conflict(self, name: str, link: dict, target: Path) -> None:
        message = (
            f"target already exists and is not managed by this tool: {target}"
        )
        if self.backup or self.force:
            if not self.yes and not self._confirm():
                raise linking.ConflictError(
                    "Aborted by user. Use --yes to skip confirmation."
                )
            linking.backup_target(
                target,
                self.backup_root,
                self.server,
                dry_run=self.dry_run,
                logger=self.logger,
            )
        else:
            raise linking.ConflictError(
                f"{message}. Use --backup to back it up, or --force to confirm."
            )

    def _confirm(self) -> bool:
        try:
            answer = input("Target is unmanaged. Move it to backup and continue? [y/N] ")
        except (EOFError, OSError):
            return False
        return answer.strip().lower() in ("y", "yes")

    def _rollback(self, created: list[dict]) -> None:
        for rec in reversed(created):
            try:
                target = resolve_within(self.server, rec["target"])
                linking.remove_link(
                    rec.get("kind_used", rec["kind"]),
                    target,
                    trash_dir=self.trash_dir,
                    dry_run=False,
                    logger=self.logger,
                )
                self.logger.warn("rollback", f"rolled back {target}")
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "rollback",
                    f"failed to roll back {rec.get('target')}: {exc}",
                )

    # -- uninstall / disable ------------------------------------------------

    def uninstall(self, name: str) -> None:
        manifest = load_manifest(self.repo, name)
        state = self._load_state()
        plugin_records = self._state_links_for(state, name)
        for rec in plugin_records:
            target = resolve_within(self.server, rec["target"])
            linking.remove_link(
                rec.get("kind_used", rec["kind"]),
                target,
                trash_dir=self.trash_dir,
                dry_run=self.dry_run,
                logger=self.logger,
            )
            if not self.dry_run:
                state["links"].remove(rec)

        self._apply_ini_lines(manifest, name, state, install=False)

        if not self.dry_run:
            manifest["enabled"] = False
            manifest["updated_at"] = _now()
            save_manifest(self.repo, name, manifest)
            self._save_state(state)
        self.logger.info("uninstall", f"uninstalled {name}")

    def enable(self, name: str) -> None:
        self.install(name)

    def disable(self, name: str) -> None:
        self.uninstall(name)

    # -- metaplugins.ini ----------------------------------------------------

    def _apply_ini_lines(self, manifest: dict, name: str, state: dict, install: bool) -> None:
        lines = manifest.get("ini_lines", [])
        if not lines:
            return
        ini_rel = f"{self.csgo_rel}/addons/metamod/metaplugins.ini"
        ini_path = resolve_within(self.server, ini_rel)

        if self.dry_run:
            for line in lines:
                verb = "append" if install else "remove"
                self.logger.action(
                    f"would {verb} metaplugins.ini line '{line}'",
                    file=str(ini_path),
                )
            return

        if install:
            content = ini_path.read_text(encoding="utf-8") if ini_path.exists() else ""
            existing = [ln.strip() for ln in content.splitlines()]
            new_lines = [ln for ln in lines if ln not in existing]
            if new_lines:
                linking.backup_target(
                    ini_path,
                    self.backup_root,
                    self.server,
                    logger=self.logger,
                )
                ini_path.parent.mkdir(parents=True, exist_ok=True)
                block = "\n".join(new_lines)
                if content.strip():
                    content = content.rstrip() + "\n" + block + "\n"
                else:
                    content = block + "\n"
                ini_path.write_text(content, encoding="utf-8")
                self.logger.info(
                    "ini",
                    f"added {len(new_lines)} line(s) to metaplugins.ini",
                    plugin=name,
                )
        else:
            if ini_path.exists():
                content_lines = ini_path.read_text(encoding="utf-8").splitlines()
                remaining = [ln for ln in content_lines if ln.strip() not in lines]
                if len(remaining) != len(content_lines):
                    linking.backup_target(
                        ini_path,
                        self.backup_root,
                        self.server,
                        logger=self.logger,
                    )
                    ini_path.write_text("\n".join(remaining).rstrip() + "\n", encoding="utf-8")
                    self.logger.info(
                        "ini",
                        f"removed {len(content_lines) - len(remaining)} line(s) from "
                        f"metaplugins.ini",
                        plugin=name,
                    )

    # -- listing ------------------------------------------------------------

    def list_plugins(self) -> list[dict]:
        state = self._load_state()
        result = []
        for name in list_plugins(self.repo):
            manifest = load_manifest(self.repo, name)
            installed = bool(self._state_links_for(state, name))
            result.append(
                {
                    "name": name,
                    "type": manifest.get("plugin_type", "?"),
                    "version": manifest.get("version", "?"),
                    "enabled": bool(manifest.get("enabled")),
                    "installed": installed,
                }
            )
        return result


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")