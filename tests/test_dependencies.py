"""Tests for plugin dependency management (``requires``)."""
from __future__ import annotations

import pytest

from cs2lm import linking
from cs2lm.installer import InstallError, PluginManager
from cs2lm.manifest import add_plugin, load_manifest

from conftest import make_css_package


def test_install_auto_installs_dependency(repo_server, tmp_path):
    """Installing MainPlugin auto-installs its required SharedLib."""
    repo, server = repo_server
    shared = make_css_package(tmp_path, "SharedLib")
    add_plugin(repo, "SharedLib", shared)
    main = make_css_package(tmp_path, "MainPlugin")
    add_plugin(repo, "MainPlugin", main, meta={"requires": ["SharedLib"]})

    PluginManager(repo).install("MainPlugin")
    assert load_manifest(repo, "SharedLib")["enabled"] is True
    target_main = server / "game" / "csgo" / "addons" / "counterstrikesharp" / "plugins" / "MainPlugin"
    target_shared = server / "game" / "csgo" / "addons" / "counterstrikesharp" / "plugins" / "SharedLib"
    assert linking.path_exists(target_main)
    assert linking.path_exists(target_shared)


def test_install_missing_dependency_raises(repo_server, tmp_path):
    """Installing a plugin whose dependency is absent fails with a clear error."""
    repo, _server = repo_server
    main = make_css_package(tmp_path, "MainPlugin")
    add_plugin(repo, "MainPlugin", main, meta={"requires": ["MissingLib"]})
    with pytest.raises(InstallError, match="requires plugin 'MissingLib'"):
        PluginManager(repo).install("MainPlugin")


def test_uninstall_refuses_when_required(repo_server, tmp_path):
    """A plugin that another installed plugin requires cannot be disabled."""
    repo, _server = repo_server
    shared = make_css_package(tmp_path, "SharedLib")
    add_plugin(repo, "SharedLib", shared)
    main = make_css_package(tmp_path, "MainPlugin")
    add_plugin(repo, "MainPlugin", main, meta={"requires": ["SharedLib"]})

    manager = PluginManager(repo)
    manager.install("MainPlugin")
    with pytest.raises(InstallError, match=r"enabled plugin\(s\) require it"):
        manager.uninstall("SharedLib")


def test_dependency_cycle_detected(repo_server, tmp_path):
    """A -> B -> A is detected and refused."""
    repo, _server = repo_server
    add_plugin(repo, "PluginA", make_css_package(tmp_path, "PluginA"),
               meta={"requires": ["PluginB"]})
    add_plugin(repo, "PluginB", make_css_package(tmp_path, "PluginB"),
               meta={"requires": ["PluginA"]})
    with pytest.raises(InstallError, match="Dependency cycle detected"):
        PluginManager(repo).install("PluginA")


def test_cs2pkg_roundtrip_preserves_requires(repo_server, tmp_path):
    """pack / add --pkg carries the ``requires`` list."""
    from cs2lm import cli
    from cs2lm.cs2pkg import build_pkg, load_pkg_meta
    from conftest import init_repo

    src_repo, _server = repo_server
    add_plugin(
        src_repo,
        "DepPlugin",
        make_css_package(tmp_path, "DepPlugin"),
        meta={"requires": ["SharedLib"]},
    )
    pkg_path = build_pkg(src_repo, "DepPlugin", tmp_path / "dist")
    meta = load_pkg_meta(pkg_path)
    assert meta["requires"] == ["SharedLib"]

    target_repo = init_repo(tmp_path, repo_name="target")
    assert (
        cli.main(["--repo", str(target_repo), "add", "DepPlugin", "--pkg", str(pkg_path)])
        == 0
    )
    assert load_manifest(target_repo, "DepPlugin")["requires"] == ["SharedLib"]