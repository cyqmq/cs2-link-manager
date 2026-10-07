"""Shared fixtures for cs2lm tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cs2lm.config import default_config, save_config  # noqa: E402


GAMEINFO_GI = """\
"GameInfo"
{
	FileSystem
	{
		SearchPaths
		{
			Game	csgo
			Game	csgo/addons/metamod
		}
	}
}
"""


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

    # A realistic server layout: engine config with Metamod wired in,
    # Metamod native binaries + CounterStrikeSharp loader vdf, and CSS API.
    # CS2 loads Metamod from bin/linuxsteamrt64/metamod.2.cs2.so (Linux)
    # and bin/win64/metamod.2.cs2.dll (Windows).
    (server / "game" / "csgo" / "gameinfo.gi").write_text(GAMEINFO_GI, encoding="utf-8")
    (server / "game" / "csgo" / "addons" / "metamod" / "bin" / "linuxsteamrt64").mkdir(parents=True, exist_ok=True)
    (server / "game" / "csgo" / "addons" / "metamod" / "bin" / "win64").mkdir(parents=True, exist_ok=True)
    (server / "game" / "csgo" / "addons" / "metamod" / "bin" / "linuxsteamrt64" / "metamod.2.cs2.so").write_bytes(b"\x7fELF")
    (server / "game" / "csgo" / "addons" / "metamod" / "bin" / "win64" / "metamod.2.cs2.dll").write_bytes(b"MZ")
    (server / "game" / "csgo" / "addons" / "metamod" / "counterstrikesharp.vdf").write_text(
        '"Plugin"\n{\n\t"file"\t"counterstrikesharp/bin/linux64/CounterStrikeSharp"\n}\n',
        encoding="utf-8",
    )
    css_api = server / "game" / "csgo" / "addons" / "counterstrikesharp" / "api"
    css_api.mkdir(parents=True, exist_ok=True)
    (css_api / "CounterStrikeSharp.API.dll").write_bytes(b"MZ")
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