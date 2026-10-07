"""Tests for adding plugins from a URL (download + extract)."""
from __future__ import annotations

import functools
import http.server
import socketserver
import threading
import zipfile
from contextlib import contextmanager
from pathlib import Path

from cs2lm import cli
from cs2lm.manifest import add_plugin, list_plugins, load_manifest
from cs2lm.url_add import DownloadError, download_and_extract

from conftest import make_css_package


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass


@contextmanager
def serve_dir(dir_path: Path):
    handler = functools.partial(_QuietHandler, directory=str(dir_path))
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{port}"
        httpd.shutdown()


def make_zip(tmp_path: Path, pkg_dir: Path, zip_name: str = "plugin.zip", wrap: bool = False) -> Path:
    zip_path = tmp_path / zip_name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        base = pkg_dir
        if wrap:
            zf.write(pkg_dir, pkg_dir.name)  # top-level directory entry
            base = pkg_dir.parent
        for f in sorted(pkg_dir.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(base).as_posix())
    return zip_path


def test_download_and_extract_top_level_addons(tmp_path):
    pkg = make_css_package(tmp_path, "TopLevel")
    zip_path = make_zip(tmp_path, pkg)
    dest = tmp_path / "out"
    with serve_dir(zip_path.parent) as base_url:
        root = download_and_extract(f"{base_url}/{zip_path.name}", dest)
    assert (root / "addons" / "counterstrikesharp" / "plugins" / "TopLevel").is_dir()


def test_download_and_extract_single_wrapper(tmp_path):
    pkg = make_css_package(tmp_path, "Wrapped")
    zip_path = make_zip(tmp_path, pkg, wrap=True)
    dest = tmp_path / "out"
    with serve_dir(zip_path.parent) as base_url:
        root = download_and_extract(f"{base_url}/{zip_path.name}", dest)
    assert (root / "addons" / "counterstrikesharp" / "plugins" / "Wrapped").is_dir()


def test_download_error(tmp_path):
    dest = tmp_path / "out"
    with serve_dir(tmp_path) as base_url:
        try:
            download_and_extract(f"{base_url}/missing.zip", dest)
        except DownloadError:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected DownloadError")


def test_cli_add_from_url(repo_server, tmp_path):
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "UrlPlugin")
    zip_path = make_zip(tmp_path, pkg)
    with serve_dir(zip_path.parent) as base_url:
        rc = cli.main(
            [
                "--repo",
                str(repo),
                "add",
                "UrlPlugin",
                "--url",
                f"{base_url}/{zip_path.name}",
            ]
        )
    assert rc == 0
    assert "UrlPlugin" in list_plugins(repo)
    manifest = load_manifest(repo, "UrlPlugin")
    assert manifest["plugin_type"] == "css"
    assert any(f["source"].endswith("UrlPlugin.dll") for f in manifest["files"])


def test_cli_add_url_and_path_conflict(repo_server, tmp_path):
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "UrlPlugin")
    zip_path = make_zip(tmp_path, pkg)
    with serve_dir(zip_path.parent) as base_url:
        rc = cli.main(
            [
                "--repo",
                str(repo),
                "add",
                "UrlPlugin",
                str(pkg),
                "--url",
                f"{base_url}/{zip_path.name}",
            ]
        )
    assert rc == 1  # clean error, plugin not added
    assert "UrlPlugin" not in list_plugins(repo)


def test_add_plugin_from_url_repo(repo_server, tmp_path):
    """The downloaded path can be fed directly into manifest.add_plugin."""
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "DirectPlugin")
    zip_path = make_zip(tmp_path, pkg)
    with serve_dir(zip_path.parent) as base_url:
        root = download_and_extract(f"{base_url}/{zip_path.name}", tmp_path / "dl")
        add_plugin(repo, "DirectPlugin", root)
    assert "DirectPlugin" in list_plugins(repo)