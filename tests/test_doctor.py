import os
from pathlib import Path

from cs2lm import linking
from cs2lm.doctor import run_doctor
from cs2lm.installer import PluginManager
from cs2lm.manifest import add_plugin

from conftest import make_css_package


def codes(issues):
    return [i["code"] for i in issues]


def test_doctor_clean(repo_server, tmp_path):
    repo, server = repo_server
    pkg = make_css_package(tmp_path, "TestPlugin")
    add_plugin(repo, "TestPlugin", pkg)
    PluginManager(repo).install("TestPlugin")
    issues = run_doctor(repo)
    assert "broken-link" not in codes(issues)
    assert "conflict" not in codes(issues)
    assert "orphan-link" not in codes(issues)


def test_doctor_detects_broken_link(repo_server, tmp_path):
    repo, server = repo_server
    pkg = make_css_package(tmp_path, "TestPlugin")
    add_plugin(repo, "TestPlugin", pkg)
    manager = PluginManager(repo)
    manager.install("TestPlugin")

    target = server / "game" / "csgo" / "addons" / "counterstrikesharp" / "plugins" / "TestPlugin"
    if linking.is_link(target):
        target.unlink()
    else:
        import shutil

        shutil.rmtree(target)

    issues = run_doctor(repo)
    assert "broken-link" in codes(issues)


def test_doctor_detects_conflict_for_disabled(repo_server, tmp_path):
    repo, server = repo_server
    pkg = make_css_package(tmp_path, "TestPlugin")
    add_plugin(repo, "TestPlugin", pkg)
    # plugin not installed, but target exists -> conflict
    target = server / "game" / "csgo" / "addons" / "counterstrikesharp" / "plugins" / "TestPlugin"
    target.mkdir(parents=True, exist_ok=True)
    issues = run_doctor(repo)
    assert "conflict" in codes(issues)


def test_doctor_detects_orphan_link(repo_server, tmp_path):
    repo, server = repo_server
    repo_plugins = repo / "plugins" / "Orphan" / "files" / "addons" / "counterstrikesharp" / "plugins" / "Orphan"
    repo_plugins.mkdir(parents=True)
    (repo_plugins / "Orphan.dll").write_bytes(b"MZ")

    plugins_dir = server / "game" / "csgo" / "addons" / "counterstrikesharp" / "plugins"
    orphan_target = plugins_dir / "Orphan"
    orphan_target.symlink_to(repo_plugins, target_is_directory=True)

    issues = run_doctor(repo)
    assert "orphan-link" in codes(issues)