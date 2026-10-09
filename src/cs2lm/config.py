"""Repository configuration management."""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_FILENAME = "config.json"
CONFIG_VERSION = 1

# Default plugin source embedded into every new repository. The URL is a
# GitHub repository page; :func:`cs2lm.sources.normalize_source_url` resolves
# it to ``raw.githubusercontent.com/<owner>/<repo>/main/index.json`` at fetch
# time. Users can remove/clear it like any other source.
DEFAULT_SOURCES: list[dict] = [
    {
        "url": "https://github.com/cyqmq/cs2pkg-port",
        "name": "cs2pkg-port",
    },
]


def default_config(repo_path: str | Path, server_path: str | Path, csgo_rel: str) -> dict:
    return {
        "version": CONFIG_VERSION,
        "repo_path": str(Path(repo_path).resolve()),
        "server_path": str(Path(server_path).resolve()),
        "csgo_rel": csgo_rel,
        "sources": [dict(s) for s in DEFAULT_SOURCES],
        # Marks that the embedded default source has been applied, so a later
        # ``source clear`` is not silently re-populated on the next load.
        "default_sources_applied": True,
        "update": {
            "timeout": 30,
            "auto_remove_orphans": False,
            "api_version_range": None,
        },
    }


def _migrate_default_sources(cfg_path: Path, cfg: dict) -> None:
    """One-time migration: add the embedded default source to old repos.

    Only applies when the config has no ``default_sources_applied`` marker and
    no sources configured (repositories created before the default source
    existed). Repositories with custom sources are left untouched (the marker
    is still set so no default is ever injected later). Best-effort: a
    read-only config file simply skips the migration.
    """
    if cfg.get("default_sources_applied"):
        return
    if not (cfg.get("sources") or []):
        cfg["sources"] = [dict(s) for s in DEFAULT_SOURCES]
    cfg["default_sources_applied"] = True
    try:
        cfg_path.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError:
        # Config is read-only: the in-memory copy still has the default
        # source, but we do not persist it.
        pass


def load_config(repo_path: str | Path) -> dict:
    p = Path(repo_path) / CONFIG_FILENAME
    if not p.exists():
        raise FileNotFoundError(f"Repository not initialized: {p}")
    try:
        cfg = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid config file: {p}") from exc
    _migrate_default_sources(p, cfg)
    return cfg


def save_config(repo_path: str | Path, cfg: dict) -> None:
    p = Path(repo_path) / CONFIG_FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")