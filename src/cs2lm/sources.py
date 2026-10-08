"""Index-based plugin sources: fetch, cache, merge.

A **source** is a URL that serves an ``index.json`` (see ``docs/INDEX.md``
for the schema).  The Python project only reads these indexes — it never
parses GitHub tags or Release pages.

Responsibilities
----------------
* ``get_sources`` / ``add_source`` / ``remove_source`` / ``list_sources``
  manage the ordered source list stored in ``config.json``.
* ``fetch_index`` downloads one source's ``index.json`` with
  ETag / If-Modified-Since caching, validates the ``schema``, and falls
  back to the cached copy when the network is unavailable.
* ``merge_sources`` merges several indexes into one "latest available
  plugin table": each plugin independently takes the highest version;
  on equal versions the earlier source wins; a failed source is skipped.
"""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from cs2lm.config import load_config, save_config
from cs2lm.versions import version_gt

INDEX_SCHEMA = 1
CACHE_DIR = "state/source_cache"
MERGED_CACHE = "state/merged_index.json"


class SourceError(Exception):
    """Raised for user-facing source fetch/validation errors."""


# ---------------------------------------------------------------------------
# Source list configuration (stored in config.json)
# ---------------------------------------------------------------------------


def get_sources(cfg: dict) -> list[dict]:
    """Return the configured sources as ``[{"url", "headers", "name"?}, ...]``."""
    raw = cfg.get("sources") or []
    sources: list[dict] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            sources.append({"url": item.strip(), "headers": {}})
        elif isinstance(item, dict) and item.get("url"):
            entry = {"url": item["url"], "headers": dict(item.get("headers") or {})}
            if item.get("name"):
                entry["name"] = item["name"]
            sources.append(entry)
    return sources


def _save_sources(repo: str | Path, sources: list[dict]) -> None:
    cfg = load_config(repo)
    cfg["sources"] = [dict(s) for s in sources]
    save_config(repo, cfg)


def add_source(
    repo: str | Path,
    url: str,
    headers: dict | None = None,
    name: str | None = None,
) -> list[dict]:
    """Add a source URL to the ordered list. Returns the updated list."""
    url = url.strip()
    if not url:
        raise ValueError("Source URL cannot be empty")
    sources = get_sources(load_config(repo))
    if any(s["url"] == url for s in sources):
        raise ValueError(f"Source already configured: {url}")
    entry: dict = {"url": url, "headers": dict(headers or {})}
    if name:
        entry["name"] = name
    sources.append(entry)
    _save_sources(repo, sources)
    return sources


def remove_source(repo: str | Path, url: str) -> list[dict]:
    """Remove a source URL from the list. Returns the updated list."""
    sources = get_sources(load_config(repo))
    remaining = [s for s in sources if s["url"] != url.strip()]
    if len(remaining) == len(sources):
        raise ValueError(f"Source not configured: {url}")
    _save_sources(repo, remaining)
    return remaining


def clear_sources(repo: str | Path) -> None:
    _save_sources(repo, [])


def list_sources(repo: str | Path) -> list[dict]:
    return get_sources(load_config(repo))


# ---------------------------------------------------------------------------
# Fetching a single source
# ---------------------------------------------------------------------------


def _source_cache_path(repo: str | Path, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return Path(repo) / CACHE_DIR / f"{digest}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_index_schema(index: dict) -> None:
    """Reject indexes this project cannot parse (schema mismatch)."""
    if not isinstance(index, dict):
        raise SourceError("index.json is not a JSON object")
    schema = index.get("schema")
    if not isinstance(schema, int):
        raise SourceError(f"index.json has no integer 'schema' (got {schema!r})")
    if schema != INDEX_SCHEMA:
        raise SourceError(
            f"unsupported index schema {schema} (this project supports {INDEX_SCHEMA})"
        )
    plugins = index.get("plugins")
    if not isinstance(plugins, dict):
        raise SourceError("index.json 'plugins' must be an object")


def fetch_index(repo: str | Path, source: dict, timeout: int = 30) -> dict:
    """Fetch and validate one source's ``index.json``.

    Uses ETag / If-Modified-Since caching.  When the network fails but a
    previously fetched copy exists in ``state/source_cache``, the cached
    index is returned (offline fallback).  Raises :class:`SourceError` on
    HTTP/network errors with no cache and on schema violations.
    """
    url = source["url"]
    headers = dict(source.get("headers") or {})
    cache_file = _source_cache_path(repo, url)
    cached: dict | None = None
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            cached = None

    request = urllib.request.Request(url, headers=headers)
    if cached:
        if cached.get("etag"):
            request.add_header("If-None-Match", cached["etag"])
        if cached.get("last_modified"):
            request.add_header("If-Modified-Since", cached["last_modified"])

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status == 304 and cached:
                return cached["index"]
            data = response.read()
            try:
                index = json.loads(data.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SourceError(f"invalid JSON in {url}: {exc}") from exc
            _validate_index_schema(index)
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(
                json.dumps(
                    {
                        "etag": response.headers.get("ETag"),
                        "last_modified": response.headers.get("Last-Modified"),
                        "index": index,
                        "fetched_at": _now(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            return index
    except urllib.error.HTTPError as exc:
        if exc.code == 304 and cached:
            return cached["index"]
        raise SourceError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
    except Exception as exc:  # noqa: BLE001 - any network error
        if cached:
            return cached["index"]
        raise SourceError(f"failed to fetch {url}: {exc}") from exc


# ---------------------------------------------------------------------------
# Merging multiple sources
# ---------------------------------------------------------------------------


def merge_sources(results: list[dict]) -> dict:
    """Merge per-source index results into one plugin table.

    ``results`` is a list of ``{"url", "index"?}`` dicts in source priority
    order (earlier = higher priority).  For every plugin id the entry with
    the highest ``version`` wins; on equal versions the earlier source is
    kept.  Returns ``{plugin_id: entry}`` where ``entry`` is the selected
    index entry plus ``source`` (URL) and ``source_index``.
    """
    merged: dict[str, dict] = {}
    for i, result in enumerate(results):
        index = result.get("index")
        if not isinstance(index, dict):
            continue
        plugins = index.get("plugins")
        if not isinstance(plugins, dict):
            continue
        for plugin_id, info in plugins.items():
            if not isinstance(info, dict):
                continue
            version = str(info.get("version") or "").strip()
            if not version:
                continue
            current = merged.get(plugin_id)
            if current is None or version_gt(version, str(current.get("version"))):
                entry = dict(info)
                entry["id"] = plugin_id
                entry["version"] = version
                entry["source"] = result.get("url")
                entry["source_index"] = i
                merged[plugin_id] = entry
            # equal version -> keep the earlier source (do nothing)
    return merged


def save_cached_merged(repo: str | Path, merged: dict) -> None:
    path = Path(repo) / MERGED_CACHE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_cached_merged(repo: str | Path) -> dict:
    path = Path(repo) / MERGED_CACHE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def fetch_and_merge(
    repo: str | Path,
    sources: list[dict],
    timeout: int = 30,
) -> tuple[dict, list[dict]]:
    """Fetch every source, merge the indexes, and cache the merged table.

    Returns ``(merged_plugins, results)`` where ``results`` records each
    source's status (``url``, ``index``, ``error``).  If every source fails
    but a cached merged table exists, that table is returned so the user can
    still see what the last successful merge looked like.
    """
    results: list[dict] = []
    for source in sources:
        try:
            index = fetch_index(repo, source, timeout=timeout)
            results.append({"url": source["url"], "index": index, "error": None})
        except SourceError as exc:
            results.append(
                {"url": source["url"], "index": None, "error": str(exc)}
            )

    merged = merge_sources(results)
    if not merged and not any(r.get("index") for r in results):
        cached = load_cached_merged(repo)
        if cached:
            return cached, results
    save_cached_merged(repo, merged)
    return merged, results