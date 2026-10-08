"""Tests for the registry-based plugin update mechanism."""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from cs2lm import cli, linking
from cs2lm.installer import PluginManager
from cs2lm.manifest import add_plugin, load_manifest
from cs2lm.updater import update_plugin

from conftest import make_css_package


def _zip_package(pkg: Path, zip_path: Path) -> Path:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(pkg.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(pkg).as_posix())
    return zip_path


def test_update_plugin_applies_changes(repo_server, tmp_path):
    """Changed package: report diff, replace files, regenerate manifest."""
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "UpdPlugin")
    add_plugin(repo, "UpdPlugin", pkg)

    dll = pkg / "addons" / "counterstrikesharp" / "plugins" / "UpdPlugin" / "UpdPlugin.dll"
    dll.write_bytes(b"NEW")
    (pkg / "addons" / "counterstrikesharp" / "plugins" / "UpdPlugin" / "extra.cfg").write_text("x")
    (pkg / "addons" / "counterstrikesharp" / "plugins" / "UpdPlugin" / "UpdPlugin.deps.json").unlink()

    zip_path = _zip_package(pkg, tmp_path / "upd.zip")
    result = update_plugin(repo, "UpdPlugin", {"url": zip_path.as_uri()}, yes=True)

    assert result["status"] == "changed"
    assert any("extra.cfg" in s for s in result["added"])
    assert any("UpdPlugin.deps.json" in s for s in result["removed"])
    assert any("UpdPlugin.dll" in s for s in result["changed"])

    manifest = load_manifest(repo, "UpdPlugin")
    sources = {f["source"] for f in manifest["files"]}
    assert any("extra.cfg" in s for s in sources)
    assert not any("UpdPlugin.deps.json" in s for s in sources)
    dll_entry = next(f for f in manifest["files"] if f["source"].endswith("UpdPlugin.dll"))
    assert dll_entry["sha256"] == hashlib.sha256(b"NEW").hexdigest()


def test_update_plugin_up_to_date(repo_server, tmp_path):
    """Identical package: status is up-to-date and nothing changes."""
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "UpdPlugin")
    add_plugin(repo, "UpdPlugin", pkg)
    manifest_before = load_manifest(repo, "UpdPlugin")

    zip_path = _zip_package(pkg, tmp_path / "same.zip")
    result = update_plugin(repo, "UpdPlugin", {"url": zip_path.as_uri()}, yes=True)
    assert result["status"] == "up-to-date"
    assert load_manifest(repo, "UpdPlugin") == manifest_before


def test_update_plugin_dry_run(repo_server, tmp_path):
    """Dry-run reports changes without touching the manifest."""
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "UpdPlugin")
    add_plugin(repo, "UpdPlugin", pkg)
    manifest_before = load_manifest(repo, "UpdPlugin")

    dll = pkg / "addons" / "counterstrikesharp" / "plugins" / "UpdPlugin" / "UpdPlugin.dll"
    dll.write_bytes(b"NEW")
    zip_path = _zip_package(pkg, tmp_path / "dry.zip")

    result = update_plugin(repo, "UpdPlugin", {"url": zip_path.as_uri()}, dry_run=True, yes=True)
    assert result["status"] == "changed"
    assert result["dry_run"] is True
    assert load_manifest(repo, "UpdPlugin") == manifest_before


def test_update_plugin_reinstalls_links(repo_server, tmp_path):
    """If installed, update re-syncs server links (new gamedata dir appears)."""
    repo, server = repo_server
    pkg = make_css_package(tmp_path, "UpdPlugin")
    add_plugin(repo, "UpdPlugin", pkg)
    PluginManager(repo).install("UpdPlugin")

    # Add a brand-new gamedata dir that was not in the original package.
    gamedata = pkg / "addons" / "counterstrikesharp" / "gamedata" / "UpdPlugin"
    gamedata.mkdir(parents=True)
    (gamedata / "data.json").write_text("{}")
    zip_path = _zip_package(pkg, tmp_path / "newdir.zip")

    result = update_plugin(repo, "UpdPlugin", {"url": zip_path.as_uri()}, yes=True)
    assert result["status"] == "changed"
    assert result["reinstalled"] is True

    target = server / "game" / "csgo" / "addons" / "counterstrikesharp" / "gamedata" / "UpdPlugin"
    assert linking.path_exists(target)


def test_cli_update_command(repo_server, tmp_path):
    """cs2lm update <name> --yes works end-to-end via registry."""
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "CliUpd")
    add_plugin(repo, "CliUpd", pkg)
    zip_path = _zip_package(pkg, tmp_path / "v1.zip")

    assert (
        cli.main(
            [
                "--repo",
                str(repo),
                "registry",
                "add",
                "CliUpd",
                zip_path.as_uri(),
                "--type",
                "css",
            ]
        )
        == 0
    )

    # v2: change the dll.
    dll = pkg / "addons" / "counterstrikesharp" / "plugins" / "CliUpd" / "CliUpd.dll"
    dll.write_bytes(b"V2")
    zip_path2 = _zip_package(pkg, tmp_path / "v2.zip")
    assert (
        cli.main(
            [
                "--repo",
                str(repo),
                "registry",
                "add",
                "CliUpd",
                zip_path2.as_uri(),
                "--type",
                "css",
            ]
        )
        == 0
    )

    assert cli.main(["--repo", str(repo), "update", "CliUpd", "--yes"]) == 0
    manifest = load_manifest(repo, "CliUpd")
    dll_entry = next(f for f in manifest["files"] if f["source"].endswith("CliUpd.dll"))
    assert dll_entry["sha256"] == hashlib.sha256(b"V2").hexdigest()


def test_cli_update_dry_run_flag(repo_server, tmp_path):
    """--dry-run is honored by the update command."""
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "DryUpd")
    add_plugin(repo, "DryUpd", pkg)
    zip_path = _zip_package(pkg, tmp_path / "dry1.zip")
    assert (
        cli.main(
            [
                "--repo",
                str(repo),
                "registry",
                "add",
                "DryUpd",
                zip_path.as_uri(),
            ]
        )
        == 0
    )
    dll = pkg / "addons" / "counterstrikesharp" / "plugins" / "DryUpd" / "DryUpd.dll"
    dll.write_bytes(b"NEW")
    zip_path2 = _zip_package(pkg, tmp_path / "dry2.zip")
    assert (
        cli.main(
            [
                "--repo",
                str(repo),
                "registry",
                "add",
                "DryUpd",
                zip_path2.as_uri(),
            ]
        )
        == 0
    )

    manifest_before = load_manifest(repo, "DryUpd")
    assert cli.main(["--repo", str(repo), "--dry-run", "update", "DryUpd"]) == 0
    assert load_manifest(repo, "DryUpd") == manifest_before


def test_cli_update_multi_plugin(repo_server, tmp_path):
    """cs2lm update <pkg> --yes updates each plugin in a multi-plugin entry."""
    from conftest import make_multi_css_package
    from cs2lm.manifest import split_css_plugins

    repo, _server = repo_server
    pkg = make_multi_css_package(tmp_path, ["SimpleAdmin", "FunCommands"])
    base = tmp_path / "split"
    base.mkdir()
    for name, src in split_css_plugins(pkg, ["SimpleAdmin", "FunCommands"], base):
        add_plugin(repo, name, src)

    zip_path = _zip_package(pkg, tmp_path / "v1.zip")
    assert (
        cli.main(
            [
                "--repo",
                str(repo),
                "registry",
                "add",
                "SimpleAdmin",
                zip_path.as_uri(),
                "--plugins",
                "SimpleAdmin,FunCommands",
            ]
        )
        == 0
    )

    # v2: only SimpleAdmin.dll changes.
    dll = pkg / "addons" / "counterstrikesharp" / "plugins" / "SimpleAdmin" / "SimpleAdmin.dll"
    dll.write_bytes(b"V2")
    zip_path2 = _zip_package(pkg, tmp_path / "v2.zip")
    assert (
        cli.main(
            [
                "--repo",
                str(repo),
                "registry",
                "add",
                "SimpleAdmin",
                zip_path2.as_uri(),
                "--plugins",
                "SimpleAdmin,FunCommands",
            ]
        )
        == 0
    )

    assert cli.main(["--repo", str(repo), "update", "SimpleAdmin", "--yes"]) == 0

    sa_manifest = load_manifest(repo, "SimpleAdmin")
    sa_dll = next(
        f for f in sa_manifest["files"] if f["source"].endswith("SimpleAdmin.dll")
    )
    assert sa_dll["sha256"] == hashlib.sha256(b"V2").hexdigest()

    fc_manifest = load_manifest(repo, "FunCommands")
    fc_dll = next(
        f for f in fc_manifest["files"] if f["source"].endswith("FunCommands.dll")
    )
    assert fc_dll["sha256"] == hashlib.sha256(b"MZ").hexdigest()