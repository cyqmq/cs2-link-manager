"""A small local web UI to manage plugins and the server.

The web UI is meant for server owners who cannot use the CLI comfortably. It
uses only the standard library and binds to ``127.0.0.1`` by default — do
not expose it to an untrusted network.

Beyond the plugin toggle page it exposes a JSON API so richer frontends can be
built against the same operations the CLI offers:

* ``GET  /api/health``   — readiness probe
* ``GET  /api/status``   — server status + detected frameworks
* ``GET  /api/plugins``  — repository plugin list
* ``GET  /api/catalog``  — merged source/registry catalog (search)
* ``POST /api/install``  — install a plugin (name or ``#N``)
* ``POST /api/uninstall`` — uninstall a plugin
* ``POST /api/update``   — run the update plan

The readiness endpoint (``GET /api/health``) prints ``CS2LM_READY port=...``
on successful startup so wrapper scripts can detect that the server is
listening.
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
from cs2lm.frameworks import detect_frameworks
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
    server_path = "unknown"
    csgo_rel = "game/csgo"
    try:
        cfg = load_config(repo)
        server_path = str(Path(cfg["server_path"]).resolve())
        csgo_rel = cfg.get("csgo_rel", "game/csgo")
    except Exception:  # noqa: BLE001
        pass
    frameworks: list[dict] = []
    try:
        frameworks = detect_frameworks(server_path, csgo_rel)
    except Exception:  # noqa: BLE001 - server may not exist yet
        pass
    return {
        "web": "online",
        "repo": repo_path,
        "server": server_path,
        "cs2": _cs2_running(),
        "frameworks": frameworks,
    }


def _framework_badges(frameworks: list[dict]) -> str:
    parts = []
    for fw in frameworks:
        color = "green" if fw.get("installed") else "#999"
        parts.append(
            f"<span style='border:1px solid {color}; color:{color}; "
            f"border-radius:10px; padding:0.1rem 0.5rem; font-size:0.8rem;'>"
            f"{html.escape(fw.get('name', fw.get('id', '')))}</span>"
        )
    return " ".join(parts) if parts else "<em>none</em>"


def _catalog_rows(
    repo: str | Path,
    query: str = "",
    source_url: str | None = None,
) -> tuple[list[dict], list[str]]:
    from cs2lm.catalog import search_catalog

    cfg = load_config(repo)
    update_cfg = cfg.get("update", {}) or {}
    timeout = update_cfg.get("timeout", 30)
    api_range = update_cfg.get("api_version_range")
    return search_catalog(
        repo,
        query=query,
        source_url=source_url,
        timeout=timeout,
        api_version_range=api_range,
    )


def _render_page(
    repo: str | Path,
    error: str = "",
    auth_token: str | None = None,
    query: str = "",
    catalog: list[dict] | None = None,
    warnings: list[str] | None = None,
) -> str:
    rows = _plugin_rows(repo)
    status = _server_status(repo)
    auth_text = "required" if auth_token else "off"
    cs2_color = (
        "green" if status["cs2"] == "online"
        else "orange" if status["cs2"] == "unknown"
        else "red"
    )
    badges = _framework_badges(status.get("frameworks") or [])
    status_card = f"""<div style="border:1px solid #ccc; border-radius:8px; padding:0.8rem 1.2rem; margin-bottom:1.5rem; display:flex; gap:2rem; flex-wrap:wrap;">
  <div><strong>Web</strong><br><span style="color:green">online</span></div>
  <div><strong>Auth</strong><br>{html.escape(auth_text)}</div>
  <div><strong>CS2 server</strong><br><span style="color:{cs2_color}">{status['cs2']}</span></div>
  <div><strong>Frameworks</strong><br>{badges}</div>
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
        rows_html.append(
            f"<tr>"
            f"<td>{name}</td>"
            f"<td>{html.escape(str(r['type']))}</td>"
            f"<td>{html.escape(str(r['version']))}</td>"
            f"<td>{enabled}</td>"
            f"<td>{installed}</td>"
            f"<td><form method='post' action='/toggle'>"
            f"{_token_field(auth_token)}"
            f"<input type='hidden' name='plugin' value='{name}'>"
            f"<input type='hidden' name='action' value='{action}'>"
            f"<button type='submit'>{label}</button>"
            f"</form></td>"
            f"</tr>"
        )

    error_html = (
        f"<p style='color:red'>Error: {html.escape(error)}</p>" if error else ""
    )

    catalog_html = ""
    if catalog is not None:
        cat_rows = []
        for item in catalog:
            iname = html.escape(item["name"])
            status_text = html.escape(str(item.get("status") or ""))
            version = html.escape(str(item.get("version") or ""))
            source_label = html.escape(str(item.get("source") or ""))
            desc = html.escape(str(item.get("description") or ""))
            cat_rows.append(
                f"<tr><td>{item.get('index')}</td><td>{iname}</td>"
                f"<td>{version}</td><td>{status_text}</td>"
                f"<td>{source_label}</td><td>{desc}</td>"
                f"<td><form method='post' action='/install'>"
                f"{_token_field(auth_token)}"
                f"<input type='hidden' name='name' value='{iname}'>"
                f"<button type='submit'>Install</button>"
                f"</form></td></tr>"
            )
        warning_html = ""
        for w in warnings or []:
            warning_html += f"<p style='color:orange'>warning: {html.escape(w)}</p>"
        catalog_html = f"""<h2>Catalog</h2>
{warning_html}
<table>
<thead><tr><th>#</th><th>Name</th><th>Version</th><th>Status</th><th>Source</th><th>Description</th><th></th></tr></thead>
<tbody>{''.join(cat_rows) or '<tr><td colspan="7">No plugins found.</td></tr>'}</tbody>
</table>"""

    token_attr = (
        f"value='{html.escape(auth_token)}'" if auth_token else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>cs2-link-manager</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
    table {{ border-collapse: collapse; margin-bottom: 1.5rem; }}
    th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.8rem; }}
    th {{ background: #f0f0f0; }}
    button {{ cursor: pointer; }}
    code {{ background: #f4f4f4; padding: 0.1rem 0.3rem; border-radius: 4px; }}
    input {{ padding: 0.3rem; }}
  </style>
</head>
<body>
  <h1>cs2-link-manager</h1>
  {status_card}
  {error_html}
  <div style="margin-bottom:1.5rem;">
    <form method="get" action="/" style="display:inline-block;">
      <input type="hidden" name="token" {token_attr}>
      <input name="q" placeholder="search plugins…" value="{html.escape(query)}">
      <button type="submit">Search catalog</button>
    </form>
    <form method="post" action="/update" style="display:inline-block;">
      {_token_field(auth_token)}
      <button type="submit">Update all</button>
    </form>
  </div>
  {catalog_html}
  <h2>Repository</h2>
  <table>
    <thead><tr><th>Name</th><th>Type</th><th>Version</th><th>Enabled</th><th>Installed</th><th></th></tr></thead>
    <tbody>{''.join(rows_html) or '<tr><td colspan="6">No plugins in repository.</td></tr>'}</tbody>
  </table>
</body>
</html>
"""


def _token_field(auth_token: str | None) -> str:
    return (
        f"<input type='hidden' name='token' value='{html.escape(auth_token)}'>"
        if auth_token
        else ""
    )


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

    def _send_html(self, page: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode("utf-8"))

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def _root_with_token(self) -> str:
        auth = getattr(self.server, "auth_token", None)
        if auth:
            return f"/?token={urllib.parse.quote(auth)}"
        return "/"

    def _read_body(self) -> dict:
        """Parse a JSON or form-encoded request body into a dict."""
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        ctype = self.headers.get("Content-Type", "")
        if "application/json" in ctype:
            try:
                data = json.loads(raw)
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
        parsed = urllib.parse.parse_qs(raw)
        return {k: (v[0] if v else "") for k, v in parsed.items()}

    def _do_api_install(self, body: dict) -> tuple[dict, int]:
        from cs2lm.catalog import install_plugin

        name = str(body.get("name") or body.get("plugin") or "")
        if not name:
            return {"status": "error", "messages": ["missing 'name'"]}, 400
        try:
            result = install_plugin(
                self.server.repo,
                name,
                dry_run=bool(body.get("dry_run")),
                force=bool(body.get("force")),
                logger=None,
            )
            return result, 200 if result["status"] == "ok" else 400
        except Exception as exc:  # noqa: BLE001 - surface to API
            return {"status": "error", "messages": [str(exc)]}, 400

    def _do_api_update(self, body: dict) -> tuple[dict, int]:
        from cs2lm.updater import plan_and_apply_update

        try:
            plan = plan_and_apply_update(
                self.server.repo,
                dry_run=bool(body.get("dry_run")),
                yes=True,
                remove_orphans=bool(body.get("remove_orphans")),
                logger=None,
            )
            return plan, 200
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}, 400

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        # Readiness probe: deliberately auth-free so wrapper scripts can use it
        # as a health check without knowing the token.
        if parsed.path == "/api/health":
            payload = {
                "status": "ok",
                "service": "cs2-link-manager-web",
                "repo": self.server.repo,
                "auth": bool(getattr(self.server, "auth_token", None)),
            }
            # Daemonized launches echo their unique nonce so the parent can
            # verify this is *our* child, not another daemon on the same port.
            nonce = getattr(self.server, "daemon_nonce", None)
            if nonce:
                payload["nonce"] = nonce
            self._send_json(payload)
            return
        token = self._request_token()
        if not self._authorized(token):
            if parsed.path == "/":
                self._send_html(_render_login(), status=401)
            else:
                self._send_json({"status": "unauthorized"}, status=401)
            return
        if parsed.path == "/api/status":
            self._send_json(_server_status(self.server.repo))
            return
        if parsed.path == "/api/plugins":
            self._send_json({"plugins": _plugin_rows(self.server.repo)})
            return
        if parsed.path == "/api/catalog":
            qs = urllib.parse.parse_qs(parsed.query)
            try:
                rows, warnings = _catalog_rows(
                    self.server.repo,
                    query=(qs.get("query") or qs.get("q") or [""])[0],
                    source_url=(qs.get("source") or [None])[0],
                )
            except Exception as exc:  # noqa: BLE001
                self._send_json({"status": "error", "message": str(exc)}, 400)
                return
            self._send_json({"results": rows, "warnings": warnings})
            return
        if parsed.path != "/":
            self.send_error(404, "Not Found")
            return
        qs = urllib.parse.parse_qs(parsed.query)
        query = (qs.get("q") or [""])[0]
        warnings: list[str] = []
        catalog = None
        if query or "catalog" in qs:
            try:
                catalog, warnings = _catalog_rows(
                    self.server.repo, query=query
                )
            except Exception as exc:  # noqa: BLE001
                self._send_html(
                    _render_page(
                        self.server.repo,
                        error=str(exc),
                        auth_token=getattr(self.server, "auth_token", None),
                    ),
                    status=400,
                )
                return
        self._send_html(
            _render_page(
                self.server.repo,
                auth_token=getattr(self.server, "auth_token", None),
                query=query,
                catalog=catalog,
                warnings=warnings,
            )
        )

    def do_POST(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        body = self._read_body()
        token = self.headers.get("X-Auth-Token") or str(body.get("token") or "")
        if not self._authorized(token):
            self._send_json({"status": "unauthorized"}, status=401)
            return

        if parsed.path in ("/api/install", "/install"):
            payload, code = self._do_api_install(body)
            if parsed.path == "/api/install":
                self._send_json(payload, status=code)
            else:
                self._redirect(self._root_with_token())
            return
        if parsed.path == "/api/uninstall":
            name = str(body.get("name") or body.get("plugin") or "")
            if not name:
                self._send_json({"status": "error", "messages": ["missing 'name'"]}, 400)
                return
            try:
                manager = PluginManager(self.server.repo)
                manager.uninstall(name)
                self._send_json({"status": "ok", "name": name})
            except Exception as exc:  # noqa: BLE001
                self._send_json({"status": "error", "messages": [str(exc)]}, 400)
            return
        if parsed.path in ("/api/update", "/update"):
            payload, code = self._do_api_update(body)
            if parsed.path == "/api/update":
                self._send_json(payload, status=code)
            else:
                self._redirect(self._root_with_token())
            return
        if parsed.path == "/toggle":
            name = str(body.get("plugin") or "")
            action = str(body.get("action") or "")
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
            self._redirect(self._root_with_token())
            return
        self.send_error(404, "Not Found")

    def log_message(self, format, *args):  # noqa: A002
        pass


def run_webui(repo: str | Path, host: str = "127.0.0.1", port: int = 8080, auth_token: str | None = None) -> None:
    """Start the web UI. Blocks until interrupted (Ctrl+C / SIGTERM)."""
    try:
        server = ThreadingHTTPServer((host, port), _Handler)
    except OverflowError as exc:
        raise ValueError(f"Invalid port: {port}. Port must be between 0 and 65535.") from exc
    server.repo = str(Path(repo).resolve())
    server.auth_token = auth_token
    server.daemon_nonce = os.environ.get("CS2LM_READY_NONCE")
    actual_port = server.server_address[1]
    print(f"cs2-link-manager Web UI at http://{host}:{actual_port}/  (Ctrl+C to stop)")
    print(f"CS2LM_READY port={actual_port} auth={'required' if auth_token else 'none'}")
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