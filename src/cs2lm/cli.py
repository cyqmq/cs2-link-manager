"""Command-line interface for cs2-link-manager."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from cs2lm import __version__
from cs2lm import doctor as doctor_mod
from cs2lm import importer as importer_mod
from cs2lm import linking, profiles
from cs2lm.config import default_config, save_config
from cs2lm.doctor import run_doctor
from cs2lm.installer import InstallError, PluginManager
from cs2lm.logutil import Logger
from cs2lm.paths import find_csgo_rel

DEFAULT_REPO = os.environ.get("CS2LM_REPO", "plugins-repo")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cs2lm",
        description=(
            "Manage CS2 CounterStrikeSharp/Metamod plugins from a central "
            "repository, linking them into the server directory."
        ),
    )
    parser.add_argument("--version", action="version", version=f"cs2lm {__version__}")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="Repository path")
    parser.add_argument("--dry-run", action="store_true", help="only print actions")
    parser.add_argument("--log", default=None, help="Write logs to this file")
    parser.add_argument(
        "--log-format",
        choices=["text", "json"],
        default="text",
        help="Log format (text or json)",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose console output")

    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize a repository")
    p_init.add_argument("--repo", dest="repo", default=argparse.SUPPRESS, help="Repository path (overrides global)")
    p_init.add_argument("--server", required=True, help="CS2 server directory")

    p_add = sub.add_parser("add", help="Add a plugin package to the repository")
    p_add.add_argument("name", nargs="?", help="Plugin name (required unless --pkg provides one)")
    p_add.add_argument(
        "path",
        nargs="?",
        help="Path to the plugin package or folder (omit when using --url/--pkg)",
    )
    p_add.add_argument("--url", default=None, help="Download a zip package from this URL")
    p_add.add_argument("--pkg", default=None, help="Add a plugin from a local .cs2pkg file")
    from cs2lm.frameworks import framework_ids

    framework_choices = framework_ids()
    p_add.add_argument("--type", choices=framework_choices, default=None)
    p_add.add_argument("--version", default=None)
    p_add.add_argument(
        "--addons-subdir",
        default=None,
        help="With --url: subdirectory inside the extracted zip whose addons/ "
        "tree holds the plugin (e.g. 'public' for public/addons)",
    )
    p_add.add_argument(
        "--sha256",
        default=None,
        help="With --url: expected SHA-256 of the downloaded zip (integrity check)",
    )
    p_add.add_argument(
        "--plugins",
        default=None,
        help="Split a multi-plugin package: comma-separated plugin directory "
        "names inside the package to add as separate repository entries",
    )

    p_pack = sub.add_parser("pack", help="Package a repository plugin as a .cs2pkg file")
    p_pack.add_argument("name", help="Plugin name")
    p_pack.add_argument("--out", default=".", help="Output directory or file path (default: current directory)")

    p_install = sub.add_parser("install", help="Install a plugin (from the repo, a source, or a catalog #N)")
    p_install.add_argument("name", help="Plugin name, or #N catalog reference from 'cs2lm search'")
    p_install.add_argument("--from-registry", action="store_true", help="Add the plugin from the local registry first, then install")
    p_install.add_argument("--backup", action="store_true", help="Back up conflicting targets")
    p_install.add_argument("--force", action="store_true", help="Force install with confirmation")
    p_install.add_argument("--yes", action="store_true", help="Skip confirmation when using --backup")
    p_install.add_argument("--timeout", type=int, default=None, help="Per-source HTTP timeout in seconds (default: config update.timeout)")

    p_uninstall = sub.add_parser("uninstall", help="Uninstall a plugin (remove links)")
    p_uninstall.add_argument("name")

    p_enable = sub.add_parser("enable", help="Enable a plugin (create links)")
    p_enable.add_argument("name")
    p_enable.add_argument("--force", action="store_true", help="Bypass the framework-presence guard (like install --force)")

    p_disable = sub.add_parser("disable", help="Disable a plugin (remove links)")
    p_disable.add_argument("name")
    p_disable.add_argument("--force", action="store_true", help="Bypass safety checks when removing links")

    p_list = sub.add_parser("list", help="List plugins in the repository")

    p_doctor = sub.add_parser("doctor", help="Run diagnostics")
    p_doctor.add_argument("--verbose", action="store_true", help="Verbose console output")

    p_import = sub.add_parser("import", help="Import an installed plugin back into the repo")
    p_import.add_argument("name")
    p_import.add_argument("path", help="Path inside the server directory")
    p_import.add_argument("--type", choices=framework_choices, default=None)
    p_import.add_argument("--version", default=None)

    p_adopt = sub.add_parser(
        "adopt",
        help="Adopt existing CSS plugins on the server into the repository",
    )
    p_adopt.add_argument("--plugin", default=None, help="Only adopt this plugin")

    p_profile = sub.add_parser("profile", help="Manage profiles")
    p_profile_sub = p_profile.add_subparsers(dest="profile_command", required=True)
    p_profile_create = p_profile_sub.add_parser("create", help="Create a profile")
    p_profile_create.add_argument("name", nargs="?", help="Profile name")
    p_profile_create.add_argument("plugins", nargs="*", help="Plugin names in the profile")
    p_profile_use = p_profile_sub.add_parser("use", help="Switch to a profile")
    p_profile_use.add_argument("name")
    p_profile_list = p_profile_sub.add_parser("list", help="List profiles")
    p_profile_delete = p_profile_sub.add_parser("delete", help="Delete a profile")
    p_profile_delete.add_argument("name")

    p_remove = sub.add_parser("remove", help="Remove a plugin from the repository (moves it to trash)")
    p_remove.add_argument("name")

    p_trash = sub.add_parser("trash", help="Manage trashed plugins")
    p_trash_sub = p_trash.add_subparsers(dest="trash_command", required=True)
    p_trash_list = p_trash_sub.add_parser("list", help="List trashed plugins")
    p_trash_restore = p_trash_sub.add_parser("restore", help="Restore a plugin from trash")
    p_trash_restore.add_argument("name")

    p_web = sub.add_parser("web", help="Start the web management UI (browse/install/update plugins, view frameworks)")
    p_web.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    p_web.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    p_web.add_argument(
        "--auth-token",
        default=None,
        help="Require this token to view and toggle plugins (recommended when binding a non-loopback host)",
    )
    p_web.add_argument(
        "--daemon",
        action="store_true",
        help="Run the web UI as a detached background process and exit",
    )
    p_web.add_argument(
        "--pidfile",
        default=None,
        help="Write the daemon PID to this file (used with --daemon)",
    )
    p_web.add_argument(
        "--daemon-log",
        default=None,
        help="Append daemon stdout/stderr to this log file (used with --daemon)",
    )

    p_registry = sub.add_parser("registry", help="Manage the local plugin registry")
    p_registry_sub = p_registry.add_subparsers(dest="registry_command", required=True)
    p_registry_add = p_registry_sub.add_parser("add", help="Add or update a registry entry")
    p_registry_add.add_argument("name")
    p_registry_add.add_argument("url")
    p_registry_add.add_argument("--description", default="")
    p_registry_add.add_argument("--type", choices=framework_choices, default=None)
    p_registry_add.add_argument("--addons-subdir", default=None)
    p_registry_add.add_argument("--sha256", default=None, help="Expected SHA-256 of the downloaded zip")
    p_registry_add.add_argument("--requires", default=None, help="Comma-separated plugin names this plugin requires")
    p_registry_add.add_argument("--plugins", default=None, help="Comma-separated plugin directory names this package contains (multi-plugin split)")
    p_registry_remove = p_registry_sub.add_parser("remove", help="Remove a registry entry")
    p_registry_remove.add_argument("name")
    p_registry_list = p_registry_sub.add_parser("list", help="List registry entries")

    p_search = sub.add_parser("search", help="Browse merged index sources and the local registry")
    p_search.add_argument("query", nargs="?", default="", help="Search text (name/description)")
    p_search.add_argument("--source", default=None, help="Only show results from this source URL")
    p_search.add_argument("--timeout", type=int, default=None, help="Per-source HTTP timeout in seconds (default: config update.timeout)")

    p_update = sub.add_parser("update", help="Update locally installed plugins from index.json sources")
    p_update.add_argument("names", nargs="*", help="Plugin ids to update (default: every locally installed plugin in the merged index)")
    p_update.add_argument("--yes", action="store_true", help="Apply updates without confirmation")
    p_update.add_argument("--force", action="store_true", help="Bypass the framework-presence guard when relinking updated plugins")
    p_update.add_argument("--remove-orphans", action="store_true", help="Uninstall and trash plugins absent from every source")
    p_update.add_argument("--timeout", type=int, default=None, help="Per-source HTTP timeout in seconds (default: config update.timeout)")
    p_update.add_argument("--self", action="store_true", help="Update the cs2lm tool itself and exit")

    p_source = sub.add_parser("source", help="Manage index.json plugin sources")
    p_source_sub = p_source.add_subparsers(dest="source_command", required=True)
    p_source_add = p_source_sub.add_parser("add", help="Add an index.json source URL")
    p_source_add.add_argument("url", help="URL of the index.json (http/https/file)")
    p_source_add.add_argument("--name", default=None, help="Source name shown in logs, e.g. 'official-repo'")
    p_source_add.add_argument("--header", action="append", default=[], help='HTTP header "Name: Value" (repeatable, for private sources)')
    p_source_list = p_source_sub.add_parser("list", help="List configured sources")
    p_source_remove = p_source_sub.add_parser("remove", help="Remove a source URL")
    p_source_remove.add_argument("url")
    p_source_clear = p_source_sub.add_parser("clear", help="Remove all sources")

    return parser


def _make_logger(args: argparse.Namespace) -> Logger:
    return Logger(path=args.log, fmt=args.log_format, verbose=args.verbose)


def cmd_init(args: argparse.Namespace, logger: Logger) -> int:
    repo = Path(args.repo).expanduser().resolve()
    server = Path(args.server).expanduser().resolve()
    if (repo / "config.json").exists():
        print(f"Repository already initialized: {repo}")
        logger.info("init", "repository already initialized", repo=str(repo))
        return 0
    (repo / "plugins").mkdir(parents=True, exist_ok=True)
    (repo / "profiles").mkdir(parents=True, exist_ok=True)
    (repo / "state").mkdir(parents=True, exist_ok=True)
    csgo_rel = find_csgo_rel(server)
    save_config(repo, default_config(repo, server, csgo_rel))
    logger.info(
        "init",
        "repository initialized",
        repo=str(repo),
        server=str(server),
        csgo_rel=csgo_rel,
    )
    return 0


def cmd_add(args: argparse.Namespace, logger: Logger) -> int:
    from cs2lm.cs2pkg import extract_pkg
    from cs2lm.manifest import add_plugin, split_css_plugins
    from cs2lm.url_add import (
        DownloadError,
        download_and_extract,
        resolve_addons_subdir,
    )

    sources = [bool(args.path), bool(args.url), bool(args.pkg)]
    if sum(sources) > 1:
        raise ValueError("Provide only one of path, --url, or --pkg")
    if not any(sources):
        raise ValueError("Provide a local path, --url, or --pkg for the plugin package")

    def looks_like_plugin(src: str | Path) -> bool:
        """Best-effort check that a package actually contains plugin files."""
        src = Path(src)
        if not src.is_dir():
            return src.suffix.lower() in (".dll", ".so", ".vdf")
        return (
            (src / "addons").is_dir()
            or bool(list(src.glob("*.dll")) or list(src.glob("*.deps.json")))
            or (src / "bin").exists()
        )

    def warn_if_empty(name: str, source: str | Path) -> None:
        if not looks_like_plugin(source):
            logger.warn(
                "add",
                f"WARNING: '{source}' does not look like a plugin package "
                f"(no addons/ tree or binaries found). '{name}' was added "
                "but may not load on the server.",
            )

    def warn_version_default(name: str, manifest: dict, package_root: Path) -> None:
        """Warn when a package carries no version metadata and defaults to 1.0.0."""
        if args.version is not None:
            return
        if manifest.get("version") != "1.0.0":
            return
        has_pkg_meta = bool(
            list(package_root.rglob("manifest.json"))
            or list(package_root.rglob("cs2pkg.json"))
        )
        if not has_pkg_meta:
            logger.warn(
                "add",
                f"WARNING: '{name}' has no manifest.json/cs2pkg.json in the "
                "package, so its version defaulted to 1.0.0. Pass "
                "--version <semver> to set one explicitly.",
            )

    def split_names(value: str | None) -> list[str]:
        if not value:
            return []
        return [v.strip() for v in value.split(",") if v.strip()]

    def add_split(names: list[str], source: str | Path, base: Path, meta: dict | None = None) -> list[dict]:
        """Split a multi-plugin CSS package and add each plugin separately."""
        manifests = []
        for name, src in split_css_plugins(source, names, base):
            manifests.append(
                add_plugin(
                    args.repo,
                    name,
                    src,
                    type_hint=args.type,
                    version=args.version,
                    meta=meta,
                )
            )
        return manifests

    if args.url:
        with tempfile.TemporaryDirectory(prefix="cs2lm-url-") as tmp:
            tmp = Path(tmp)
            try:
                source = download_and_extract(
                    args.url, tmp, expected_sha256=args.sha256
                )
            except DownloadError as exc:
                raise ValueError(str(exc)) from exc
            if args.addons_subdir:
                source = resolve_addons_subdir(tmp, args.addons_subdir)
            names = split_names(args.plugins)
            if names:
                manifests = add_split(names, source, tmp)
                logger.info("add", f"added {len(manifests)} plugins from package")
                return 0
            if not args.name:
                raise ValueError("A plugin name is required when adding from a URL.")
            manifest = add_plugin(
                args.repo,
                args.name,
                source,
                type_hint=args.type,
                version=args.version,
            )
            warn_if_empty(args.name, source)
            warn_version_default(args.name, manifest, tmp)
    elif args.pkg:
        with tempfile.TemporaryDirectory(prefix="cs2lm-pkg-") as tmp:
            tmp = Path(tmp)
            source, meta = extract_pkg(args.pkg, tmp)
            type_hint = args.type or (meta or {}).get("plugin_type")
            version = args.version or (meta or {}).get("version")
            names = split_names(args.plugins) or (meta or {}).get("plugins") or []
            if len(names) > 1:
                manifests = add_split(names, source, tmp, meta)
                logger.info("add", f"added {len(manifests)} plugins from package")
                return 0
            plugin_name = args.name or (names[0] if names else None) or (meta or {}).get("name")
            if not plugin_name:
                raise ValueError(
                    "No plugin name given and cs2pkg.json does not provide one."
                )
            manifest = add_plugin(
                args.repo,
                plugin_name,
                source,
                type_hint=type_hint,
                version=version,
                meta=meta,
            )
    else:
        if args.plugins:
            names = split_names(args.plugins)
            with tempfile.TemporaryDirectory(prefix="cs2lm-split-") as tmp:
                manifests = add_split(names, args.path, Path(tmp))
            logger.info("add", f"added {len(manifests)} plugins from package")
            return 0
        if not args.name:
            raise ValueError("A plugin name is required when adding from a local path.")
        if Path(args.path).is_file() and Path(args.path).suffix.lower() == ".cs2pkg":
            raise ValueError(
                f"'{args.path}' is a .cs2pkg package. Use "
                f"'cs2lm add --pkg {args.path}' to import it (or pass --pkg)."
            )
        manifest = add_plugin(
            args.repo,
            args.name,
            args.path,
            type_hint=args.type,
            version=args.version,
        )
        warn_if_empty(args.name, args.path)
    logger.info(
        "add",
        f"added plugin '{manifest['name']}'",
        type=manifest["plugin_type"],
        files=len(manifest["files"]),
        links=len(manifest["links"]),
    )
    return 0


def cmd_install(args: argparse.Namespace, logger: Logger) -> int:
    from cs2lm.catalog import install_plugin

    result = install_plugin(
        args.repo,
        args.name,
        dry_run=args.dry_run,
        backup=args.backup,
        force=args.force,
        yes=args.yes,
        timeout=args.timeout,
        from_registry=args.from_registry,
        logger=logger,
    )
    for message in result["messages"]:
        print(message)
    return 0 if result["status"] == "ok" else 1


def cmd_uninstall(args: argparse.Namespace, logger: Logger) -> int:
    manager = PluginManager(args.repo, dry_run=args.dry_run, logger=logger)
    manager.uninstall(args.name)
    return 0


def cmd_enable(args: argparse.Namespace, logger: Logger) -> int:
    manager = PluginManager(
        args.repo, dry_run=args.dry_run, force=args.force, logger=logger
    )
    manager.enable(args.name)
    return 0


def cmd_disable(args: argparse.Namespace, logger: Logger) -> int:
    manager = PluginManager(
        args.repo, dry_run=args.dry_run, force=args.force, logger=logger
    )
    manager.disable(args.name)
    return 0


def cmd_list(args: argparse.Namespace, logger: Logger) -> int:
    manager = PluginManager(args.repo, logger=logger)
    rows = manager.list_plugins()
    if not rows:
        print("No plugins in repository.")
        return 0
    name_w = max(len("NAME"), *(len(r["name"]) for r in rows))
    type_w = max(len("TYPE"), *(len(r["type"]) for r in rows))
    ver_w = max(len("VERSION"), *(len(r["version"]) for r in rows))
    header = (
        f"{'NAME':<{name_w}}  {'TYPE':<{type_w}}  {'VERSION':<{ver_w}}  "
        f"{'ENABLED':<8} {'INSTALLED':<10}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['name']:<{name_w}}  {r['type']:<{type_w}}  {r['version']:<{ver_w}}  "
            f"{str(r['enabled']):<8} {str(r['installed']):<10}"
        )
    return 0


def cmd_doctor(args: argparse.Namespace, logger: Logger) -> int:
    issues = run_doctor(args.repo, logger=logger, verbose=args.verbose)
    if not issues:
        print("All checks passed.")
        return 0
    for issue in issues:
        severity = issue["severity"].upper()
        prefix = f"[{severity}] {issue['code']}"
        plugin = issue.get("plugin")
        if plugin:
            prefix += f" ({plugin})"
        print(f"{prefix}: {issue['message']}")
    errors = [i for i in issues if i["severity"] == "error"]
    return 1 if errors else 0


def cmd_import(args: argparse.Namespace, logger: Logger) -> int:
    manifest = importer_mod.import_plugin(
        args.repo,
        args.name,
        args.path,
        type_hint=args.type,
        version=args.version,
        logger=logger,
    )
    print(
        f"Imported '{args.name}' ({len(manifest['files'])} files). "
        "Original server files left untouched."
    )
    return 0


def cmd_pack(args: argparse.Namespace, logger: Logger) -> int:
    from cs2lm.cs2pkg import build_pkg

    out = build_pkg(args.repo, args.name, args.out)
    logger.info("pack", f"packaged plugin '{args.name}'", out=str(out))
    print(f"Packaged '{args.name}' -> {out}")
    return 0


def cmd_adopt(args: argparse.Namespace, logger: Logger) -> int:
    from cs2lm.adopt import adopt_css_plugins
    from cs2lm.manifest import list_plugins

    if args.plugin and args.plugin in list_plugins(args.repo):
        print(f"'{args.plugin}' is already in the repository.")
        return 0
    adopted = adopt_css_plugins(args.repo, only=args.plugin, logger=logger)
    if args.plugin and args.plugin not in adopted:
        raise FileNotFoundError(f"No adoptable plugin found: {args.plugin}")
    if adopted:
        print(f"Adopted {len(adopted)} plugin(s): {', '.join(adopted)}")
        print("The original plugin files are still on the server.")
        print("Take over each plugin with:")
        print("  cs2lm install <name> --backup")
    else:
        print("No new plugins adopted.")
    return 0


def cmd_web(args: argparse.Namespace, logger: Logger) -> int:
    from cs2lm.daemon import start_daemon
    from cs2lm.webui import run_webui

    host = args.host
    token = args.auth_token
    if not 0 <= args.port <= 65535:
        raise ValueError(
            f"Invalid port: {args.port}. Port must be between 0 and 65535 "
            "(use 0 for a random free port)."
        )
    if token == "":
        raise ValueError(
            "--auth-token must not be empty; pass a non-empty token or omit "
            "the option entirely."
        )
    is_loopback = host in ("127.0.0.1", "localhost", "::1")
    if not is_loopback and not token:
        raise ValueError(
            f"binding web UI to {host} requires --auth-token for "
            "authentication; pass a non-empty token (e.g. "
            "--auth-token my-secret)."
        )

    if args.daemon:
        from cs2lm.daemon import DaemonError, start_daemon

        try:
            pid = start_daemon(
                args.repo,
                host=host,
                port=args.port,
                auth_token=token,
                pidfile=args.pidfile,
                logfile=args.daemon_log,
            )
        except DaemonError as exc:
            raise ValueError(str(exc)) from exc
        location = args.pidfile or f"pid {pid}"
        print(f"Started web UI daemon ({location}).")
        return 0

    if not is_loopback:
        print(
            f"WARNING: binding web UI to {host} with --auth-token. Keep the "
            "token secret and prefer SSH port forwarding when possible."
        )
    run_webui(args.repo, host=host, port=args.port, auth_token=token)
    return 0


def cmd_registry(args: argparse.Namespace, logger: Logger) -> int:
    from cs2lm.registry import (
        registry_add,
        registry_remove,
        registry_search,
    )

    command = args.registry_command
    if command == "add":
        registry_add(
            args.repo,
            args.name,
            args.url,
            description=args.description,
            type_hint=args.type,
            addons_subdir=args.addons_subdir,
            sha256=args.sha256,
            requires=args.requires.split(",") if args.requires else [],
            plugins=args.plugins.split(",") if args.plugins else [],
        )
        print(f"Registry: added '{args.name}' -> {args.url}")
        return 0
    if command == "remove":
        try:
            registry_remove(args.repo, args.name)
        except KeyError as exc:
            raise ValueError(str(exc)) from exc
        print(f"Registry: removed '{args.name}'")
        return 0
    if command == "list":
        entries = registry_search(args.repo)
        if not entries:
            print("Registry is empty. Add entries with 'cs2lm registry add <name> <url>'.")
            return 0
        for name, entry in entries:
            desc = f" — {entry.get('description')}" if entry.get("description") else ""
            subdir = f" (addons-subdir: {entry['addons_subdir']})" if entry.get("addons_subdir") else ""
            print(f"{name}: {entry['url']}{desc}{subdir}")
        return 0
    logger.error("registry", f"unknown registry command: {command}")
    return 2


def cmd_search(args: argparse.Namespace, logger: Logger) -> int:
    from cs2lm.catalog import print_catalog, save_search_results, search_catalog
    from cs2lm.config import load_config

    cfg = load_config(args.repo)
    update_cfg = cfg.get("update", {}) or {}
    timeout = args.timeout or update_cfg.get("timeout", 30)
    api_range = update_cfg.get("api_version_range")
    rows, warnings = search_catalog(
        args.repo,
        query=args.query,
        source_url=args.source,
        timeout=timeout,
        api_version_range=api_range,
    )
    for warning in warnings:
        print(f"warning: {warning}")
    print_catalog(rows)
    save_search_results(args.repo, rows)
    logger.info("search", f"catalog: {len(rows)} results", rows=len(rows))
    return 0


def cmd_source(args: argparse.Namespace, logger: Logger) -> int:
    from cs2lm.sources import (
        add_source,
        clear_sources,
        list_sources,
        remove_source,
    )

    if args.source_command == "add":
        headers: dict[str, str] = {}
        for header in args.header:
            if ":" in header:
                key, value = header.split(":", 1)
                headers[key.strip()] = value.strip()
            else:
                raise ValueError(f"Invalid header (expected 'Name: Value'): {header}")
        # Validate the index before saving it as a configured source, so a
        # typo / unreachable / malformed index fails at `source add` time
        # instead of silently poisoning later `search`/`update` runs.
        from cs2lm.sources import SourceError, fetch_index

        try:
            fetch_index(
                args.repo,
                {"url": args.url, "headers": headers},
                timeout=15,
            )
        except SourceError as exc:
            raise ValueError(f"Invalid index.json at {args.url}: {exc}") from exc
        except OSError as exc:
            raise ValueError(f"Cannot fetch {args.url}: {exc}") from exc
        add_source(args.repo, args.url, headers=headers, name=args.name)
        print(f"Source added: {args.url}")
        logger.info("source", "source added", url=args.url)
        return 0
    if args.source_command == "list":
        sources = list_sources(args.repo)
        if not sources:
            print("No sources configured.")
        else:
            for i, source in enumerate(sources, 1):
                label = f"  ({source['name']})" if source.get("name") else ""
                print(f"{i}. {source['url']}{label}")
        return 0
    if args.source_command == "remove":
        remove_source(args.repo, args.url)
        print(f"Source removed: {args.url}")
        return 0
    if args.source_command == "clear":
        clear_sources(args.repo)
        print("All sources removed.")
        return 0
    raise ValueError(f"Unknown source command: {args.source_command}")  # pragma: no cover


def _self_update() -> int:
    """Best-effort self-update: ``git pull`` in a checkout, else instructions."""
    import subprocess

    from cs2lm import __version__

    print(f"cs2lm {__version__}")
    current = Path(__file__).resolve().parent
    while True:
        if (current / ".git").exists():
            print(f"Updating from git checkout: {current}")
            proc = subprocess.run(
                ["git", "-C", str(current), "pull", "--ff-only"],
                capture_output=True,
                text=True,
            )
            if proc.stdout.strip():
                print(proc.stdout.strip())
            if proc.stderr.strip():
                print(proc.stderr.strip())
            return 0 if proc.returncode == 0 else 1
        if current.parent == current:
            break
        current = current.parent
    print(
        "Self-update is unavailable (not a git checkout). "
        "Run 'pip install -U cs2-link-manager' once the package is published."
    )
    return 0


def cmd_update(args: argparse.Namespace, logger: Logger) -> int:
    if args.self:
        return _self_update()

    from cs2lm.config import load_config
    from cs2lm.installer import PluginManager
    from cs2lm.sources import fetch_and_merge, get_sources
    from cs2lm.updater import (
        compute_actions,
        remove_orphans,
        scan_local,
        update_plugin,
    )

    cfg = load_config(args.repo)
    sources = get_sources(cfg)
    if not sources:
        print("No plugin sources configured. Add one with 'cs2lm source add <index-url>'.")
        return 0

    update_cfg = cfg.get("update", {}) or {}
    timeout = args.timeout or update_cfg.get("timeout", 30)
    api_range = update_cfg.get("api_version_range")
    merged, results = fetch_and_merge(
        args.repo, sources, timeout=timeout, api_version_range=api_range
    )

    for result in results:
        if result.get("error"):
            print(f"Source {result['url']}: SKIPPED ({result['error']})")
        else:
            index = result.get("index") or {}
            plugins = index.get("plugins") or {}
            print(f"Source {result['url']}: ok ({len(plugins)} plugins)")
        for warning in result.get("warnings") or []:
            print(f"  warning: {warning}")

    if args.names:
        missing = [n for n in args.names if n not in merged]
        if missing:
            print("Not in any source: " + ", ".join(missing))
        merged = {k: v for k, v in merged.items() if k in args.names}

    if not merged:
        print("No plugins in the merged index.")
        return 0

    local = scan_local(args.repo)
    install, update, skipped, orphans = compute_actions(merged, local)

    # Missing plugins are not listed here: huge indexes would drown out the
    # useful output. `cs2lm search` + `cs2lm install` are the browse flow.

    if update:
        print("\nUpdates:")
        for plugin in update:
            print(
                f"  update  {plugin} {local[plugin]} -> "
                f"{merged[plugin].get('version')} (from {merged[plugin].get('source')})"
            )
    else:
        print("\nNo updates available.")

    if not update and not orphans:
        print("Everything is up to date.")
        return 0

    errors: list[str] = []
    manager = PluginManager(
        args.repo,
        dry_run=args.dry_run,
        yes=args.yes,
        logger=logger,
    )

    for plugin in update:
        result = update_plugin(
            args.repo,
            plugin,
            merged[plugin],
            dry_run=args.dry_run,
            yes=args.yes,
            force=args.force,
            logger=logger,
        )
        status = result["status"]
        if status == "up-to-date":
            print(f"{plugin}: already up to date.")
        elif status == "aborted":
            print(f"{plugin}: update aborted.")
        elif status == "changed":
            print(
                f"{plugin}: {result['old_version']} -> {result['new_version']} "
                f"({len(result['added'])} added, {len(result['removed'])} removed, "
                f"{len(result['changed'])} changed"
                f"{', dry-run' if result.get('dry_run') else ''})."
            )
        elif status == "error":
            print(f"{plugin}: update failed: {result['message']}")
            errors.append(plugin)
        elif status == "not-in-repo":
            print(f"{plugin}: {result['message']}")

    if orphans:
        auto_remove = bool(cfg.get("update", {}).get("auto_remove_orphans", False))
        if args.remove_orphans or auto_remove:
            if args.dry_run:
                print(f"Would remove orphans: {', '.join(orphans)}")
            else:
                removed = remove_orphans(args.repo, orphans, manager=manager, logger=logger)
                print(f"Removed orphans: {', '.join(removed)}")
        else:
            print(
                f"Orphans (not in any source): {', '.join(orphans)} "
                "(use --remove-orphans to remove)"
            )

    return 1 if errors else 0


def cmd_profile(args: argparse.Namespace, logger: Logger) -> int:
    command = args.profile_command
    if command == "list":
        names = profiles.list_profiles(args.repo)
        if not names:
            print("No profiles.")
        else:
            for n in names:
                print(n)
        return 0
    if command == "create":
        if not args.name:
            raise ValueError(
                "Profile name is required. Usage: "
                "cs2lm profile create <name> [plugins...]"
            )
        profiles.create_profile(args.repo, args.name, args.plugins)
        logger.info("profile", f"created profile '{args.name}'")
        return 0
    if command == "delete":
        profiles.delete_profile(args.repo, args.name)
        logger.info("profile", f"deleted profile '{args.name}'")
        return 0
    if command == "use":
        manager = PluginManager(args.repo, dry_run=args.dry_run, logger=logger)
        result = profiles.use_profile(args.repo, args.name, manager, logger=logger)
        enabled = result["enabled"]
        disabled = result["disabled"]
        print(f"Switched to profile '{args.name}':")
        print(f"  Enabled: {', '.join(enabled) if enabled else '(none)'}")
        print(f"  Disabled: {', '.join(disabled) if disabled else '(none)'}")
        return 0
    logger.error("profile", f"unknown profile command: {command}")
    return 2


def cmd_remove(args: argparse.Namespace, logger: Logger) -> int:
    import shutil
    from datetime import datetime

    from cs2lm.installer import PluginManager
    from cs2lm.manifest import plugin_dir

    repo = Path(args.repo)
    pdir = plugin_dir(repo, args.name)
    if not pdir.is_dir():
        raise ValueError(f"Plugin not found in repository: {args.name}")

    manager = PluginManager(repo, logger=logger)
    if manager.plugin_has_links(args.name):
        manager.uninstall(args.name)

    trash = repo / "trash" / "plugins"
    trash.mkdir(parents=True, exist_ok=True)
    dest = trash / f"{args.name}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    shutil.move(str(pdir), str(dest))
    logger.info("remove", f"removed plugin '{args.name}'")
    print(
        f"Removed '{args.name}' (moved to trash: {dest.name}). "
        f"Restore with 'cs2lm trash restore {args.name}'."
    )
    return 0


def cmd_trash(args: argparse.Namespace, logger: Logger) -> int:
    import shutil

    from cs2lm.manifest import plugin_dir

    repo = Path(args.repo)
    trash = repo / "trash" / "plugins"
    if args.trash_command == "list":
        if not trash.is_dir():
            print("Trash is empty.")
            return 0
        entries = sorted(trash.iterdir())
        if not entries:
            print("Trash is empty.")
            return 0
        for p in entries:
            print(p.name)
        return 0
    if args.trash_command == "restore":
        if not trash.is_dir():
            raise ValueError(f"No trashed plugin named '{args.name}'.")
        candidates = sorted(trash.glob(f"{args.name}-*"))
        if not candidates:
            raise ValueError(f"No trashed plugin named '{args.name}'.")
        latest = candidates[-1]
        dest = plugin_dir(repo, args.name)
        if dest.exists():
            raise ValueError(
                f"A plugin '{args.name}' already exists in the repository. "
                "Remove it first, then restore from trash."
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(latest), str(dest))
        logger.info("trash", f"restored plugin '{args.name}'")
        print(f"Restored '{args.name}' from trash. Use 'cs2lm install {args.name}' to link it.")
        return 0
    raise ValueError(f"Unknown trash command: {args.trash_command}")  # pragma: no cover


HANDLERS = {
    "init": cmd_init,
    "add": cmd_add,
    "pack": cmd_pack,
    "install": cmd_install,
    "uninstall": cmd_uninstall,
    "enable": cmd_enable,
    "disable": cmd_disable,
    "list": cmd_list,
    "doctor": cmd_doctor,
    "import": cmd_import,
    "adopt": cmd_adopt,
    "profile": cmd_profile,
    "registry": cmd_registry,
    "search": cmd_search,
    "update": cmd_update,
    "source": cmd_source,
    "web": cmd_web,
    "remove": cmd_remove,
    "trash": cmd_trash,
}


def main(argv: list[str] | None = None) -> int:
    # On Windows, redirected stdout/stderr uses the system code page (e.g.
    # GBK). Force UTF-8 so web.log and console output are consistent across
    # platforms (same bytes as on Linux).
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

    parser = build_parser()
    args = parser.parse_args(argv)
    logger: Logger | None = None
    try:
        logger = _make_logger(args)
        handler = HANDLERS[args.command]
        return handler(args, logger)
    except (linking.ConflictError, InstallError) as exc:
        logger = logger or Logger()
        logger.error("cli", str(exc))
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError, OSError, linking.LinkError) as exc:
        logger = logger or Logger()
        logger.error("cli", str(exc))
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OverflowError as exc:
        logger = logger or Logger()
        logger.error("cli", str(exc))
        print(f"error: invalid numeric argument: {exc}", file=sys.stderr)
        return 1
    finally:
        if logger is not None:
            logger.close()