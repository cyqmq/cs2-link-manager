"""Tests for the registry-based plugin update mechanism."""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from cs2lm import cli, linking
from cs2lm.installer import PluginManager
from cs2lm.manifest import add_plugin, list_plugins, load_manifest
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


def _write_index(tmp_path: Path, plugins: dict) -> Path:
    """Write an index.json file and return its path."""
    import json

    path = tmp_path / "index.json"
    path.write_text(
        json.dumps({"schema": 1, "name": "test-source", "plugins": plugins}),
        encoding="utf-8",
    )
    return path


def test_cli_update_command(repo_server, tmp_path):
    """cs2lm update <name> --yes works end-to-end via an index.json source."""
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "CliUpd")
    add_plugin(repo, "CliUpd", pkg)

    dll = pkg / "addons" / "counterstrikesharp" / "plugins" / "CliUpd" / "CliUpd.dll"
    dll.write_bytes(b"V2")
    zip_path2 = _zip_package(pkg, tmp_path / "v2.zip")
    index_path = _write_index(
        tmp_path,
        {
            "CliUpd": {
                "id": "CliUpd",
                "version": "2.0.0",
                "download_url": zip_path2.as_uri(),
                "plugin_type": "css",
            }
        },
    )

    assert (
        cli.main(
            ["--repo", str(repo), "source", "add", index_path.as_uri()]
        )
        == 0
    )
    assert cli.main(["--repo", str(repo), "update", "CliUpd", "--yes"]) == 0
    manifest = load_manifest(repo, "CliUpd")
    assert manifest["version"] == "2.0.0"
    dll_entry = next(f for f in manifest["files"] if f["source"].endswith("CliUpd.dll"))
    assert dll_entry["sha256"] == hashlib.sha256(b"V2").hexdigest()


def test_cli_update_dry_run_flag(repo_server, tmp_path):
    """--dry-run is honored by the update command."""
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "DryUpd")
    add_plugin(repo, "DryUpd", pkg)

    dll = pkg / "addons" / "counterstrikesharp" / "plugins" / "DryUpd" / "DryUpd.dll"
    dll.write_bytes(b"NEW")
    zip_path2 = _zip_package(pkg, tmp_path / "dry2.zip")
    index_path = _write_index(
        tmp_path,
        {
            "DryUpd": {
                "id": "DryUpd",
                "version": "1.1.0",
                "download_url": zip_path2.as_uri(),
                "plugin_type": "css",
            }
        },
    )
    assert (
        cli.main(["--repo", str(repo), "source", "add", index_path.as_uri()])
        == 0
    )

    manifest_before = load_manifest(repo, "DryUpd")
    assert cli.main(["--repo", str(repo), "--dry-run", "update", "DryUpd"]) == 0
    assert load_manifest(repo, "DryUpd") == manifest_before


def test_cli_update_multi_plugin(repo_server, tmp_path):
    """cs2lm update refreshes each plugin in a multi-plugin package."""
    from conftest import make_multi_css_package
    from cs2lm.manifest import split_css_plugins

    repo, _server = repo_server
    pkg = make_multi_css_package(tmp_path, ["SimpleAdmin", "FunCommands"])
    base = tmp_path / "split"
    base.mkdir()
    for name, src in split_css_plugins(pkg, ["SimpleAdmin", "FunCommands"], base):
        add_plugin(repo, name, src)

    zip_path = _zip_package(pkg, tmp_path / "v1.zip")
    dll = pkg / "addons" / "counterstrikesharp" / "plugins" / "SimpleAdmin" / "SimpleAdmin.dll"
    dll.write_bytes(b"V2")
    zip_path2 = _zip_package(pkg, tmp_path / "v2.zip")
    index_path = _write_index(
        tmp_path,
        {
            "SimpleAdmin": {
                "id": "SimpleAdmin",
                "version": "2.0.0",
                "download_url": zip_path2.as_uri(),
                "plugin_type": "css",
                "plugins": ["SimpleAdmin", "FunCommands"],
            },
            "FunCommands": {
                "id": "FunCommands",
                "version": "1.0.0",
                "download_url": zip_path.as_uri(),
                "plugin_type": "css",
                "plugins": ["SimpleAdmin", "FunCommands"],
            },
        },
    )
    assert (
        cli.main(["--repo", str(repo), "source", "add", index_path.as_uri()])
        == 0
    )

    assert cli.main(["--repo", str(repo), "update", "--yes"]) == 0

    sa_manifest = load_manifest(repo, "SimpleAdmin")
    assert sa_manifest["version"] == "2.0.0"
    sa_dll = next(
        f for f in sa_manifest["files"] if f["source"].endswith("SimpleAdmin.dll")
    )
    assert sa_dll["sha256"] == hashlib.sha256(b"V2").hexdigest()

    fc_manifest = load_manifest(repo, "FunCommands")
    fc_dll = next(
        f for f in fc_manifest["files"] if f["source"].endswith("FunCommands.dll")
    )
    assert fc_dll["sha256"] == hashlib.sha256(b"MZ").hexdigest()


def test_compute_actions():
    from cs2lm.updater import compute_actions

    merged = {
        "a": {"version": "1.0.0"},
        "b": {"version": "2.0.0"},
        "c": {"version": "0.9.0"},
    }
    local = {"b": "1.0.0", "c": "0.9.0", "d": "3.0.0"}
    install, update, skip, orphans = compute_actions(merged, local)
    assert install == ["a"]
    assert update == ["b"]
    assert skip == ["c"]
    assert orphans == ["d"]


def test_update_plugin_atomic_replace_leaves_no_temp_dirs(repo_server, tmp_path):
    """After an update no .<name>.new / .<name>.old staging dirs remain."""
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "Atomic")
    add_plugin(repo, "Atomic", pkg)
    dll = pkg / "addons" / "counterstrikesharp" / "plugins" / "Atomic" / "Atomic.dll"
    dll.write_bytes(b"V2")
    zip_path = _zip_package(pkg, tmp_path / "v2.zip")
    result = update_plugin(
        repo, "Atomic", {"url": zip_path.as_uri(), "version": "1.1.0"}, yes=True
    )
    assert result["status"] == "changed"
    plugins_root = repo / "plugins"
    assert not list(plugins_root.glob(".Atomic.new"))
    assert not list(plugins_root.glob(".Atomic.old"))
    assert (plugins_root / "Atomic" / "manifest.json").exists()


def test_update_plugin_package_id_mismatch(repo_server, tmp_path):
    """A package whose manifest id differs from the index is refused."""
    import json

    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "IdMismatch")
    add_plugin(repo, "IdMismatch", pkg)
    (pkg / "manifest.json").write_text(
        json.dumps({"id": "Other", "version": "1.0.0"}), encoding="utf-8"
    )
    zip_path = _zip_package(pkg, tmp_path / "bad.zip")
    result = update_plugin(
        repo,
        "IdMismatch",
        {"url": zip_path.as_uri(), "version": "1.0.0"},
        yes=True,
    )
    assert result["status"] == "error"
    assert "id mismatch" in result["message"]


def test_update_plugin_sha256_mismatch(repo_server, tmp_path):
    """A checksum mismatch aborts the update with an error."""
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "ShaUpd")
    add_plugin(repo, "ShaUpd", pkg)
    zip_path = _zip_package(pkg, tmp_path / "sha.zip")
    result = update_plugin(
        repo,
        "ShaUpd",
        {"url": zip_path.as_uri(), "version": "1.1.0", "sha256": "0" * 64},
        yes=True,
    )
    assert result["status"] == "error"
    assert "Checksum mismatch" in result["message"]


def test_cli_update_installs_missing_and_skips_newer(repo_server, tmp_path):
    """update installs missing plugins and skips ones already newer."""
    import json

    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "Old")
    add_plugin(repo, "Old", pkg)  # version defaults to 1.0.0
    new_pkg = make_css_package(tmp_path, "New")
    zip_new = _zip_package(new_pkg, tmp_path / "new.zip")

    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "plugins": {
                    "New": {
                        "id": "New",
                        "version": "1.0.0",
                        "download_url": zip_new.as_uri(),
                        "plugin_type": "css",
                    },
                    "Old": {
                        "id": "Old",
                        "version": "0.9.0",
                        "download_url": zip_new.as_uri(),
                        "plugin_type": "css",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    assert cli.main(["--repo", str(repo), "source", "add", index_path.as_uri()]) == 0
    assert cli.main(["--repo", str(repo), "update", "--yes"]) == 0
    assert "New" in list_plugins(repo)
    old_manifest = load_manifest(repo, "Old")
    assert old_manifest["version"] == "1.0.0"


def test_cli_update_orphan_removal(repo_server, tmp_path):
    """--remove-orphans uninstalls and trashes plugins absent from sources."""
    import json

    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "Orphan")
    add_plugin(repo, "Orphan", pkg)
    kept = make_css_package(tmp_path, "Kept")
    add_plugin(repo, "Kept", kept)
    zip_kept = _zip_package(kept, tmp_path / "kept.zip")

    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "plugins": {
                    "Kept": {
                        "id": "Kept",
                        "version": "1.0.0",
                        "download_url": zip_kept.as_uri(),
                        "plugin_type": "css",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert cli.main(["--repo", str(repo), "source", "add", index_path.as_uri()]) == 0
    assert cli.main(["--repo", str(repo), "update", "--yes", "--remove-orphans"]) == 0
    assert "Kept" in list_plugins(repo)
    assert "Orphan" not in list_plugins(repo)
    assert any((repo / "trash" / "plugins").glob("Orphan-*"))


def test_cli_update_requires_expansion(repo_server, tmp_path):
    """Dependencies listed in index ``requires`` are installed first."""
    import json

    repo, _server = repo_server
    dep_pkg = make_css_package(tmp_path, "DepLib")
    zip_dep = _zip_package(dep_pkg, tmp_path / "dep.zip")
    main_pkg = make_css_package(tmp_path, "Main")
    zip_main = _zip_package(main_pkg, tmp_path / "main.zip")

    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "plugins": {
                    "DepLib": {
                        "id": "DepLib",
                        "version": "1.0.0",
                        "download_url": zip_dep.as_uri(),
                        "plugin_type": "css",
                    },
                    "Main": {
                        "id": "Main",
                        "version": "1.0.0",
                        "download_url": zip_main.as_uri(),
                        "plugin_type": "css",
                        "requires": {"DepLib": ">=1.0.0"},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    assert cli.main(["--repo", str(repo), "source", "add", index_path.as_uri()]) == 0
    assert cli.main(["--repo", str(repo), "update", "--yes"]) == 0
    assert "DepLib" in list_plugins(repo)
    assert "Main" in list_plugins(repo)
    main_manifest = load_manifest(repo, "Main")
    assert main_manifest.get("requires") == {"DepLib": ">=1.0.0"}