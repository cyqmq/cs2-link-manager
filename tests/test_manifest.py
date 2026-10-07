from pathlib import Path

import pytest

from cs2lm.manifest import (
    add_plugin,
    classify_plugin,
    list_plugins,
    sanitize_name,
)

from conftest import make_css_package


def test_add_css_package_with_addons_tree(repo_server, tmp_path):
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "TestPlugin")
    manifest = add_plugin(repo, "TestPlugin", pkg)

    assert manifest["plugin_type"] == "css"
    assert manifest["enabled"] is True
    targets = {f["target"] for f in manifest["files"]}
    assert (
        "game/csgo/addons/counterstrikesharp/plugins/TestPlugin/TestPlugin.dll"
        in targets
    )
    assert (
        "game/csgo/addons/counterstrikesharp/configs/plugins/TestPlugin/TestPlugin.json"
        in targets
    )

    link_targets = {l["target"] for l in manifest["links"]}
    assert "game/csgo/addons/counterstrikesharp/plugins/TestPlugin" in link_targets
    assert "game/csgo/addons/counterstrikesharp/configs/plugins/TestPlugin" in link_targets
    assert all(l["kind"] == "symlink-dir" for l in manifest["links"])


def test_add_css_plugin_folder_without_addons(repo_server, tmp_path):
    repo, _server = repo_server
    pkg = tmp_path / "Hello"
    pkg.mkdir()
    (pkg / "Hello.dll").write_bytes(b"MZ")
    (pkg / "Hello.deps.json").write_text("{}")

    manifest = add_plugin(repo, "Hello", pkg)
    assert manifest["plugin_type"] == "css"
    assert manifest["links"] == [
        {
            "source": "files/addons/counterstrikesharp/plugins/Hello",
            "target": "game/csgo/addons/counterstrikesharp/plugins/Hello",
            "kind": "symlink-dir",
        }
    ]
    assert (
        "game/csgo/addons/counterstrikesharp/plugins/Hello/Hello.dll"
        in {f["target"] for f in manifest["files"]}
    )


def test_add_plugin_duplicate_raises(repo_server, tmp_path):
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "TestPlugin")
    add_plugin(repo, "TestPlugin", pkg)
    with pytest.raises(FileExistsError):
        add_plugin(repo, "TestPlugin", pkg)


def test_add_plugin_rejects_core_overwrite(repo_server, tmp_path):
    repo, _server = repo_server
    pkg = tmp_path / "Bad"
    (pkg / "addons" / "counterstrikesharp" / "gamedata").mkdir(parents=True)
    (pkg / "addons" / "counterstrikesharp" / "gamedata" / "gamedata.json").write_text("{}")

    with pytest.raises(ValueError, match="core framework file"):
        add_plugin(repo, "Bad", pkg)


def test_add_plugin_unknown_type(repo_server, tmp_path):
    repo, _server = repo_server
    pkg = tmp_path / "Mystery"
    pkg.mkdir()
    (pkg / "data.bin").write_bytes(b"x")
    with pytest.raises(ValueError, match="Could not detect plugin type"):
        add_plugin(repo, "Mystery", pkg)


def test_classify_plugin(tmp_path):
    css = tmp_path / "csspkg"
    (css / "addons" / "counterstrikesharp").mkdir(parents=True)
    assert classify_plugin(css) == "css"

    mm = tmp_path / "mmpkg"
    (mm / "addons" / "metamod").mkdir(parents=True)
    assert classify_plugin(mm) == "metamod"

    assert classify_plugin(css, type_hint="metamod") == "metamod"


def test_list_plugins(repo_server, tmp_path):
    repo, _server = repo_server
    assert list_plugins(repo) == []
    pkg = make_css_package(tmp_path, "TestPlugin")
    add_plugin(repo, "TestPlugin", pkg)
    assert list_plugins(repo) == ["TestPlugin"]


def test_sanitize_name():
    with pytest.raises(ValueError):
        sanitize_name("bad/name")
    with pytest.raises(ValueError):
        sanitize_name("")
    assert sanitize_name("Good Name") == "Good Name"