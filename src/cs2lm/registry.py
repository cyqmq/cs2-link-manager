"""Local plugin registry: a small JSON index of plugin sources.

A registry lives at ``<repo>/registry.json`` and maps a plugin name to a
source URL (plus optional metadata). This gives users a lightweight
"one-command install" workflow without depending on a central service:

* ``cs2lm registry add MatchZy https://example.com/matchzy.zip``
* ``cs2lm search matchzy``
* ``cs2lm install MatchZy --from-registry``

The registry is deliberately plain JSON so community repositories (e.g. the
awesome-cs2 manifest lists) can be exported/imported into it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

REGISTRY_FILENAME = "registry.json"


def registry_path(repo: str | Path) -> Path:
    return Path(repo) / REGISTRY_FILENAME


def load_registry(repo: str | Path) -> dict:
    p = registry_path(repo)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def save_registry(repo: str | Path, data: dict) -> None:
    p = registry_path(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _warn_if_unreachable(url: str) -> None:
    """Best-effort HEAD probe; print a warning when the URL is unreachable."""
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if 200 <= resp.status < 400:
                return
        print(
            f"Warning: {url} returned HTTP {resp.status}.",
            file=sys.stderr,
        )
    except Exception as exc:  # noqa: BLE001 - best-effort probe
        print(
            f"Warning: {url} appears unreachable ({exc}). The entry was "
            "saved anyway; remove it with 'cs2lm registry remove'.",
            file=sys.stderr,
        )


def registry_add(
    repo: str | Path,
    name: str,
    url: str,
    description: str = "",
    type_hint: str | None = None,
    addons_subdir: str | None = None,
    sha256: str | None = None,
    requires: list[str] | None = None,
    plugins: list[str] | None = None,
) -> dict:
    """Add or update a registry entry. Returns the stored entry."""
    if not name.strip():
        raise ValueError("Registry entry name cannot be empty")
    if not url:
        raise ValueError("Registry entry URL cannot be empty")
    parsed_url = urlparse(url)
    if parsed_url.scheme not in ("http", "https", "file"):
        raise ValueError(
            f"Invalid registry URL: '{url}'. Expected an http(s) or file:// "
            "URL such as https://example.com/plugin.zip."
        )
    if parsed_url.scheme in ("http", "https") and not parsed_url.netloc:
        raise ValueError(f"Invalid registry URL: '{url}' (missing host).")
    _warn_if_unreachable(url)
    entry = {
        "url": url,
        "description": description,
        "type": type_hint,
        "addons_subdir": addons_subdir,
        "sha256": sha256,
        "requires": [r.strip() for r in requires if r and r.strip()] if requires else [],
        "plugins": [p.strip() for p in plugins if p and p.strip()] if plugins else [],
    }
    data = load_registry(repo)
    data[name.strip()] = entry
    save_registry(repo, data)
    return entry


def registry_remove(repo: str | Path, name: str) -> None:
    data = load_registry(repo)
    if name not in data:
        raise KeyError(f"Registry entry not found: {name}")
    del data[name]
    save_registry(repo, data)


def registry_search(repo: str | Path, query: str = "") -> list[tuple[str, dict]]:
    """Return ``(name, entry)`` pairs matching ``query`` (name/desc/url)."""
    data = load_registry(repo)
    q = query.strip().lower()
    results: list[tuple[str, dict]] = []
    for name, entry in sorted(data.items()):
        haystack = " ".join(
            [
                name,
                str(entry.get("description", "")),
                str(entry.get("url", "")),
            ]
        ).lower()
        if not q or q in haystack:
            results.append((name, entry))
    return results