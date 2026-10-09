"""Tests for the unified catalog: search, #N install, source filtering."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from cs2lm import cli
from cs2lm.manifest import add_plugin, list_plugins

from conftest import make_css_package


def _zip_package(pkg: Path, zip_path: Path) -> Path:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(pkg.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(pkg).as_posix())
    return zip_path


def _write_index(tmp_path: Path, plugins: dict, name: str = "test-source") -> Path:
    """Write an index.json file (auto-filling sha256 for file:// assets)."""
    from urllib.parse import urlparse
    from urllib.request import url2pathname

    def _with_sha(entry: dict) -> dict:
        out = dict(entry)
        if "sha256" not in out:
            url = out.get("download_url") or out.get("url") or ""
            if url.startswith("file:"):
                zip_path = Path(url2pathname(urlparse(url).path))
                if zip_path.is_file():
                    out["sha256"] = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        return out

    path = tmp_path / "index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "name": name,
                "plugins": {k: _with_sha(v) for k, v in plugins.items()},
            }
        ),
        encoding="utf-8",
    )
    return path


def _add_source(repo: Path, index_path: Path) -> None:
    assert cli.main(["--repo", str(repo), "source", "add", index_path.as_uri()]) == 0


def test_cli_search_shows_catalog_statuses(repo_server, tmp_path, capsys):
    """search merges index sources + registry, annotates install status."""
    repo, _server = repo_server
    add_plugin(repo, "Installed", make_css_package(tmp_path, "Installed"))
    from cs2lm.installer import PluginManager

    PluginManager(repo).install("Installed")

    zip_new = _zip_package(make_css_package(tmp_path, "NewOne"), tmp_path / "new.zip")
    zip_reg = _zip_package(make_css_package(tmp_path, "RegPlugin"), tmp_path / "reg.zip")
    index_path = _write_index(
        tmp_path,
        {
            "Installed": {
                "id": "Installed",
                "version": "1.0.0",
                "download_url": zip_new.as_uri(),
                "description": "local plugin",
                "plugin_type": "css",
            },
            "NewOne": {
                "id": "NewOne",
                "version": "1.0.0",
                "download_url": zip_new.as_uri(),
                "description": "brand new",
                "plugin_type": "css",
            },
        },
        name="index-a",
    )
    _add_source(repo, index_path)
    assert cli.main(["--repo", str(repo), "registry", "add", "RegPlugin", zip_reg.as_uri()]) == 0

    assert cli.main(["--repo", str(repo), "search"]) == 0
    out = capsys.readouterr().out
    assert "Installed" in out
    assert "NewOne" in out
    assert "RegPlugin" in out
    assert "已装(1.0.0)" in out  # Installed status
    assert "未安装" in out
    assert "index-a" in out
    assert "registry" in out

    # Snapshot written for install #N.
    snap = json.loads((repo / "state" / "search_result.json").read_text(encoding="utf-8"))
    results = snap["results"]
    assert results[0]["index"] == 1
    assert any(r["name"] == "RegPlugin" and r["source_kind"] == "registry" for r in results)


def test_cli_search_filter_source(repo_server, tmp_path, capsys):
    """--source <url> restricts the catalog to one source."""
    repo, _server = repo_server
    zip_a = _zip_package(make_css_package(tmp_path, "OnlyA"), tmp_path / "a.zip")
    zip_b = _zip_package(make_css_package(tmp_path, "OnlyB"), tmp_path / "b.zip")
    index_a = _write_index(
        tmp_path, {"OnlyA": {"id": "OnlyA", "version": "1.0.0", "download_url": zip_a.as_uri(), "plugin_type": "css"}}, name="index-a"
    )
    index_b = _write_index(
        tmp_path / "b.json", {"OnlyB": {"id": "OnlyB", "version": "1.0.0", "download_url": zip_b.as_uri(), "plugin_type": "css"}}, name="index-b"
    )
    _add_source(repo, index_a)
    assert cli.main(["--repo", str(repo), "source", "add", index_b.as_uri()]) == 0

    assert cli.main(["--repo", str(repo), "search", "--source", index_a.as_uri()]) == 0
    out = capsys.readouterr().out
    assert "OnlyA" in out
    assert "OnlyB" not in out


def test_cli_install_by_catalog_reference(repo_server, tmp_path):
    """install #N resolves the catalog snapshot and installs from the source."""
    repo, _server = repo_server
    zip_path = _zip_package(make_css_package(tmp_path, "CatPlugin"), tmp_path / "cat.zip")
    index_path = _write_index(
        tmp_path,
        {"CatPlugin": {"id": "CatPlugin", "version": "2.0.0", "download_url": zip_path.as_uri(), "plugin_type": "css"}},
    )
    _add_source(repo, index_path)

    assert cli.main(["--repo", str(repo), "search"]) == 0
    assert cli.main(["--repo", str(repo), "install", "#1"]) == 0
    assert "CatPlugin" in list_plugins(repo)
    from cs2lm.manifest import load_manifest

    assert load_manifest(repo, "CatPlugin")["version"] == "2.0.0"


def test_cli_install_by_name_falls_back_to_source(repo_server, tmp_path):
    """install <name> falls back to configured sources when not in the repo."""
    repo, _server = repo_server
    zip_path = _zip_package(make_css_package(tmp_path, "Fallback"), tmp_path / "fb.zip")
    index_path = _write_index(
        tmp_path,
        {"Fallback": {"id": "Fallback", "version": "1.0.0", "download_url": zip_path.as_uri(), "plugin_type": "css"}},
    )
    _add_source(repo, index_path)

    assert cli.main(["--repo", str(repo), "install", "Fallback"]) == 0
    assert "Fallback" in list_plugins(repo)


def test_cli_install_missing_plugin_errors_clearly(repo_server, tmp_path, capsys):
    """install of an unknown plugin fails with a helpful message."""
    repo, _server = repo_server
    assert cli.main(["--repo", str(repo), "install", "Nope"]) == 1
    out = capsys.readouterr().err
    assert "not in the repository" in out
    assert "search" in out


def test_cli_install_reports_missing_dependency(repo_server, tmp_path, capsys):
    """a requires dependency absent from every source is reported, not fatal."""
    repo, _server = repo_server
    zip_main = _zip_package(make_css_package(tmp_path, "NeedsLib"), tmp_path / "n.zip")
    index_path = _write_index(
        tmp_path,
        {
            "NeedsLib": {
                "id": "NeedsLib",
                "version": "1.0.0",
                "download_url": zip_main.as_uri(),
                "plugin_type": "css",
                "requires": {"GhostLib": ">=1.0.0"},
            }
        },
    )
    _add_source(repo, index_path)

    # install returns an error and explains which dependency is missing.
    assert cli.main(["--repo", str(repo), "install", "NeedsLib"]) == 1
    captured = capsys.readouterr()
    assert "GhostLib" in captured.err
    assert "Install failed" in captured.out