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


def start_server(repo, auth_token=None):
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui._Handler)
    server.repo = str(repo)
    server.auth_token = auth_token
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


def test_webui_requires_token(repo_server, tmp_path):
    import urllib.error

    repo, _server = repo_server
    add_plugin(repo, tmp_path, "WebPlugin")
    server, thread, port = start_server(repo, auth_token="secret")
    base = f"http://127.0.0.1:{port}"

    def get(path):
        try:
            with urllib.request.urlopen(base + path) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    try:
        # Without token: login page.
        status, body = get("/")
        assert status == 401
        assert "Token" in body
        assert "WebPlugin" not in body
        # With token: plugin list.
        status, body = get("/?token=secret")
        assert status == 200
        assert "WebPlugin" in body
        # Wrong token still blocked.
        status, _ = get("/?token=wrong")
        assert status == 401

        # POST /toggle without token -> 401.
        data = urllib.parse.urlencode(
            {"plugin": "WebPlugin", "action": "disable"}
        ).encode()
        req = urllib.request.Request(base + "/toggle", data=data, method="POST")
        try:
            urllib.request.urlopen(req)
            raise AssertionError("expected HTTPError for unauthenticated POST")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401

        # POST /toggle with token -> 303.
        data = urllib.parse.urlencode(
            {"plugin": "WebPlugin", "action": "disable", "token": "secret"}
        ).encode()
        req = urllib.request.Request(base + "/toggle", data=data, method="POST")
        with urllib.request.urlopen(req) as resp:
            assert resp.status in (200, 303)
        manifest = load_manifest(repo, "WebPlugin")
        assert manifest["enabled"] is False
    finally:
        server.shutdown()
        thread.join()