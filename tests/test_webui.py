"""Tests for the local web UI."""
from __future__ import annotations

import threading
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

from cs2lm import cli
from cs2lm import webui
from cs2lm.manifest import load_manifest

from conftest import make_css_package


def start_server(repo):
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui._Handler)
    server.repo = str(repo)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, thread, port


def add_plugin(repo, tmp_path, name):
    cli.main(["--repo", str(repo), "add", name, str(make_css_package(tmp_path, name))])


def test_webui_lists_plugins(repo_server, tmp_path):
    repo, _server = repo_server
    add_plugin(repo, tmp_path, "WebPlugin")
    server, thread, port = start_server(repo)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
            body = resp.read().decode("utf-8")
        assert "WebPlugin" in body
    finally:
        server.shutdown()
        thread.join()


def test_webui_toggle_disable(repo_server, tmp_path):
    repo, _server = repo_server
    add_plugin(repo, tmp_path, "WebPlugin")
    cli.main(["--repo", str(repo), "install", "WebPlugin"])

    server, thread, port = start_server(repo)
    try:
        data = urllib.parse.urlencode(
            {"plugin": "WebPlugin", "action": "disable"}
        ).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/toggle", data=data, method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status in (200, 303)
        manifest = load_manifest(repo, "WebPlugin")
        assert manifest["enabled"] is False
    finally:
        server.shutdown()
        thread.join()


def test_webui_toggle_enable(repo_server, tmp_path):
    repo, _server = repo_server
    add_plugin(repo, tmp_path, "WebPlugin")
    cli.main(["--repo", str(repo), "disable", "WebPlugin"])  # sets enabled=False

    server, thread, port = start_server(repo)
    try:
        data = urllib.parse.urlencode(
            {"plugin": "WebPlugin", "action": "enable"}
        ).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/toggle", data=data, method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status in (200, 303)
        manifest = load_manifest(repo, "WebPlugin")
        assert manifest["enabled"] is True
    finally:
        server.shutdown()
        thread.join()