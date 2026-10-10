"""Tests for the local web UI."""
from __future__ import annotations

import os
import threading
import urllib.error
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


def test_webui_health_endpoint(repo_server, tmp_path):
    import json as jsonlib

    repo, _server = repo_server
    add_plugin(repo, tmp_path, "WebPlugin")
    server, thread, port = start_server(repo, auth_token="secret")
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/health",
            headers={"X-Auth-Token": "secret"},
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = jsonlib.loads(resp.read().decode("utf-8"))
        assert data["status"] == "ok"
        assert data["service"] == "cs2-link-manager-web"
        assert data["auth"] is True

        # Health is a readiness probe: it must work without a token.
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/health")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = jsonlib.loads(resp.read().decode("utf-8"))
        assert data["status"] == "ok"
    finally:
        server.shutdown()
        thread.join()


def test_webui_daemon_writes_pidfile(repo_server, tmp_path):
    """web --daemon spawns a detached child and writes its PID."""
    import signal
    import socket
    import time

    repo, _server = repo_server
    add_plugin(repo, tmp_path, "WebPlugin")

    # Pick a free TCP port.
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    pidfile = tmp_path / "web.pid"
    logfile = tmp_path / "web.log"
    rc = cli.main(
        [
            "--repo",
            str(repo),
            "web",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--auth-token",
            "secret",
            "--daemon",
            "--pidfile",
            str(pidfile),
            "--daemon-log",
            str(logfile),
        ]
    )
    assert rc == 0
    try:
        # PID file appears and the child serves HTTP.
        pid = None
        for _ in range(50):
            if pidfile.exists():
                pid = int(pidfile.read_text(encoding="utf-8").strip())
                break
            time.sleep(0.1)
        assert pid is not None and pid > 0

        reached = False
        for _ in range(50):
            try:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/health",
                    headers={"X-Auth-Token": "secret"},
                )
                with urllib.request.urlopen(req, timeout=1) as resp:
                    assert resp.status == 200
                reached = True
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.1)
        assert reached, "daemon web server did not become ready"
    finally:
        # Cleanup: terminate the child.
        if pidfile.exists():
            try:
                pid = int(pidfile.read_text(encoding="utf-8").strip())
                os.kill(pid, signal.SIGTERM)
            except (OSError, ValueError):
                pass
        time.sleep(0.3)


def test_webui_accepts_auth_token_header(repo_server, tmp_path):
    """Script/API clients can authenticate with X-Auth-Token instead of ?token=."""
    import urllib.error

    repo, _server = repo_server
    add_plugin(repo, tmp_path, "WebPlugin")
    server, thread, port = start_server(repo, auth_token="secret")
    base = f"http://127.0.0.1:{port}"

    try:
        # GET with header.
        req = urllib.request.Request(base + "/", headers={"X-Auth-Token": "secret"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            assert "WebPlugin" in resp.read().decode("utf-8")

        # POST with header.
        data = urllib.parse.urlencode(
            {"plugin": "WebPlugin", "action": "disable"}
        ).encode()
        req = urllib.request.Request(
            base + "/toggle",
            data=data,
            method="POST",
            headers={"X-Auth-Token": "secret"},
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
        manifest = load_manifest(repo, "WebPlugin")
        assert manifest["enabled"] is False

        # Wrong header is rejected.
        req = urllib.request.Request(base + "/", headers={"X-Auth-Token": "wrong"})
        try:
            urllib.request.urlopen(req)
            raise AssertionError("expected HTTPError for wrong header token")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
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


def _read(port, path):
    """GET a path and return (status, body, headers)."""
    import urllib.error

    base = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(base + path) as resp:
            return resp.status, resp.read().decode("utf-8"), resp.headers
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8"), exc.headers


def test_webui_language_switch_zh(repo_server, tmp_path):
    repo, _server = repo_server
    add_plugin(repo, tmp_path, "WebPlugin")
    server, thread, port = start_server(repo)
    try:
        status, body, _ = _read(port, "/?lang=zh")
        assert status == 200
        assert "仓库插件" in body  # Repository heading
        assert "搜索目录" in body  # Search catalog button
        assert "全部更新" in body  # Update all button
        assert "禁用" in body      # Disable button (plugin enabled by default)
        assert 'lang="zh"' in body
    finally:
        server.shutdown()
        thread.join()


def test_webui_language_cookie_persists(repo_server, tmp_path):
    repo, _server = repo_server
    add_plugin(repo, tmp_path, "WebPlugin")
    server, thread, port = start_server(repo)
    try:
        status, body, headers = _read(port, "/?lang=zh")
        assert status == 200
        assert "仓库插件" in body
        assert "lang=zh" in (headers.get("Set-Cookie") or "")

        # A follow-up request without ?lang= but with the cookie stays Chinese.
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/", headers={"Cookie": "lang=zh"}
        )
        with urllib.request.urlopen(req) as resp:
            body2 = resp.read().decode("utf-8")
        assert "仓库插件" in body2

        # Switching back to English overwrites the cookie.
        status, body3, headers3 = _read(port, "/?lang=en")
        assert "Repository" in body3
        assert "lang=en" in (headers3.get("Set-Cookie") or "")
    finally:
        server.shutdown()
        thread.join()


def test_webui_login_language_switch(repo_server, tmp_path):
    repo, _server = repo_server
    add_plugin(repo, tmp_path, "WebPlugin")
    server, thread, port = start_server(repo, auth_token="secret")
    try:
        # Unauthenticated request with ?lang=zh shows the Chinese login page.
        status, body, _ = _read(port, "/?lang=zh")
        assert status == 401
        assert "需要认证" in body
        assert "令牌" in body
        assert "解锁" in body
        assert "WebPlugin" not in body
    finally:
        server.shutdown()
        thread.join()


def test_webui_catalog_status_localized(repo_server, tmp_path):
    import hashlib
    import json
    import zipfile

    repo, _server = repo_server

    # Build a CSS package zip and an index source pointing at it, so the
    # catalog search returns the plugin (like the API catalog test).
    pkg = make_css_package(tmp_path, "WebPlugin")
    zip_path = tmp_path / "webplugin.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(pkg.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(pkg).as_posix())
    index_path = tmp_path / "index.json"
    sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    index_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "plugins": {
                    "WebPlugin": {
                        "id": "WebPlugin",
                        "version": "1.0.0",
                        "download_url": zip_path.as_uri(),
                        "sha256": sha256,
                        "plugin_type": "css",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert cli.main(["--repo", str(repo), "source", "add", index_path.as_uri()]) == 0
    cli.main(["--repo", str(repo), "install", "WebPlugin"])

    server, thread, port = start_server(repo)
    try:
        # English catalog status: "Installed(1.0.0)" (no space).
        status, body, _ = _read(port, "/?q=WebPlugin&lang=en")
        assert status == 200
        assert "Installed(1.0.0)" in body

        # Chinese catalog status: "已装(1.0.0)".
        status, body, _ = _read(port, "/?q=WebPlugin&lang=zh")
        assert status == 200
        assert "已装(1.0.0)" in body
    finally:
        server.shutdown()
        thread.join()