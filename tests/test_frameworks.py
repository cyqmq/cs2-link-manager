"""Tests for multi-framework support, framework detection, and the web API."""
from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

from cs2lm import cli, webui
from cs2lm.frameworks import (
    detect_frameworks,
    framework_ids,
    normalize_framework,
)
from cs2lm.installer import InstallError, PluginManager
from cs2lm.manifest import (
    add_plugin,
    classify_plugin,
    list_plugins,
    load_manifest,
)

from conftest import make_css_package


def make_framework_package(tmp_path: Path, root: str, name: str) -> Path:
    pkg = tmp_path / name
    plugin_dir = pkg / "addons" / root / "plugins" / name
    plugin_dir.mkdir(parents=True)
    (plugin_dir / f"{name}.dll").write_bytes(b"MZ")
    cfg_dir = pkg / "addons" / root / "configs" / "plugins" / name
    cfg_dir.mkdir(parents=True)
    (cfg_dir / f"{name}.json").write_text("{}")
    return pkg


def start_server(repo, auth_token=None):
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui._Handler)
    server.repo = str(repo)
    server.auth_token = auth_token
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, thread, port


# ---------------------------------------------------------------------------
# Classification & normalization
# ---------------------------------------------------------------------------


def test_framework_ids():
    ids = framework_ids()
    assert "css" in ids
    assert "metamod" in ids
    assert "swiftly" in ids
    assert "plugify" in ids
    assert "modsharp" in ids


def test_normalize_framework_aliases():
    assert normalize_framework("counterstrikesharp") == "css"
    assert normalize_framework("cs#") == "css"
    assert normalize_framework("metamod-source") == "metamod"
    assert normalize_framework("swiftly-s2") == "swiftly"
    assert normalize_framework("plugify") == "plugify"
    assert normalize_framework("mod-sharp") == "modsharp"
    assert normalize_framework("unknown") is None


def test_classify_plugin_detects_frameworks(tmp_path):
    swiftly = make_framework_package(tmp_path, "swiftly", "SwPlugin")
    plugify = make_framework_package(tmp_path, "plugify", "PlPlugin")
    modsharp = make_framework_package(tmp_path, "modsharp", "MsPlugin")
    assert classify_plugin(swiftly) == "swiftly"
    assert classify_plugin(plugify) == "plugify"
    assert classify_plugin(modsharp) == "modsharp"


def test_classify_plugin_type_hint(tmp_path):
    css = make_css_package(tmp_path, "HintPlugin")
    assert classify_plugin(css, "plugify") == "plugify"


# ---------------------------------------------------------------------------
# Server-side framework detection
# ---------------------------------------------------------------------------


def test_detect_frameworks_reports_installed(repo_server):
    repo, server = repo_server
    entries = {e["id"]: e for e in detect_frameworks(server, "game/csgo")}
    assert entries["css"]["installed"] is True
    assert entries["metamod"]["installed"] is True
    assert entries["swiftly"]["installed"] is False
    assert entries["plugify"]["installed"] is False
    assert entries["modsharp"]["installed"] is False


# ---------------------------------------------------------------------------
# Multi-framework add/install + install guard
# ---------------------------------------------------------------------------


def test_add_plugin_swiftly_links(repo_server, tmp_path):
    repo, _server = repo_server
    pkg = make_framework_package(tmp_path, "swiftly", "SwPlugin")
    add_plugin(repo, "SwPlugin", pkg)
    manifest = load_manifest(repo, "SwPlugin")
    assert manifest["plugin_type"] == "swiftly"
    assert any("addons/swiftly/plugins/SwPlugin" in l["target"] for l in manifest["links"])


def test_install_guard_blocks_missing_framework(repo_server, tmp_path):
    repo, _server = repo_server
    pkg = make_framework_package(tmp_path, "plugify", "PlPlugin")
    add_plugin(repo, "PlPlugin", pkg)

    # Plugify is not installed on the fixture server -> blocked.
    try:
        PluginManager(repo).install("PlPlugin")
        raise AssertionError("expected InstallError for missing framework")
    except InstallError as exc:
        assert "Plugify" in str(exc)

    # --force bypasses the guard.
    PluginManager(repo, force=True).install("PlPlugin")
    manifest = load_manifest(repo, "PlPlugin")
    assert manifest["enabled"] is True


def test_install_guard_allows_css(repo_server, tmp_path):
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "CssPlugin")
    add_plugin(repo, "CssPlugin", pkg)
    PluginManager(repo).install("CssPlugin")
    assert load_manifest(repo, "CssPlugin")["enabled"] is True


# ---------------------------------------------------------------------------
# Web API
# ---------------------------------------------------------------------------


def _zip_package(pkg: Path, zip_path: Path) -> Path:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(pkg.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(pkg).as_posix())
    return zip_path


def _write_index(tmp_path: Path, plugins: dict) -> Path:
    path = tmp_path / "index.json"
    for entry in plugins.values():
        if "sha256" not in entry:
            url = entry.get("download_url", "")
            if url.startswith("file:"):
                from urllib.parse import urlparse
                from urllib.request import url2pathname

                zip_path = Path(url2pathname(urlparse(url).path))
                if zip_path.is_file():
                    entry["sha256"] = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": 1, "plugins": plugins}), encoding="utf-8")
    return path


def test_webui_api_status_reports_frameworks(repo_server):
    repo, _server = repo_server
    server, thread, port = start_server(repo)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data["web"] == "online"
        fw = {e["id"]: e for e in data["frameworks"]}
        assert fw["css"]["installed"] is True
        assert "swiftly" in fw
    finally:
        server.shutdown()
        thread.join()


def test_webui_api_catalog_and_install(repo_server, tmp_path):
    repo, _server = repo_server
    zip_path = _zip_package(make_css_package(tmp_path, "ApiPlugin"), tmp_path / "api.zip")
    index_path = _write_index(
        tmp_path,
        {
            "ApiPlugin": {
                "id": "ApiPlugin",
                "version": "1.0.0",
                "download_url": zip_path.as_uri(),
                "plugin_type": "css",
            }
        },
    )
    assert cli.main(["--repo", str(repo), "source", "add", index_path.as_uri()]) == 0

    server, thread, port = start_server(repo)
    base = f"http://127.0.0.1:{port}"
    try:
        # Catalog search returns the plugin.
        with urllib.request.urlopen(f"{base}/api/catalog?query=Api") as resp:
            catalog = json.loads(resp.read().decode("utf-8"))
        assert catalog["results"][0]["name"] == "ApiPlugin"

        # Install via API.
        body = json.dumps({"name": "ApiPlugin"}).encode("utf-8")
        req = urllib.request.Request(
            base + "/api/install",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        assert result["status"] == "ok"
        assert "ApiPlugin" in list_plugins(repo)
    finally:
        server.shutdown()
        thread.join()


def test_webui_api_update_plan(repo_server):
    repo, _server = repo_server
    server, thread, port = start_server(repo)
    try:
        body = json.dumps({"dry_run": True}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/update",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            plan = json.loads(resp.read().decode("utf-8"))
        assert "sources" in plan
        assert "install" in plan
        assert "update" in plan
        assert "orphans" in plan
    finally:
        server.shutdown()
        thread.join()


def test_webui_api_uninstall(repo_server, tmp_path):
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "UnPlugin")
    add_plugin(repo, "UnPlugin", pkg)
    PluginManager(repo).install("UnPlugin")

    server, thread, port = start_server(repo)
    try:
        body = json.dumps({"name": "UnPlugin"}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/uninstall",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        assert result["status"] == "ok"
        assert load_manifest(repo, "UnPlugin")["enabled"] is False
    finally:
        server.shutdown()
        thread.join()