"""Unified plugin catalog: browse index sources + registry, install on demand.

``cs2lm search`` shows every plugin available from the configured
``index.json`` sources plus the local registry, annotated with the local
install status and a 1-based number.  ``cs2lm install <name|#N>`` uses
this catalog to install missing plugins directly from a source, pulling in
``requires`` dependencies automatically.
"""
from __future__ import annotations

import json
from pathlib import Path

from cs2lm.versions import version_gt

SEARCH_RESULTS = "state/search_result.json"


def _matches(query: str, name: str, entry: dict) -> bool:
    q = query.strip().lower()
    if not q:
        return True
    haystack = " ".join(
        [
            name,
            str(entry.get("description") or ""),
            str(entry.get("name") or ""),
        ]
    ).lower()
    return q in haystack


def _status(local: str | None, version: str | None) -> str:
    if not local:
        return "未安装"
    if version and version_gt(version, local):
        return f"已装({local})→{version}"
    return f"已装({local})"


def _source_label(source: dict) -> str:
    """Short display label for a source URL."""
    if source.get("name"):
        return source["name"]
    from urllib.parse import urlparse

    url = source.get("url", "")
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return parsed.netloc
    if parsed.scheme == "file":
        return Path(parsed.path).stem or "file"
    return url or "index"


def search_catalog(
    repo: str | Path,
    query: str = "",
    source_url: str | None = None,
    timeout: int = 30,
    api_version_range: tuple[int, int] | None = None,
) -> tuple[list[dict], list[str]]:
    """Build the numbered catalog of available plugins.

    Merges every configured ``index.json`` source (or only ``source_url`` when
    given, fetching it as a one-off source if it is not configured) plus the
    local registry.  Each result row is 1-indexed and carries enough source
    metadata for ``install #N``.

    Returns ``(rows, warnings)``.
    """
    from cs2lm.config import load_config
    from cs2lm.manifest import list_plugins, load_manifest
    from cs2lm.registry import registry_search
    from cs2lm.sources import fetch_and_merge, get_sources

    cfg = load_config(repo)
    sources = get_sources(cfg)
    if source_url:
        configured = {s["url"] for s in sources}
        if source_url in configured:
            sources = [s for s in sources if s["url"] == source_url]
        else:
            sources = [{"url": source_url}]

    merged, fetch_results = fetch_and_merge(
        repo, sources, timeout=timeout, api_version_range=api_version_range
    )

    warnings: list[str] = []
    for result in fetch_results:
        if result.get("error"):
            warnings.append(f"Source {result['url']}: {result['error']}")
        warnings.extend(result.get("warnings") or [])

    local_versions: dict[str, str] = {}
    for name in list_plugins(repo):
        try:
            local_versions[name] = str(
                load_manifest(repo, name).get("version") or ""
            )
        except Exception:  # noqa: BLE001 - skip unreadable manifests
            continue

    labels: dict[str, str] = {}
    for result in fetch_results:
        if result.get("error"):
            continue
        index = result.get("index") or {}
        index_name = index.get("name")
        if index_name:
            labels[result["url"]] = index_name
    for source in sources:
        if source.get("name"):
            labels[source["url"]] = source["name"]
    rows: list[dict] = []

    for plugin_id in sorted(merged):
        entry = merged[plugin_id]
        if query and not _matches(query, plugin_id, entry):
            continue
        version = str(entry.get("version") or "")
        local = local_versions.get(plugin_id)
        source_url = entry.get("source") or ""
        rows.append(
            {
                "name": plugin_id,
                "version": version,
                "status": _status(local, version),
                "installed_version": local,
                "source": labels.get(source_url, _source_label({"url": source_url})),
                "source_url": source_url,
                "source_kind": "index",
                "description": entry.get("description") or "",
                "download_url": entry.get("download_url"),
                "sha256": entry.get("sha256"),
                "requires": entry.get("requires"),
                "plugin_type": entry.get("plugin_type") or entry.get("type"),
                "api_version": entry.get("api_version"),
                "entry": entry,
            }
        )

    registry_names = {r["name"] for r in rows}
    for name, entry in registry_search(repo, query):
        if name in registry_names:
            continue
        local = local_versions.get(name)
        rows.append(
            {
                "name": name,
                "version": None,
                "status": _status(local, None),
                "installed_version": local,
                "source": "registry",
                "source_url": None,
                "source_kind": "registry",
                "description": entry.get("description") or "",
                "download_url": entry.get("url"),
                "sha256": entry.get("sha256"),
                "requires": entry.get("requires"),
                "plugin_type": entry.get("type"),
                "api_version": None,
                "entry": entry,
            }
        )

    for i, row in enumerate(rows, 1):
        row["index"] = i
    return rows, warnings


def print_catalog(rows: list[dict]) -> None:
    """Print the numbered catalog table."""
    if not rows:
        print("No plugins found.")
        return
    idx_w = max(len(str(len(rows))), 1)
    name_w = max(len("名称"), *(len(str(r["name"])) for r in rows))
    ver_w = max(len("版本"), *(len(str(r["version"] or "")) for r in rows))
    status_w = max(len("状态"), *(len(str(r["status"])) for r in rows))
    source_w = max(len("来源"), *(len(str(r["source"])) for r in rows))
    header = (
        f"#  [{'#':>{idx_w}}]  {'名称':<{name_w}}  {'版本':<{ver_w}}  "
        f"{'状态':<{status_w}}  {'来源':<{source_w}}  描述"
    )
    print(header)
    for r in rows:
        print(
            f"#  [{r['index']:>{idx_w}}]  {str(r['name']):<{name_w}}  "
            f"{str(r['version'] or ''):<{ver_w}}  {str(r['status']):<{status_w}}  "
            f"{str(r['source']):<{source_w}}  {r['description']}"
        )


def save_search_results(repo: str | Path, rows: list[dict]) -> None:
    """Persist the catalog snapshot for ``install #N`` to reference."""
    path = Path(repo) / SEARCH_RESULTS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"results": rows}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_search_results(repo: str | Path) -> list[dict]:
    """Load the catalog snapshot written by ``search``."""
    path = Path(repo) / SEARCH_RESULTS
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    results = data.get("results") if isinstance(data, dict) else None
    return results if isinstance(results, list) else []


def install_from_index_with_deps(
    repo: str | Path,
    name: str,
    merged: dict,
    dry_run: bool = False,
    logger=None,
) -> dict:
    """Install a plugin from the merged index, dependencies first.

    Uses :func:`cs2lm.updater.expand_requires` to order missing ``requires``
    plugins before their dependents, then downloads/verifies/installs each one.
    """
    from cs2lm.updater import expand_requires, install_plugin_from_index, scan_local

    local = scan_local(repo)
    to_install = expand_requires(merged, [name], local)
    installed: list[str] = []
    errors: list[str] = []
    for plugin in to_install:
        if plugin not in merged:
            errors.append(plugin)
            continue
        result = install_plugin_from_index(
            repo,
            plugin,
            merged[plugin],
            dry_run=dry_run,
            logger=logger,
        )
        if result["status"] in ("installed", "would-install"):
            installed.append(plugin)
        elif result["status"] == "error":
            errors.append(plugin)
    return {"name": name, "installed": installed, "errors": errors}