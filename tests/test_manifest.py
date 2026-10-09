from pathlib import Path

import pytest

from cs2lm.manifest import (
    add_plugin,
    classify_plugin,
    list_plugins,
    sanitize_name,
)

from conftest import make_css_package, make_multi_css_package


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


def test_add_renames_internal_plugin_dir_to_given_name(repo_server, tmp_path):
    """cs2lm add Renamed ./DemoPlugin/ must link as plugins/Renamed.

    The package contains addons/counterstrikesharp/plugins/DemoPlugin but the
    user gives the repository name Renamed; install/uninstall and profiles
    must operate on Renamed, not DemoPlugin.
    """
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "DemoPlugin")
    manifest = add_plugin(repo, "Renamed", pkg)

    assert manifest["name"] == "Renamed"
    # The plugin directory is stored under the new name (files inside keep
    # their original names; renaming binaries could break the plugin).
    file_sources = {f["source"] for f in manifest["files"]}
    assert any("plugins/Renamed/" in s for s in file_sources)
    assert not any("plugins/DemoPlugin" in s for s in file_sources)
    # Targets use the new directory name.
    targets = {f["target"] for f in manifest["files"]}
    assert any("plugins/Renamed/" in t for t in targets)
    assert not any("plugins/DemoPlugin" in t for t in targets)
    # Links point at the new name.
    link_targets = {l["target"] for l in manifest["links"]}
    assert "game/csgo/addons/counterstrikesharp/plugins/Renamed" in link_targets
    assert "game/csgo/addons/counterstrikesharp/configs/plugins/Renamed" in link_targets
    assert not any("DemoPlugin" in t for t in link_targets)


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


def test_add_plugin_unknown_type_defaults_to_css(repo_server, tmp_path):
    """A directory with no recognizable plugin layout is added as CSS with a
    warning (README promises a warning, not an error, for non-plugin dirs)."""
    repo, _server = repo_server
    pkg = tmp_path / "Mystery"
    pkg.mkdir()
    (pkg / "data.bin").write_bytes(b"x")
    manifest = add_plugin(repo, "Mystery", pkg)
    assert manifest["plugin_type"] == "css"


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


def test_add_plugin_records_sha256(repo_server, tmp_path):
    """Every managed file records its SHA-256 for future integrity checks."""
    import hashlib

    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "TestPlugin")
    manifest = add_plugin(repo, "TestPlugin", pkg)
    assert manifest["files"]
    for f in manifest["files"]:
        assert "sha256" in f
    dll = next(f for f in manifest["files"] if f["source"].endswith("TestPlugin.dll"))
    assert dll["sha256"] == hashlib.sha256(b"MZ").hexdigest()


def test_add_plugin_rejects_multi_plugin_package(repo_server, tmp_path):
    """A package with several plugin dirs is ambiguous -> refuse with a hint."""
    repo, _server = repo_server
    pkg = tmp_path / "Multi"
    plugins = pkg / "addons" / "counterstrikesharp" / "plugins"
    for name in ("One", "Two"):
        (plugins / name).mkdir(parents=True)
        (plugins / name / f"{name}.dll").write_bytes(b"MZ")
        (plugins / name / f"{name}.deps.json").write_text("{}")
    with pytest.raises(ValueError, match="plugin directories under 'plugins/'"):
        add_plugin(repo, "Multi", pkg)


def test_add_plugin_stores_meta_fields(repo_server, tmp_path):
    """cs2pkg metadata (author/description/license/homepage/repository/deps) is stored."""
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "MetaPlugin")
    meta = {
        "author": "Alice",
        "description": "A test plugin",
        "license": "MIT",
        "homepage": "https://example.com",
        "repository": "https://github.com/example/plugin",
        "dependencies": {"CounterStrikeSharp.API": "1.0.376"},
    }
    manifest = add_plugin(repo, "MetaPlugin", pkg, meta=meta)
    for field in ("author", "description", "license", "homepage", "repository"):
        assert manifest[field] == meta[field]
    assert manifest["dependencies"]["CounterStrikeSharp.API"] == "1.0.376"


def test_split_css_plugins_creates_per_plugin_trees(tmp_path):
    """A multi-plugin package splits into independent addons/ trees."""
    from cs2lm.manifest import split_css_plugins

    pkg = make_multi_css_package(
        tmp_path, ["SimpleAdmin", "FunCommands", "StealthModule"]
    )
    base = tmp_path / "split"
    base.mkdir()
    results = split_css_plugins(
        pkg, ["SimpleAdmin", "FunCommands", "StealthModule"], base
    )
    assert [n for n, _ in results] == ["SimpleAdmin", "FunCommands", "StealthModule"]
    for name, src in results:
        assert (src / "addons" / "counterstrikesharp" / "plugins" / name).is_dir()
        # Only the plugin's own configs dir is included, not the other plugins'.
        cfg = src / "addons" / "counterstrikesharp" / "configs" / "plugins"
        assert (cfg / name).is_dir()
        assert len(list(cfg.iterdir())) == 1


def test_split_css_plugins_missing_name_raises(tmp_path):
    """Splitting with a name absent from the package fails clearly."""
    from cs2lm.manifest import split_css_plugins

    pkg = make_multi_css_package(tmp_path, ["SimpleAdmin", "FunCommands"])
    base = tmp_path / "split"
    base.mkdir()
    with pytest.raises(ValueError, match="not found in package"):
        split_css_plugins(pkg, ["Nope"], base)


def test_add_split_creates_separate_repo_entries(repo_server, tmp_path):
    """Adding each split tree produces one repo plugin per package plugin."""
    from cs2lm.manifest import load_manifest, split_css_plugins

    repo, _server = repo_server
    pkg = make_multi_css_package(
        tmp_path, ["SimpleAdmin", "FunCommands", "StealthModule"]
    )
    base = tmp_path / "split"
    base.mkdir()
    for name, src in split_css_plugins(
        pkg, ["SimpleAdmin", "FunCommands", "StealthModule"], base
    ):
        add_plugin(repo, name, src)
    assert list_plugins(repo) == ["FunCommands", "SimpleAdmin", "StealthModule"]
    for name in ("SimpleAdmin", "FunCommands", "StealthModule"):
        sources = {f["source"] for f in load_manifest(repo, name)["files"]}
        assert any(f"plugins/{name}/" in s for s in sources)
        for other in ("SimpleAdmin", "FunCommands", "StealthModule"):
            if other != name:
                assert not any(f"plugins/{other}/" in s for s in sources)


def _make_package_without_configs(tmp_path: Path, names: list[str]) -> Path:
    """Build a multi-plugin CSS package with plugins/ + shared/ only."""
    pkg = tmp_path / "NoConfigsPkg"
    for name in names:
        dirname = pkg / "addons" / "counterstrikesharp" / "plugins" / name
        dirname.mkdir(parents=True)
        (dirname / f"{name}.dll").write_bytes(b"MZ")
    shared = pkg / "addons" / "counterstrikesharp" / "shared" / "CS2-SimpleAdminApi"
    shared.mkdir(parents=True)
    (shared / "CS2-SimpleAdminApi.dll").write_bytes(b"MZ")
    return pkg


def test_split_css_plugins_without_configs(tmp_path, capsys):
    """Splitting a package with no configs/ (e.g. SimpleAdmin) must not crash.

    Regression test: split_css_plugins previously assumed ``configs/``
    exists and raised WinError 3 on packages that only ship ``plugins/`` and
    ``shared/``.
    """
    from cs2lm.manifest import split_css_plugins

    pkg = _make_package_without_configs(tmp_path, ["SimpleAdmin", "FunCommands"])
    base = tmp_path / "split"
    base.mkdir()
    results = split_css_plugins(pkg, ["SimpleAdmin", "FunCommands"], base)
    assert [n for n, _ in results] == ["SimpleAdmin", "FunCommands"]
    for name, src in results:
        assert (src / "addons" / "counterstrikesharp" / "plugins" / name).is_dir()
        # No configs tree is created when the source has none.
        assert not (src / "addons" / "counterstrikesharp" / "configs").exists()
    # The shared/ directory is reported, not silently dropped.
    assert "shared/" in capsys.readouterr().err


def test_collect_css_links_includes_shared(repo_server, tmp_path):
    """A CSS package shipping a shared/ tree links it to the server."""
    repo, _server = repo_server
    pkg = _make_package_without_configs(tmp_path, ["SimpleAdmin"])
    manifest = add_plugin(repo, "SimpleAdmin", pkg)
    shared_links = [
        link for link in manifest["links"]
        if "shared/CS2-SimpleAdminApi" in link["source"]
    ]
    assert shared_links
    assert any(
        link["target"].endswith(
            "addons/counterstrikesharp/shared/CS2-SimpleAdminApi"
        )
        for link in shared_links
    )


def _write_deps_with_version(pkg: Path, name: str, version: str) -> None:
    """Write a realistic .deps.json declaring the plugin assembly version."""
    import json

    deps = pkg / "addons" / "counterstrikesharp" / "plugins" / name / f"{name}.deps.json"
    deps.write_text(
        json.dumps(
            {
                "runtimeTarget": {"name": ".NETCoreApp,Version=v8.0"},
                "targets": {
                    ".NETCoreApp,Version=v8.0": {
                        f"{name}/{version}": {
                            "dependencies": {"CounterStrikeSharp.API": "1.0.376"},
                            "runtime": {f"{name}.dll": {}},
                        }
                    }
                },
                "libraries": {},
            }
        ),
        encoding="utf-8",
    )


def test_add_plugin_detects_version_from_deps_json(repo_server, tmp_path):
    """``add`` extracts the plugin version from its .deps.json targets."""
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "Retakes")
    _write_deps_with_version(pkg, "Retakes", "3.1.1")
    manifest = add_plugin(repo, "Retakes", pkg)
    assert manifest["version"] == "3.1.1"


def test_add_plugin_version_override_wins(repo_server, tmp_path):
    """An explicit --version argument beats .deps.json detection."""
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "Retakes")
    _write_deps_with_version(pkg, "Retakes", "3.1.1")
    manifest = add_plugin(repo, "Retakes", pkg, version="9.9.9")
    assert manifest["version"] == "9.9.9"


def test_pack_preserves_detected_version(repo_server, tmp_path):
    """The detected version survives the pack round trip."""
    from cs2lm.cs2pkg import build_pkg, load_pkg_meta

    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "Retakes")
    _write_deps_with_version(pkg, "Retakes", "3.1.1")
    add_plugin(repo, "Retakes", pkg)

    pkg_path = build_pkg(repo, "Retakes", tmp_path / "dist")
    assert load_pkg_meta(pkg_path)["version"] == "3.1.1"


def test_retakes_scenario_dir_rename_and_shared(repo_server, tmp_path):
    """cs2-retakes-style package: dir renamed to repo name, shared linked.

    Regression coverage for a real deployment report: a package shipping
    ``plugins/cs2-retakes/RetakesPlugin.dll`` plus
    ``shared/RetakesPluginShared/`` was registered as ``RetakesPlugin``.
    The tool must (1) normalize the plugin directory to the repo name and
    (2) link the ``shared/`` library to the server.
    """
    from cs2lm import linking
    from cs2lm.installer import PluginManager

    repo, server = repo_server
    pkg = tmp_path / "retakes-pkg"
    plugin_dir = pkg / "addons" / "counterstrikesharp" / "plugins" / "cs2-retakes"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "RetakesPlugin.dll").write_bytes(b"MZ")
    (plugin_dir / "RetakesPlugin.deps.json").write_text("{}", encoding="utf-8")
    shared_dir = pkg / "addons" / "counterstrikesharp" / "shared" / "RetakesPluginShared"
    shared_dir.mkdir(parents=True)
    (shared_dir / "RetakesPluginShared.dll").write_bytes(b"MZ")

    manifest = add_plugin(repo, "RetakesPlugin", pkg)
    # The plugin directory is normalized to the repository name.
    assert any(
        "plugins/RetakesPlugin/RetakesPlugin.dll" in f["source"]
        for f in manifest["files"]
    )
    assert not any("plugins/cs2-retakes" in f["source"] for f in manifest["files"])
    # The shared library is recorded as a link.
    assert any(
        "shared/RetakesPluginShared" in link["source"]
        for link in manifest["links"]
    )

    PluginManager(repo).install("RetakesPlugin")
    target_plugin = (
        server / "game" / "csgo" / "addons" / "counterstrikesharp" / "plugins" / "RetakesPlugin"
    )
    target_shared = (
        server / "game" / "csgo" / "addons" / "counterstrikesharp" / "shared" / "RetakesPluginShared"
    )
    assert linking.path_exists(target_plugin)
    assert linking.path_exists(target_shared)