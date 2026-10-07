import json
import os
from pathlib import Path

import pytest

from cs2lm import linking
from cs2lm.installer import PluginManager
from cs2lm.manifest import add_plugin, load_manifest

from conftest import make_css_package


def make_manager(repo, **kwargs):
    return PluginManager(repo, **kwargs)


def plugin_path(server, rel):
    return server / "game" / "csgo" / "addons" / "counterstrikesharp" / "plugins" / rel


def test_install_creates_symlink(repo_server, tmp_path):
    repo, server = repo_server
    pkg = make_css_package(tmp_path, "TestPlugin")
    add_plugin(repo, "TestPlugin", pkg)
    manager = make_manager(repo)
    manager.install("TestPlugin")

    target = plugin_path(server, "TestPlugin")
    assert linking.path_exists(target)
    assert linking.is_link(target) or linking.is_junction(target)

    state = json.loads((repo / "state" / "links.json").read_text(encoding="utf-8"))
    records = [r for r in state["links"] if r["plugin"] == "TestPlugin"]
    assert len(records) == 2  # plugin dir + configs dir
    assert all(r["kind_used"] in ("symlink", "junction", "copy") for r in records)

    manifest = load_manifest(repo, "TestPlugin")
    assert manifest["enabled"] is True


def test_install_is_idempotent(repo_server, tmp_path):
    repo, server = repo_server
    pkg = make_css_package(tmp_path, "TestPlugin")
    add_plugin(repo, "TestPlugin", pkg)
    manager = make_manager(repo)
    manager.install("TestPlugin")
    manager.install("TestPlugin")  # must not raise

    state = json.loads((repo / "state" / "links.json").read_text(encoding="utf-8"))
    records = [r for r in state["links"] if r["plugin"] == "TestPlugin"]
    assert len(records) == 2


def test_uninstall_removes_link_keeps_repo(repo_server, tmp_path):
    repo, server = repo_server
    pkg = make_css_package(tmp_path, "TestPlugin")
    add_plugin(repo, "TestPlugin", pkg)
    manager = make_manager(repo)
    manager.install("TestPlugin")
    manager.uninstall("TestPlugin")

    target = plugin_path(server, "TestPlugin")
    assert not linking.path_exists(target)

    repo_file = (
        repo
        / "plugins"
        / "TestPlugin"
        / "files"
        / "addons"
        / "counterstrikesharp"
        / "plugins"
        / "TestPlugin"
        / "TestPlugin.dll"
    )
    assert repo_file.exists()
    manifest = load_manifest(repo, "TestPlugin")
    assert manifest["enabled"] is False


def test_install_conflict_refused_by_default(repo_server, tmp_path):
    repo, server = repo_server
    pkg = make_css_package(tmp_path, "TestPlugin")
    add_plugin(repo, "TestPlugin", pkg)

    target = plugin_path(server, "TestPlugin")
    target.mkdir(parents=True)
    (target / "unmanaged.txt").write_text("mine")

    manager = make_manager(repo)
    with pytest.raises(linking.ConflictError):
        manager.install("TestPlugin")
    assert (target / "unmanaged.txt").exists()


def test_install_conflict_with_backup(repo_server, tmp_path):
    repo, server = repo_server
    pkg = make_css_package(tmp_path, "TestPlugin")
    add_plugin(repo, "TestPlugin", pkg)

    target = plugin_path(server, "TestPlugin")
    target.mkdir(parents=True)
    (target / "unmanaged.txt").write_text("mine")

    manager = make_manager(repo, backup=True, yes=True)
    manager.install("TestPlugin")
    assert linking.path_exists(target)
    assert not (target / "unmanaged.txt").exists()
    backups = list((server / ".cs2lm-backups").rglob("unmanaged.txt"))
    assert backups


def test_install_conflict_with_backup_requires_confirmation(repo_server, tmp_path):
    repo, server = repo_server
    pkg = make_css_package(tmp_path, "TestPlugin")
    add_plugin(repo, "TestPlugin", pkg)

    target = plugin_path(server, "TestPlugin")
    target.mkdir(parents=True)
    (target / "unmanaged.txt").write_text("mine")

    manager = make_manager(repo, backup=True)  # no --yes -> input() -> EOF -> abort
    with pytest.raises(linking.ConflictError, match="Aborted by user"):
        manager.install("TestPlugin")
    assert (target / "unmanaged.txt").exists()
    assert not (server / ".cs2lm-backups").exists()


def test_install_conflict_with_backup_confirmed(repo_server, tmp_path, monkeypatch):
    repo, server = repo_server
    pkg = make_css_package(tmp_path, "TestPlugin")
    add_plugin(repo, "TestPlugin", pkg)

    target = plugin_path(server, "TestPlugin")
    target.mkdir(parents=True)
    (target / "unmanaged.txt").write_text("mine")

    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    manager = make_manager(repo, backup=True)
    manager.install("TestPlugin")
    assert linking.path_exists(target)
    assert not (target / "unmanaged.txt").exists()
    backups = list((server / ".cs2lm-backups").rglob("unmanaged.txt"))
    assert backups


def test_install_conflict_with_force_skips_confirmation(repo_server, tmp_path):
    repo, server = repo_server
    pkg = make_css_package(tmp_path, "TestPlugin")
    add_plugin(repo, "TestPlugin", pkg)

    target = plugin_path(server, "TestPlugin")
    target.mkdir(parents=True)
    (target / "unmanaged.txt").write_text("mine")

    # --force takes over without asking for confirmation.
    manager = make_manager(repo, force=True)
    manager.install("TestPlugin")
    assert linking.path_exists(target)
    assert not (target / "unmanaged.txt").exists()
    backups = list((server / ".cs2lm-backups").rglob("unmanaged.txt"))
    assert backups


def test_install_dry_run_creates_nothing(repo_server, tmp_path):
    repo, server = repo_server
    pkg = make_css_package(tmp_path, "TestPlugin")
    add_plugin(repo, "TestPlugin", pkg)
    manager = make_manager(repo, dry_run=True)
    manager.install("TestPlugin")

    target = plugin_path(server, "TestPlugin")
    assert not linking.path_exists(target)
    assert not (repo / "state" / "links.json").exists()
    manifest = load_manifest(repo, "TestPlugin")
    assert manifest["enabled"] is True  # dry-run does not mutate manifests


def test_disable_and_enable(repo_server, tmp_path):
    repo, server = repo_server
    pkg = make_css_package(tmp_path, "TestPlugin")
    add_plugin(repo, "TestPlugin", pkg)
    manager = make_manager(repo)
    manager.install("TestPlugin")

    manager.disable("TestPlugin")
    target = plugin_path(server, "TestPlugin")
    assert not linking.path_exists(target)
    assert load_manifest(repo, "TestPlugin")["enabled"] is False

    manager.enable("TestPlugin")
    assert linking.path_exists(target)
    assert load_manifest(repo, "TestPlugin")["enabled"] is True


def test_uninstall_no_state_is_noop(repo_server, tmp_path):
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "TestPlugin")
    add_plugin(repo, "TestPlugin", pkg)
    manager = make_manager(repo)
    manager.uninstall("TestPlugin")  # should not raise
    assert load_manifest(repo, "TestPlugin")["enabled"] is False