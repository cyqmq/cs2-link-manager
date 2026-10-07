"""Tests for .cs2pkg packaging and installation."""
from __future__ import annotations

import zipfile
from pathlib import Path

from cs2lm import cli
from cs2lm.cs2pkg import PKG_META_FILENAME, build_pkg, extract_pkg, load_pkg_meta
from cs2lm.manifest import add_plugin, list_plugins, load_manifest

from conftest import init_repo, make_css_package


def test_build_pkg_roundtrip(repo_server, tmp_path):
    repo, _server = repo_server
    add_plugin(repo, "MyPlugin", make_css_package(tmp_path, "MyPlugin"))

    pkg_path = build_pkg(repo, "MyPlugin", tmp_path / "dist")
    assert pkg_path.name == "MyPlugin.cs2pkg"
    assert pkg_path.exists()

    meta = load_pkg_meta(pkg_path)
    assert meta["name"] == "MyPlugin"
    assert meta["plugin_type"] == "css"

    dest = tmp_path / "extracted"
    root, meta2 = extract_pkg(pkg_path, dest)
    assert meta2 == meta
    assert (root / "addons" / "counterstrikesharp" / "plugins" / "MyPlugin" / "MyPlugin.dll").is_file()


def test_build_pkg_contains_meta_and_files(repo_server, tmp_path):
    repo, _server = repo_server
    add_plugin(repo, "MyPlugin", make_css_package(tmp_path, "MyPlugin"))
    pkg_path = build_pkg(repo, "MyPlugin", tmp_path / "out.cs2pkg")

    with zipfile.ZipFile(pkg_path) as zf:
        names = set(zf.namelist())
        assert PKG_META_FILENAME in names
        assert any(n.endswith("MyPlugin.dll") for n in names)


def test_add_from_pkg(repo_server, tmp_path):
    src_repo, _server = repo_server
    add_plugin(src_repo, "PkgPlugin", make_css_package(tmp_path, "PkgPlugin"))
    pkg_path = build_pkg(src_repo, "PkgPlugin", tmp_path / "dist")

    # A fresh repository consumes the package.
    target_repo = init_repo(tmp_path, repo_name="target")
    rc = cli.main(["--repo", str(target_repo), "add", "PkgPlugin", "--pkg", str(pkg_path)])
    assert rc == 0
    assert "PkgPlugin" in list_plugins(target_repo)
    manifest = load_manifest(target_repo, "PkgPlugin")
    assert manifest["plugin_type"] == "css"
    assert manifest["version"] == "1.0.0"


def test_add_from_pkg_uses_cs2pkg_name_when_omitted(repo_server, tmp_path):
    """cs2lm add --pkg file.cs2pkg uses cs2pkg.json's name when no name is given."""
    src_repo, _server = repo_server
    add_plugin(src_repo, "PkgPlugin", make_css_package(tmp_path, "PkgPlugin"))
    pkg_path = build_pkg(src_repo, "PkgPlugin", tmp_path / "dist")

    target_repo = init_repo(tmp_path, repo_name="target")
    rc = cli.main(["--repo", str(target_repo), "add", "--pkg", str(pkg_path)])
    assert rc == 0
    assert "PkgPlugin" in list_plugins(target_repo)


def test_add_from_pkg_renames_internal_dir_to_cli_name(repo_server, tmp_path):
    """cs2lm add MyName --pkg where the package contains DemoPlugin must link as MyName."""
    src_repo, _server = repo_server
    add_plugin(src_repo, "DemoPlugin", make_css_package(tmp_path, "DemoPlugin"))
    pkg_path = build_pkg(src_repo, "DemoPlugin", tmp_path / "dist")

    target_repo = init_repo(tmp_path, repo_name="target")
    rc = cli.main(["--repo", str(target_repo), "add", "MyName", "--pkg", str(pkg_path)])
    assert rc == 0
    manifest = load_manifest(target_repo, "MyName")
    assert manifest["name"] == "MyName"
    targets = {f["target"] for f in manifest["files"]}
    assert any("plugins/MyName/" in t for t in targets)
    assert not any("plugins/DemoPlugin" in t for t in targets)


def test_cli_pack(repo_server, tmp_path, capsys):
    repo, _server = repo_server
    add_plugin(repo, "PackMe", make_css_package(tmp_path, "PackMe"))
    out_dir = tmp_path / "releases"
    rc = cli.main(["--repo", str(repo), "pack", "PackMe", "--out", str(out_dir)])
    assert rc == 0
    assert (out_dir / "PackMe.cs2pkg").exists()
    captured = capsys.readouterr()
    assert "Packaged 'PackMe'" in captured.out


def test_load_pkg_meta_invalid(tmp_path):
    bogus = tmp_path / "bad.cs2pkg"
    bogus.write_bytes(b"not a zip")
    assert load_pkg_meta(bogus) is None