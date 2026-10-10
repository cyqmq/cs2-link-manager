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


# ---------------------------------------------------------------------------
# Lightweight i18n (English / Chinese)
# ---------------------------------------------------------------------------

_I18N: dict[str, dict[str, str]] = {
    "en": {
        "auth_required": "auth required",
        "web": "Web",
        "auth": "Auth",
        "cs2_server": "CS2 server",
        "frameworks": "Frameworks",
        "repo": "Repo",
        "server": "Server",
        "online": "online",
        "offline": "offline",
        "unknown": "unknown",
        "required": "required",
        "off": "off",
        "none": "none",
        "enabled": "enabled",
        "disabled": "disabled",
        "yes": "yes",
        "no": "no",
        "enable": "Enable",
        "disable": "Disable",
        "error": "Error",
        "warning": "warning",
        "catalog": "Catalog",
        "category": "Category",
        "name": "Name",
        "type": "Type",
        "version": "Version",
        "status": "Status",
        "source": "Source",
        "description": "Description",
        "install": "Install",
        "installed": "Installed",
        "no_plugins_found": "No plugins found.",
        "search_placeholder": "search plugins…",
        "search_catalog": "Search catalog",
        "update_all": "Update all",
        "repository": "Repository",
        "no_plugins_in_repo": "No plugins in repository.",
        "token": "Token",
        "unlock": "Unlock",
        "missing_name": "missing 'name'",
        "unknown_action": "Unknown action",
        "not_found": "Not Found",
    },
    "zh": {
        "auth_required": "需要认证",
        "web": "Web",
        "auth": "认证",
        "cs2_server": "CS2 服务器",
        "frameworks": "框架",
        "repo": "仓库",
        "server": "服务器",
        "online": "在线",
        "offline": "离线",
        "unknown": "未知",
        "required": "需要",
        "off": "关闭",
        "none": "无",
        "enabled": "已启用",
        "disabled": "已禁用",
        "yes": "是",
        "no": "否",
        "enable": "启用",
        "disable": "禁用",
        "error": "错误",
        "warning": "警告",
        "catalog": "插件目录",
        "category": "分类",
        "name": "名称",
        "type": "类型",
        "version": "版本",
        "status": "状态",
        "source": "来源",
        "description": "描述",
        "install": "安装",
        "installed": "已安装",
        "no_plugins_found": "未找到插件。",
        "search_placeholder": "搜索插件…",
        "search_catalog": "搜索目录",
        "update_all": "全部更新",
        "repository": "仓库插件",
        "no_plugins_in_repo": "仓库中没有插件。",
        "token": "令牌",
        "unlock": "解锁",
        "missing_name": "缺少 'name'",
        "unknown_action": "未知操作",
        "not_found": "未找到",
    },
}

_LANG_CODES = ("en", "zh")


def _t(lang: str, key: str) -> str:
    """Translate a UI string. Falls back to English for unknown keys."""
    table = _I18N.get(lang) or _I18N["en"]
    return table.get(key, _I18N["en"].get(key, key))


def _localize_status(status: str, lang: str) -> str:
    """Translate the Chinese catalog status strings for the English UI."""
    if lang == "zh":
        return status
    return (
        status.replace("仓库", "In repo")
        .replace("未链接", "not linked")
        .replace("已装", "Installed")
        .replace("未安装", "Not installed")
    )


def _lang_links(lang: str, query: str = "", auth_token: str | None = None) -> str:
    """Language switcher links that preserve token and current search query."""
    token_part = f"&token={urllib.parse.quote(auth_token)}" if auth_token else ""
    q_part = f"&q={urllib.parse.quote(query)}" if query else ""
    zh = f'<a href="/?lang=zh{token_part}{q_part}">中文</a>'
    en = f'<a href="/?lang=en{token_part}{q_part}">English</a>'
    if lang == "zh":
        zh = "<span>中文</span>"
    else:
        en = "<span>English</span>"
    return (
        f"<div style='float:right;'>"
        f"{zh} | {en}"
        f"</div>"
    )


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


def _framework_badges(frameworks: list[dict], lang: str = "en") -> str:
    parts = []
    for fw in frameworks:
        color = "green" if fw.get("installed") else "#999"
        parts.append(
            f"<span style='border:1px solid {color}; color:{color}; "
            f"border-radius:10px; padding:0.1rem 0.5rem; font-size:0.8rem;'>"
            f"{html.escape(fw.get('name', fw.get('id', '')))}</span>"
        )
    none_text = _t(lang, "none")
    return " ".join(parts) if parts else f"<em>{none_text}</em>"


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
    lang: str = "en",
) -> str:
    if lang not in _LANG_CODES:
        lang = "en"
    rows = _plugin_rows(repo)
    status = _server_status(repo)
    auth_text = _t(lang, "required") if auth_token else _t(lang, "off")
    cs2_status = _t(lang, status["cs2"]) if status["cs2"] in ("online", "offline", "unknown") else status["cs2"]
    cs2_color = (
        "green" if status["cs2"] == "online"
        else "orange" if status["cs2"] == "unknown"
        else "red"
    )
    badges = _framework_badges(status.get("frameworks") or [], lang)
    status_card = f"""<div style="border:1px solid #ccc; border-radius:8px; padding:0.8rem 1.2rem; margin-bottom:1.5rem; display:flex; gap:2rem; flex-wrap:wrap;">
  <div><strong>{_t(lang, 'web')}</strong><br><span style="color:green">{_t(lang, 'online')}</span></div>
  <div><strong>{_t(lang, 'auth')}</strong><br>{html.escape(auth_text)}</div>
  <div><strong>{_t(lang, 'cs2_server')}</strong><br><span style="color:{cs2_color}">{cs2_status}</span></div>
  <div><strong>{_t(lang, 'frameworks')}</strong><br>{badges}</div>
  <div><strong>{_t(lang, 'repo')}</strong><br><code>{html.escape(status['repo'])}</code></div>
  <div><strong>{_t(lang, 'server')}</strong><br><code>{html.escape(status['server'])}</code></div>
</div>"""

    rows_html = []
    for r in rows:
        name = html.escape(r["name"])
        enabled = _t(lang, "enabled") if r["enabled"] else _t(lang, "disabled")
        installed = _t(lang, "yes") if r["installed"] else _t(lang, "no")
        action = "disable" if r["enabled"] else "enable"
        label = _t(lang, "disable") if r["enabled"] else _t(lang, "enable")
        rows_html.append(
            f"<tr>"
            f"<td>{name}</td>"
            f"<td>{html.escape(str(r['type']))}</td>"
            f"<td>{html.escape(str(r['version']))}</td>"
            f"<td>{html.escape(str(r.get('category') or ''))}</td>"
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
        f"<p style='color:red'>{_t(lang, 'error')}: {html.escape(error)}</p>"
        if error
        else ""
    )

    catalog_html = ""
    if catalog is not None:
        cat_rows = []
        for item in catalog:
            iname = html.escape(item["name"])
            status_text = _localize_status(str(item.get("status") or ""), lang)
            status_text = html.escape(status_text)
            version = html.escape(str(item.get("version") or ""))
            source_label = html.escape(str(item.get("source") or ""))
            category = str(item.get("category") or "")
            desc = html.escape(str(item.get("description") or ""))
            if category:
                desc = f"[{html.escape(category)}] {desc}"
            cat_rows.append(
                f"<tr><td>{item.get('index')}</td><td>{iname}</td>"
                f"<td>{version}</td><td>{status_text}</td>"
                f"<td>{source_label}</td><td>{desc}</td>"
                f"<td><form method='post' action='/install'>"
                f"{_token_field(auth_token)}"
                f"<input type='hidden' name='name' value='{iname}'>"
                f"<button type='submit'>{_t(lang, 'install')}</button>"
                f"</form></td></tr>"
            )
        warning_html = ""
        for w in warnings or []:
            warning_html += (
                f"<p style='color:orange'>{_t(lang, 'warning')}: {html.escape(w)}</p>"
            )
        no_results = _t(lang, "no_plugins_found")
        catalog_html = f"""<h2>{_t(lang, 'catalog')}</h2>
{warning_html}
<table>
<thead><tr><th>#</th><th>{_t(lang, 'name')}</th><th>{_t(lang, 'version')}</th><th>{_t(lang, 'status')}</th><th>{_t(lang, 'source')}</th><th>{_t(lang, 'description')}</th><th></th></tr></thead>
<tbody>{''.join(cat_rows) or f'<tr><td colspan="7">{no_results}</td></tr>'}</tbody>
</table>"""

    token_attr = (
        f"value='{html.escape(auth_token)}'" if auth_token else ""
    )
    no_plugins_in_repo = _t(lang, "no_plugins_in_repo")
    return f"""<!doctype html>
<html lang="{lang}">
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
  <h1>cs2-link-manager {_lang_links(lang, query, auth_token)}</h1>
  {status_card}
  {error_html}
  <div style="margin-bottom:1.5rem;">
    <form method="get" action="/" style="display:inline-block;">
      <input type="hidden" name="token" {token_attr}>
      <input name="q" placeholder="{_t(lang, 'search_placeholder')}" value="{html.escape(query)}">
      <button type="submit">{_t(lang, 'search_catalog')}</button>
    </form>
    <form method="post" action="/update" style="display:inline-block;">
      {_token_field(auth_token)}
      <button type="submit">{_t(lang, 'update_all')}</button>
    </form>
  </div>
  {catalog_html}
  <h2>{_t(lang, 'repository')}</h2>
  <table>
    <thead><tr><th>{_t(lang, 'name')}</th><th>{_t(lang, 'type')}</th><th>{_t(lang, 'version')}</th><th>{_t(lang, 'category')}</th><th>{_t(lang, 'enabled')}</th><th>{_t(lang, 'installed')}</th><th></th></tr></thead>
    <tbody>{''.join(rows_html) or f'<tr><td colspan="7">{no_plugins_in_repo}</td></tr>'}</tbody>
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


def _render_login(lang: str = "en") -> str:
    if lang not in _LANG_CODES:
        lang = "en"
    auth_required = _t(lang, "auth_required")
    return f"""<!doctype html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <title>cs2-link-manager - {auth_required}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
    input[type=password] {{ padding: 0.4rem; }}
    button {{ cursor: pointer; padding: 0.4rem 1rem; }}
  </style>
</head>
<body>
  <h1>cs2-link-manager {_lang_links(lang)}</h1>
  <form method="get" action="/">
    <label>{_t(lang, 'token')}: <input type="password" name="token"></label>
    <button type="submit">{_t(lang, 'unlock')}</button>
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

    def _get_lang(self) -> str:
        """Resolve UI language: query ``lang`` -> cookie -> Accept-Language -> English."""
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        lang = (qs.get("lang") or [""])[0]
        if lang in _LANG_CODES:
            return lang
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            key, _, value = part.strip().partition("=")
            if key == "lang" and value in _LANG_CODES:
                return value
        accept = self.headers.get("Accept-Language", "")
        if accept.lower().startswith("zh"):
            return "zh"
        return "en"

    def _send_html(self, page: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        # Persist an explicitly requested language (via ?lang=) in a cookie.
        lang_cookie = getattr(self, "_set_lang_cookie", None)
        if lang_cookie:
            self.send_header("Set-Cookie", f"lang={lang_cookie}; Path=/")
            self._set_lang_cookie = None
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
        qs = urllib.parse.parse_qs(parsed.query)
        lang_param = (qs.get("lang") or [""])[0]
        if lang_param in _LANG_CODES:
            self._set_lang_cookie = lang_param
        lang = self._get_lang()
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
                self._send_html(_render_login(lang=lang), status=401)
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
            self.send_error(404, _t(lang, "not_found"))
            return
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
                        lang=lang,
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
                lang=lang,
            )
        )

    def do_POST(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        lang = self._get_lang()
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
                        lang=lang,
                    ),
                    status=400,
                )
                return
            self._redirect(self._root_with_token())
            return
        self.send_error(404, _t(lang, "not_found"))

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