"""Tests for multi-plugin packaging and game-content (.cs2pkg kind=content)."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from cs2lm import cli
from cs2lm.cs2pkg import PKG_META_FILENAME, build_pkg, extract_pkg, load_pkg_meta
from cs2lm.manifest import (
    add_plugin,
    list_plugins,
    load_manifest,
)

from conftest import init_repo, make_css_package, make_multi_css_package


def _make_content_package(
    tmp_path: Path,
    name: str = "ContentMod",
    requires_frameworks: list[str] | None = None,
    platform: str = "all",
    roots: dict | None = None,
) -> Path:
    """Build a content package directory with a cs2pkg.json manifest."""
    pkg = tmp_path / name
    cfg = pkg / "cfg"
    cfg.mkdir(parents=True)
    (cfg / "server.cfg").write_text('echo "content";\n', encoding="utf-8")
    ov = pkg / "overrides"
    ov.mkdir(parents=True)
    (ov / "botprofile.vpk").write_bytes(b"VPK")
    addons = pkg / "addons" / "counterstrikesharp" / "plugins" / "DemoPlugin"
    addons.mkdir(parents=True)
    (addons / "DemoPlugin.dll").write_bytes(b"MZ")

    meta = {
        "kind": "content",
        "name": name,
        "version": "1.0.0",
        "roots": roots
        or {
            "addons": "game/csgo/addons",
            "cfg": "game/csgo/cfg",
            "overrides": "game/csgo/overrides",
        },
    }
    if requires_frameworks:
        meta["requires_frameworks"] = requires_frameworks
    if platform:
        meta["platform"] = platform
    (pkg / "cs2pkg.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    return pkg


def test_pack_multi_plugin_roundtrip(repo_server, tmp_path):
    """pack A,B produces a multi-plugin .cs2pkg that add --pkg can split back."""
    repo, _server = repo_server
    add_plugin(repo, "Alpha", make_css_package(tmp_path, "Alpha"))
    add_plugin(repo, "Beta", make_css_package(tmp_path, "Beta"))

    pkg_path = build_pkg(repo, ["Alpha", "Beta"], tmp_path / "dist")
    assert pkg_path.name == "plugins.cs2pkg"

    meta = load_pkg_meta(pkg_path)
    assert meta["plugins"] == ["Alpha", "Beta"]
    assert meta["plugin_type"] == "css"

    with zipfile.ZipFile(pkg_path) as zf:
        names = set(zf.namelist())
        assert any("Alpha.dll" in n for n in names)
        assert any("Beta.dll" in n for n in names)

    target_repo = init_repo(tmp_path, repo_name="target")
    rc = cli.main(
        [
            "--repo", str(target_repo),
            "add",
            "--pkg", str(pkg_path),
        ]
    )
    assert rc == 0
    assert sorted(list_plugins(target_repo)) == ["Alpha", "Beta"]
    assert load_manifest(target_repo, "Alpha")["plugin_type"] == "css"
    assert load_manifest(target_repo, "Beta")["plugin_type"] == "css"


def test_cli_pack_multi_plugin(repo_server, tmp_path):
    """cs2lm pack Alpha Beta --out dir writes one multi-plugin .cs2pkg."""
    repo, _server = repo_server
    add_plugin(repo, "Alpha", make_css_package(tmp_path, "Alpha"))
    add_plugin(repo, "Beta", make_css_package(tmp_path, "Beta"))
    out_dir = tmp_path / "releases"
    rc = cli.main(
        ["--repo", str(repo), "pack", "Alpha", "Beta", "--out", str(out_dir)]
    )
    assert rc == 0
    pkg = out_dir / "plugins.cs2pkg"
    assert pkg.exists()
    meta = load_pkg_meta(pkg)
    assert set(meta["plugins"]) == {"Alpha", "Beta"}


def test_add_content_pkg_install_uninstall(repo_server, tmp_path):
    """A content .cs2pkg imports, installs by copy, and uninstalls to trash."""
    _repo, server = repo_server
    pkg_dir = _make_content_package(
        tmp_path, requires_frameworks=["metamod", "css"]
    )
    target_repo = init_repo(tmp_path, repo_name="target", server=server)
    # Import the content directory via add --pkg by packing it first.
    content_repo = init_repo(tmp_path, repo_name="content-src", server=server)
    from cs2lm.manifest import add_content

    add_content(
        content_repo,
        "ContentMod",
        pkg_dir,
        meta=json.loads((pkg_dir / "cs2pkg.json").read_text(encoding="utf-8")),
    )
    pkg_path = build_pkg(content_repo, "ContentMod", tmp_path / "dist")

    # Import into a fresh repo through the CLI.
    rc = cli.main(["--repo", str(target_repo), "add", "--pkg", str(pkg_path)])
    assert rc == 0
    assert "ContentMod" in list_plugins(target_repo)
    manifest = load_manifest(target_repo, "ContentMod")
    assert manifest["kind"] == "content"
    assert manifest["requires_frameworks"] == ["metamod", "css"]
    assert all(link["kind"] == "copy" for link in manifest["links"])

    # Install (server has both frameworks).
    rc = cli.main(["--repo", str(target_repo), "install", "ContentMod"])
    assert rc == 0
    assert (server / "game" / "csgo" / "cfg" / "server.cfg").exists()
    assert (server / "game" / "csgo" / "overrides" / "botprofile.vpk").exists()
    assert (
        server
        / "game"
        / "csgo"
        / "addons"
        / "counterstrikesharp"
        / "plugins"
        / "DemoPlugin"
        / "DemoPlugin.dll"
    ).exists()

    # Uninstall removes the copies (moves them to trash).
    rc = cli.main(["--repo", str(target_repo), "uninstall", "ContentMod"])
    assert rc == 0
    assert not (server / "game" / "csgo" / "cfg" / "server.cfg").exists()
    assert not (server / "game" / "csgo" / "overrides" / "botprofile.vpk").exists()


def test_add_content_requires_frameworks_blocked(repo_server, tmp_path, capsys):
    """Installing a content package without its required frameworks is blocked."""
    repo, server = repo_server
    # Remove CSS framework from the server to simulate a missing framework.
    import shutil

    css_root = server / "game" / "csgo" / "addons" / "counterstrikesharp"
    if css_root.exists():
        shutil.rmtree(css_root)

    from cs2lm.manifest import add_content

    pkg_dir = _make_content_package(
        tmp_path, requires_frameworks=["metamod", "css"]
    )
    add_content(
        repo,
        "ContentMod",
        pkg_dir,
        meta=json.loads((pkg_dir / "cs2pkg.json").read_text(encoding="utf-8")),
    )
    rc = cli.main(["--repo", str(repo), "install", "ContentMod"])
    assert rc != 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "CounterStrikeSharp" in combined or "framework" in combined

    # --force bypasses the guard.
    rc = cli.main(["--repo", str(repo), "install", "ContentMod", "--force"])
    assert rc == 0


def test_content_pack_roundtrip_layout(repo_server, tmp_path):
    """Packing a content entry restores the package top-level roots."""
    repo, _server = repo_server
    pkg_dir = _make_content_package(tmp_path)
    from cs2lm.manifest import add_content

    meta = json.loads((pkg_dir / "cs2pkg.json").read_text(encoding="utf-8"))
    add_content(repo, "ContentMod", pkg_dir, meta=meta)
    pkg_path = build_pkg(repo, "ContentMod", tmp_path / "dist")
    meta_out = load_pkg_meta(pkg_path)
    assert meta_out["kind"] == "content"
    assert meta_out["roots"] == meta["roots"]

    with zipfile.ZipFile(pkg_path) as zf:
        names = set(zf.namelist())
        assert "cfg/server.cfg" in names
        assert "overrides/botprofile.vpk" in names
        assert PKG_META_FILENAME in names


def test_add_content_install_components(repo_server, tmp_path):
    """install --components cfg only installs the selected content roots."""
    repo, server = repo_server
    pkg_dir = _make_content_package(tmp_path)
    from cs2lm.manifest import add_content

    meta = json.loads((pkg_dir / "cs2pkg.json").read_text(encoding="utf-8"))
    add_content(repo, "ContentMod", pkg_dir, meta=meta)

    rc = cli.main(["--repo", str(repo), "install", "ContentMod", "--components", "cfg"])
    assert rc == 0
    assert (server / "game" / "csgo" / "cfg" / "server.cfg").exists()
    assert not (server / "game" / "csgo" / "overrides" / "botprofile.vpk").exists()

    # Uninstall removes only what was installed.
    rc = cli.main(["--repo", str(repo), "uninstall", "ContentMod"])
    assert rc == 0
    assert not (server / "game" / "csgo" / "cfg" / "server.cfg").exists()


def test_split_mixed_framework_package(repo_server, tmp_path):
    """A package with CSS plugins and Metamod addons splits per framework."""
    repo, _server = repo_server
    pkg = tmp_path / "Mixed"
    css_dir = pkg / "addons" / "counterstrikesharp" / "plugins" / "CssPlugin"
    css_dir.mkdir(parents=True)
    (css_dir / "CssPlugin.dll").write_bytes(b"MZ")
    (css_dir / "CssPlugin.deps.json").write_text("{}")

    mm_dir = pkg / "addons" / "BotController" / "bin" / "win64"
    mm_dir.mkdir(parents=True)
    (mm_dir / "BotController.dll").write_bytes(b"MZ")

    from cs2lm.manifest import split_package_plugins

    base = tmp_path / "split"
    base.mkdir(exist_ok=True)
    results = split_package_plugins(pkg, ["CssPlugin", "BotController"], base)
    split_names = [n for n, _ in results]
    assert "CssPlugin" in split_names
    assert "BotController" in split_names