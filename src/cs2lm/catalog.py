"""Unified plugin catalog: browse index sources + registry, install on demand.

``cs2lm search`` shows every plugin available from the configured
``index.json`` sources plus the local registry, annotated with the local
install status and a 1-based number.  ``cs2lm install <name|#N>`` uses
this catalog to install missing plugins directly from a source, pulling in
``requires`` dependencies automatically. The same catalog helpers back the
web API.
"""
from __future__ import annotations

import json
import tempfile
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


def _status(local: str | None, version: str | None, linked: bool) -> str:
    if not local:
        return "未安装"
    if linked:
        base = f"已装({local})"
    else:
        base = f"仓库({local},未链接)"
    if version and version_gt(version, local):
        return f"{base}→{version}"
    return base


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
    from cs2lm.installer import PluginManager
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
    manager = PluginManager(repo)
    for name in list_plugins(repo):
        try:
            local_versions[name] = str(
                load_manifest(repo, name).get("version") or ""
            )
        except Exception:  # noqa: BLE001 - skip unreadable manifests
            continue

    linked_plugins: set[str] = set()
    for name in local_versions:
        if manager.plugin_has_links(name):
            linked_plugins.add(name)

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
                "status": _status(local, version, plugin_id in linked_plugins),
                "installed_version": local,
                "linked": plugin_id in linked_plugins,
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
                "status": _status(local, None, name in linked_plugins),
                "installed_version": local,
                "linked": name in linked_plugins,
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
    force: bool = False,
    logger=None,
) -> dict:
    """Install a plugin from the merged index, dependencies first.

    Uses :func:`cs2lm.updater.expand_requires` to order missing ``requires``
    plugins before their dependents, then downloads/verifies/installs each one.
    ``force`` is forwarded to the plugin manager so ``install --force`` can
    bypass the framework-presence guard even on the source-install path.
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
            force=force,
        )
        if result["status"] in ("installed", "would-install"):
            installed.append(plugin)
        elif result["status"] == "error":
            errors.append(plugin)
    return {"name": name, "installed": installed, "errors": errors}


def install_plugin(
    repo: str | Path,
    name: str,
    *,
    dry_run: bool = False,
    backup: bool = False,
    force: bool = False,
    yes: bool = False,
    timeout: int | None = None,
    from_registry: bool = False,
    logger=None,
) -> dict:
    """Install a plugin by name or catalog reference (``#N``).

    Resolution order:
    1. ``#N`` -> the ``state/search_result.json`` snapshot;
    2. already in the repository -> local manifest install;
    3. missing -> merged index sources (``requires`` dependencies included);
    4. missing -> local registry (forced by ``from_registry``);
    5. none -> :class:`ValueError`.

    Returns ``{"name": ..., "messages": [...], "status": "ok"|"error"}``.
    """
    from cs2lm.config import load_config
    from cs2lm.installer import PluginManager
    from cs2lm.manifest import add_plugin, list_plugins, split_css_plugins
    from cs2lm.registry import load_registry
    from cs2lm.sources import fetch_and_merge, get_sources
    from cs2lm.url_add import (
        DownloadError,
        download_and_extract,
        resolve_addons_subdir,
    )

    name = str(name)
    registry_entry: dict | None = None

    if name.startswith("#"):
        try:
            ref = int(name[1:])
        except ValueError:
            raise ValueError(f"Invalid catalog reference: {name}")
        row = next(
            (r for r in load_search_results(repo) if r.get("index") == ref),
            None,
        )
        if not row:
            raise ValueError(f"No catalog result #{ref}. Run 'cs2lm search' first.")
        name = row["name"]
        if row.get("source_kind") == "registry":
            registry_entry = row.get("entry")

    messages: list[str] = []

    if not from_registry and name not in list_plugins(repo):
        cfg = load_config(repo)
        sources = get_sources(cfg)
        fetch_timeout = timeout or cfg.get("update", {}).get("timeout", 30)
        api_range = cfg.get("update", {}).get("api_version_range")
        if sources:
            merged, _results = fetch_and_merge(
                repo,
                sources,
                timeout=fetch_timeout,
                api_version_range=api_range,
            )
            if name in merged:
                result = install_from_index_with_deps(
                    repo,
                    name,
                    merged,
                    dry_run=dry_run,
                    force=force,
                    logger=logger,
                )
                for plugin in result["installed"]:
                    verb = "would install" if dry_run else "installed"
                    messages.append(
                        f"{plugin}: {verb} {merged[plugin].get('version')}."
                    )
                if result["errors"]:
                    messages.append(f"Install failed: {', '.join(result['errors'])}")
                    return {"name": name, "messages": messages, "status": "error"}
                return {"name": name, "messages": messages, "status": "ok"}

    if from_registry or (registry_entry is None and name not in list_plugins(repo)):
        if registry_entry is None:
            registry_entry = load_registry(repo).get(name)
        if not registry_entry:
            raise ValueError(
                f"Plugin '{name}' is not in the repository and was not found "
                "in any configured source or the local registry. Run "
                "'cs2lm search' to see what is available."
            )
        if name not in list_plugins(repo):
            with tempfile.TemporaryDirectory(prefix="cs2lm-reg-") as tmp:
                tmp_path = Path(tmp)
                try:
                    source = download_and_extract(
                        registry_entry["url"],
                        tmp_path,
                        expected_sha256=registry_entry.get("sha256"),
                    )
                except DownloadError as exc:
                    raise ValueError(str(exc)) from exc
                if registry_entry.get("addons_subdir"):
                    source = resolve_addons_subdir(
                        tmp_path, registry_entry["addons_subdir"]
                    )
                plugin_names = registry_entry.get("plugins") or []
                if len(plugin_names) > 1:
                    added = 0
                    for pname, split_src in split_css_plugins(
                        source, plugin_names, tmp_path
                    ):
                        add_plugin(
                            repo,
                            pname,
                            split_src,
                            type_hint=registry_entry.get("type"),
                            meta=registry_entry,
                        )
                        added += 1
                    messages.append(
                        f"Added {added} plugins from registry package '{name}'."
                    )
                else:
                    add_plugin(
                        repo,
                        name,
                        source,
                        type_hint=registry_entry.get("type"),
                        meta=registry_entry,
                    )
                    messages.append(f"Added '{name}' from registry.")

    manager = PluginManager(
        repo,
        dry_run=dry_run,
        backup=backup,
        force=force,
        yes=yes,
        logger=logger,
    )
    manager.install(name)
    if not dry_run:
        messages.append(f"Installed {name}.")
    return {"name": name, "messages": messages, "status": "ok"}