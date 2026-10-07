"""A small local web UI to browse and toggle plugins.

This is intentionally minimal and uses only the standard library. It binds
to ``127.0.0.1`` by default and is meant for a server owner on the same
machine — do not expose it to an untrusted network.

The web UI also exposes a readiness endpoint (``GET /api/health``) and
prints ``CS2LM_READY port=...`` on successful startup so wrapper scripts
(panel launchers) can detect that the server is actually listening, not just
that a process is alive.
"""
from __future__ import annotations

import html
import json
import os
import signal
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cs2lm.config import load_config
from cs2lm.installer import PluginManager


def _plugin_rows(repo: str | Path) -> list[dict]:
    return PluginManager(repo).list_plugins()


def _toggle_plugin(repo: str | Path, name: str, action: str) -> None:
    manager = PluginManager(repo)
    if action == "enable":
        manager.enable(name)
    elif action == "disable":
        manager.disable(name)
    else:
        raise ValueError(f"Unknown action: {action}")


def _cs2_running() -> str:
    """Best-effort detection of whether the CS2 server process is running."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq cs2.exe"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout or ""
            return "online" if "cs2.exe" in out else "offline"
        # Linux: cs2 dedicated server runs as 'cs2' or a srcds variant.
        for pattern in (["pgrep", "-x", "cs2"], ["pgrep", "-f", "srcds"]):
            proc = subprocess.run(pattern, capture_output=True, timeout=5)
            if proc.returncode == 0:
                return "online"
        return "offline"
    except Exception:  # noqa: BLE001 - best effort
        return "unknown"


def _server_status(repo: str | Path) -> dict:
    repo_path = str(Path(repo).resolve())
    try:
        cfg = load_config(repo)
        server_path = str(Path(cfg["server_path"]).resolve())
    except Exception:  # noqa: BLE001
        server_path = "unknown"
    return {
        "web": "online",
        "repo": repo_path,
        "server": server_path,
        "cs2": _cs2_running(),
    }


def _render_page(repo: str | Path, error: str = "", auth_token: str | None = None) -> str:
    rows = _plugin_rows(repo)
    status = _server_status(repo)
    auth_text = "required" if auth_token else "off"
    status_card = f"""<div style="border:1px solid #ccc; border-radius:8px; padding:0.8rem 1.2rem; margin-bottom:1.5rem; display:flex; gap:2rem; flex-wrap:wrap;">
  <div><strong>Web</strong><br><span style="color:green">online</span></div>
  <div><strong>Auth</strong><br>{html.escape(auth_text)}</div>
  <div><strong>CS2 server</strong><br><span style="color:{'green' if status['cs2'] == 'online' else 'orange' if status['cs2'] == 'unknown' else 'red'}">{status['cs2']}</span></div>
  <div><strong>Repo</strong><br><code>{html.escape(status['repo'])}</code></div>
  <div><strong>Server</strong><br><code>{html.escape(status['server'])}</code></div>
</div>"""

    rows_html = []
    for r in rows:
        name = html.escape(r["name"])
        enabled = "enabled" if r["enabled"] else "disabled"
        installed = "yes" if r["installed"] else "no"
        action = "disable" if r["enabled"] else "enable"
        label = "Disable" if r["enabled"] else "Enable"
        token_field = (
            f"<input type='hidden' name='token' value='{html.escape(auth_token)}'>"
            if auth_token
            else ""
        )
        rows_html.append(
            f"<tr>"
            f"<td>{name}</td>"
            f"<td>{html.escape(str(r['type']))}</td>"
            f"<td>{html.escape(str(r['version']))}</td>"
            f"<td>{enabled}</td>"
            f"<td>{installed}</td>"
            f"<td><form method='post' action='/toggle'>"
            f"{token_field}"
            f"<input type='hidden' name='plugin' value='{name}'>"
            f"<input type='hidden' name='action' value='{action}'>"
            f"<button type='submit'>{label}</button>"
            f"</form></td>"
            f"</tr>"
        )
    error_html = (
        f"<p style='color:red'>Error: {html.escape(error)}</p>" if error else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>cs2-link-manager</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
    table {{ border-collapse: collapse; }}
    th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.8rem; }}
    th {{ background: #f0f0f0; }}
    button {{ cursor: pointer; }}
    code {{ background: #f4f4f4; padding: 0.1rem 0.3rem; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>cs2-link-manager</h1>
  {status_card}
  {error_html}
  <table>
    <thead><tr><th>Name</th><th>Type</th><th>Version</th><th>Enabled</th><th>Installed</th><th></th></tr></thead>
    <tbody>{''.join(rows_html) or '<tr><td colspan="6">No plugins in repository.</td></tr>'}</tbody>
  </table>
</body>
</html>
"""


def _render_login() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>cs2-link-manager - auth required</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 2rem; }
    input[type=password] { padding: 0.4rem; }
    button { cursor: pointer; padding: 0.4rem 1rem; }
  </style>
</head>
<body>
  <h1>cs2-link-manager</h1>
  <form method="get" action="/">
    <label>Token: <input type="password" name="token"></label>
    <button type="submit">Unlock</button>
  </form>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    """HTTP handler bound to the server instance holding ``repo``."""

    def _authorized(self, token: str | None) -> bool:
        required = getattr(self.server, "auth_token", None)
        return not required or token == required

    def _request_token(self) -> str | None:
        """Read the auth token from the X-Auth-Token header, then the query
        string / form body. Header support makes script/API usage convenient."""
        header = self.headers.get("X-Auth-Token")
        if header:
            return header
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        return (qs.get("token") or [""])[0]

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/health":
            if not self._authorized(self._request_token()):
                self._send_json({"status": "unauthorized"}, status=401)
                return
            self._send_json(
                {
                    "status": "ok",
                    "service": "cs2-link-manager-web",
                    "repo": self.server.repo,
                    "auth": bool(getattr(self.server, "auth_token", None)),
                }
            )
            return
        if parsed.path != "/":
            self.send_error(404, "Not Found")
            return
        if not self._authorized(self._request_token()):
            self._send_html(_render_login(), status=401)
            return
        self._send_html(_render_page(self.server.repo, auth_token=getattr(self.server, "auth_token", None)))

    def do_POST(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/toggle":
            self.send_error(404, "Not Found")
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        form = urllib.parse.parse_qs(body)
        name = (form.get("plugin") or [""])[0]
        action = (form.get("action") or [""])[0]
        token = self.headers.get("X-Auth-Token") or (form.get("token") or [""])[0]
        if not self._authorized(token):
            self._send_html(_render_login(), status=401)
            return
        try:
            _toggle_plugin(self.server.repo, name, action)
        except Exception as exc:  # noqa: BLE001 - surface to the page
            self._send_html(
                _render_page(
                    self.server.repo,
                    error=str(exc),
                    auth_token=getattr(self.server, "auth_token", None),
                ),
                status=400,
            )
            return
        self.send_response(303)
        location = "/"
        auth = getattr(self.server, "auth_token", None)
        if auth:
            location = f"/?token={urllib.parse.quote(auth)}"
        self.send_header("Location", location)
        self.end_headers()

    def _send_html(self, page: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode("utf-8"))

    def log_message(self, format, *args):  # noqa: A002
        pass


def run_webui(repo: str | Path, host: str = "127.0.0.1", port: int = 8080, auth_token: str | None = None) -> None:
    """Start the web UI. Blocks until interrupted (Ctrl+C / SIGTERM)."""
    server = ThreadingHTTPServer((host, port), _Handler)
    server.repo = str(Path(repo).resolve())
    server.auth_token = auth_token
    print(f"cs2-link-manager Web UI at http://{host}:{port}/  (Ctrl+C to stop)")
    print(f"CS2LM_READY port={port} auth={'required' if auth_token else 'none'}")
    if auth_token:
        print("Authentication required (--auth-token).")

    def _stop(_signum, _frame):  # noqa: ANN001 - signal handler signature
        threading.Thread(target=server.shutdown, daemon=True).start()

    old_sigterm = None
    if hasattr(signal, "SIGTERM"):
        old_sigterm = signal.signal(signal.SIGTERM, _stop)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if old_sigterm is not None:
            signal.signal(signal.SIGTERM, old_sigterm)
        server.server_close()