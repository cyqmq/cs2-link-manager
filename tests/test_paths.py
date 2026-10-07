from pathlib import Path

import pytest

from cs2lm.paths import find_csgo_rel, resolve_within, safe_rel


def test_resolve_within_accepts_valid(tmp_path):
    root = tmp_path / "server"
    (root / "game" / "csgo").mkdir(parents=True)
    result = resolve_within(root, "game/csgo/addons")
    assert result == (root / "game" / "csgo" / "addons")


def test_resolve_within_rejects_escape(tmp_path):
    root = tmp_path / "server"
    root.mkdir()
    with pytest.raises(ValueError):
        resolve_within(root, "../outside")


def test_resolve_within_rejects_absolute(tmp_path):
    root = tmp_path / "server"
    root.mkdir()
    with pytest.raises(ValueError):
        resolve_within(root, str(tmp_path / "outside"))


def test_resolve_within_does_not_follow_symlink(tmp_path):
    root = tmp_path / "server"
    (root / "game" / "csgo").mkdir(parents=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    # a symlink that points outside the server root must still be "inside"
    # logically, so install/uninstall can manage it
    (root / "game" / "csgo" / "linkdir").symlink_to(repo, target_is_directory=True)
    result = resolve_within(root, "game/csgo/linkdir")
    assert result.name == "linkdir"


def test_find_csgo_rel(tmp_path):
    server = tmp_path / "server"
    (server / "game" / "csgo").mkdir(parents=True)
    assert find_csgo_rel(server) == "game/csgo"


def test_find_csgo_rel_flat(tmp_path):
    server = tmp_path / "server"
    (server / "csgo").mkdir(parents=True)
    assert find_csgo_rel(server) == "csgo"


def test_find_csgo_rel_default(tmp_path):
    server = tmp_path / "server"
    server.mkdir()
    assert find_csgo_rel(server) == "game/csgo"


def test_safe_rel_rejects_unsafe():
    with pytest.raises(ValueError):
        safe_rel("../evil")
    with pytest.raises(ValueError):
        safe_rel("/abs/path")
    assert safe_rel("a/b/c") == "a/b/c"