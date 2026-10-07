"""Profile management: named sets of plugins that can be switched at once."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from cs2lm.installer import PluginManager
from cs2lm.logutil import Logger
from cs2lm.manifest import list_plugins, load_manifest, sanitize_name

PROFILE_DIR = "profiles"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def profile_path(repo: str | Path, name: str) -> Path:
    return Path(repo) / PROFILE_DIR / f"{sanitize_name(name)}.json"


def list_profiles(repo: str | Path) -> list[str]:
    base = Path(repo) / PROFILE_DIR
    if not base.is_dir():
        return []
    return sorted(p.stem for p in base.glob("*.json"))


def get_profile(repo: str | Path, name: str) -> dict:
    p = profile_path(repo, name)
    if not p.exists():
        raise FileNotFoundError(f"Profile not found: {name}")
    return json.loads(p.read_text(encoding="utf-8"))


def create_profile(repo: str | Path, name: str, plugins: list[str]) -> dict:
    name = sanitize_name(name)
    p = profile_path(repo, name)
    if p.exists():
        raise FileExistsError(f"Profile already exists: {name}")
    # validate plugin names exist in the repository
    available = set(list_plugins(repo))
    unknown = [pn for pn in plugins if pn not in available]
    if unknown:
        raise ValueError(
            f"Unknown plugin(s) in profile: {', '.join(unknown)}. "
            f"Available: {', '.join(sorted(available)) or '(none)'}"
        )
    profile = {
        "name": name,
        "plugins": list(dict.fromkeys(plugins)),  # preserve order, dedupe
        "created_at": _now(),
        "updated_at": _now(),
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return profile


def delete_profile(repo: str | Path, name: str) -> None:
    p = profile_path(repo, name)
    if not p.exists():
        raise FileNotFoundError(f"Profile not found: {name}")
    p.unlink()


def use_profile(
    repo: str | Path,
    name: str,
    manager: PluginManager,
    logger: Logger | None = None,
) -> dict:
    """Switch to a profile: enable plugins in the profile, disable others."""
    logger = logger or Logger()
    profile = get_profile(repo, name)
    wanted = set(profile["plugins"])
    all_plugins = list_plugins(repo)

    enabled_count = 0
    disabled_count = 0

    for plugin in profile["plugins"]:
        manifest = load_manifest(repo, plugin)
        if not manifest.get("enabled"):
            manager.enable(plugin)
            enabled_count += 1

    for plugin in all_plugins:
        if plugin in wanted:
            continue
        manifest = load_manifest(repo, plugin)
        if manifest.get("enabled") or manager.plugin_has_links(plugin):
            manager.disable(plugin)
            disabled_count += 1

    logger.info(
        "profile",
        f"switched to profile '{name}' "
        f"(enabled {enabled_count}, disabled {disabled_count})",
    )
    return {"profile": name, "enabled": enabled_count, "disabled": disabled_count}