"""Shared fixtures for cs2lm tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cs2lm.config import default_config, save_config  # noqa: E402


def make_server(tmp_path: Path) -> Path:
    server = tmp_path / "server"
    dirs = [
        "game/csgo/addons/counterstrikesharp/plugins",
        "game/csgo/addons/counterstrikesharp/configs/plugins",
        "game/csgo/addons/counterstrikesharp/gamedata",
        "game/csgo/addons/counterstrikesharp/lang",
        "game/csgo/addons/metamod",
    ]
    for d in dirs:
        (server / d).mkdir(parents=True, exist_ok=True)
    return server


def init_repo(tmp_path: Path, repo_name: str = "repo", server: Path | None = None) -> Path:
    repo = tmp_path / repo_name
    for d in ("plugins", "profiles", "state"):
        (repo / d).mkdir(parents=True, exist_ok=True)
    server = server or make_server(tmp_path)
    save_config(repo, default_config(repo, server, "game/csgo"))
    return repo


@pytest.fixture
def repo_server(tmp_path):
    server = make_server(tmp_path)
    repo = init_repo(tmp_path, server=server)
    return repo, server


def make_css_package(tmp_path: Path, name: str = "TestPlugin", with_configs: bool = True) -> Path:
    pkg = tmp_path / name
    (pkg / "addons" / "counterstrikesharp" / "plugins" / name).mkdir(parents=True)
    (pkg / "addons" / "counterstrikesharp" / "plugins" / name / f"{name}.dll").write_bytes(b"MZ")
    (pkg / "addons" / "counterstrikesharp" / "plugins" / name / f"{name}.deps.json").write_text("{}")
    if with_configs:
        (pkg / "addons" / "counterstrikesharp" / "configs" / "plugins" / name).mkdir(parents=True)
        (pkg / "addons" / "counterstrikesharp" / "configs" / "plugins" / name / f"{name}.json").write_text("{}")
    return pkg


@pytest.fixture
def css_package(tmp_path):
    return make_css_package(tmp_path, "TestPlugin")


@pytest.fixture
def css_package_b(tmp_path):
    return make_css_package(tmp_path, "OtherPlugin")