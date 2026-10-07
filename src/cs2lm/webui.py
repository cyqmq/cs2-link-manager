"""A small local web UI to browse and toggle plugins.

This is intentionally minimal and uses only the standard library. It binds
to ``127.0.0.1`` by default and is meant for a server owner on the same
machine — do not expose it to an untrusted network.
"""
from __future__ import annotations

import html
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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


def _render_page(repo: str | Path, error: str = "", auth_token: str | None = None) -> str:
    rows = _plugin_rows(repo)
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
  </style>
</head>
<body>
  <h1>cs2-link-manager</h1>
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

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/":
            self.send_error(404, "Not Found")
            return
        qs = urllib.parse.parse_qs(parsed.query)
        token = (qs.get("token") or [""])[0]
        if not self._authorized(token):
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
        token = (form.get("token") or [""])[0]
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
    """Start the web UI. Blocks until interrupted (Ctrl+C)."""
    server = ThreadingHTTPServer((host, port), _Handler)
    server.repo = str(Path(repo).resolve())
    server.auth_token = auth_token
    print(f"cs2-link-manager Web UI at http://{host}:{port}/  (Ctrl+C to stop)")
    if auth_token:
        print("Authentication required (--auth-token).")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()