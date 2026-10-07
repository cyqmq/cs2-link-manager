"""Repository configuration management."""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_FILENAME = "config.json"
CONFIG_VERSION = 1


def default_config(repo_path: str | Path, server_path: str | Path, csgo_rel: str) -> dict:
    return {
        "version": CONFIG_VERSION,
        "repo_path": str(Path(repo_path).resolve()),
        "server_path": str(Path(server_path).resolve()),
        "csgo_rel": csgo_rel,
    }


def load_config(repo_path: str | Path) -> dict:
    p = Path(repo_path) / CONFIG_FILENAME
    if not p.exists():
        raise FileNotFoundError(f"Repository not initialized: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid config file: {p}") from exc


def save_config(repo_path: str | Path, cfg: dict) -> None:
    p = Path(repo_path) / CONFIG_FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")