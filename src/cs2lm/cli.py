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
    p_add.add_argument("--type", choices=["css", "metamod"], default=None)
    p_add.add_argument("--version", default=None)
    p_add.add_argument(
        "--addons-subdir",
        default=None,
        help="With --url: subdirectory inside the extracted zip whose addons/ "
        "tree holds the plugin (e.g. 'public' for public/addons)",
    )

    p_pack = sub.add_parser("pack", help="Package a repository plugin as a .cs2pkg file")
    p_pack.add_argument("name", help="Plugin name")
    p_pack.add_argument("--out", default=".", help="Output directory or file path (default: current directory)")

    p_install = sub.add_parser("install", help="Install a plugin (create links)")
    p_install.add_argument("name")
    p_install.add_argument("--from-registry", action="store_true", help="Add the plugin from the local registry first, then install")
    p_install.add_argument("--backup", action="store_true", help="Back up conflicting targets")
    p_install.add_argument("--force", action="store_true", help="Force install with confirmation")
    p_install.add_argument("--yes", action="store_true", help="Skip confirmation when using --backup")

    p_uninstall = sub.add_parser("uninstall", help="Uninstall a plugin (remove links)")
    p_uninstall.add_argument("name")

    p_enable = sub.add_parser("enable", help="Enable a plugin (create links)")
    p_enable.add_argument("name")

    p_disable = sub.add_parser("disable", help="Disable a plugin (remove links)")
    p_disable.add_argument("name")

    p_list = sub.add_parser("list", help="List plugins in the repository")

    p_doctor = sub.add_parser("doctor", help="Run diagnostics")

    p_import = sub.add_parser("import", help="Import an installed plugin back into the repo")
    p_import.add_argument("name")
    p_import.add_argument("path", help="Path inside the server directory")
    p_import.add_argument("--type", choices=["css", "metamod"], default=None)
    p_import.add_argument("--version", default=None)

    p_adopt = sub.add_parser(
        "adopt",
        help="Adopt existing CSS plugins on the server into the repository",
    )
    p_adopt.add_argument("--plugin", default=None, help="Only adopt this plugin")

    p_profile = sub.add_parser("profile", help="Manage profiles")
    p_profile_sub = p_profile.add_subparsers(dest="profile_command", required=True)
    p_profile_create = p_profile_sub.add_parser("create", help="Create a profile")
    p_profile_create.add_argument("name")
    p_profile_create.add_argument("plugins", nargs="*", help="Plugin names in the profile")
    p_profile_use = p_profile_sub.add_parser("use", help="Switch to a profile")
    p_profile_use.add_argument("name")
    p_profile_list = p_profile_sub.add_parser("list", help="List profiles")
    p_profile_delete = p_profile_sub.add_parser("delete", help="Delete a profile")
    p_profile_delete.add_argument("name")

    p_web = sub.add_parser("web", help="Start a local web UI to browse and toggle plugins")
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
    p_registry_add.add_argument("--type", choices=["css", "metamod"], default=None)
    p_registry_add.add_argument("--addons-subdir", default=None)
    p_registry_remove = p_registry_sub.add_parser("remove", help="Remove a registry entry")
    p_registry_remove.add_argument("name")
    p_registry_list = p_registry_sub.add_parser("list", help="List registry entries")

    p_search = sub.add_parser("search", help="Search the local plugin registry")
    p_search.add_argument("query", nargs="?", default="", help="Search text (name/description/url)")

    p_update = sub.add_parser("update", help="Update plugins from the local registry")
    p_update.add_argument("names", nargs="*", help="Plugin names to update (default: all registry entries in the repo)")
    p_update.add_argument("--yes", action="store_true", help="Apply updates without confirmation")

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
    from cs2lm.manifest import add_plugin
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

    if args.url:
        with tempfile.TemporaryDirectory(prefix="cs2lm-url-") as tmp:
            try:
                source = download_and_extract(args.url, tmp)
            except DownloadError as exc:
                raise ValueError(str(exc)) from exc
            if args.addons_subdir:
                source = resolve_addons_subdir(tmp, args.addons_subdir)
            if not args.name:
                raise ValueError("A plugin name is required when adding from a URL.")
            manifest = add_plugin(
                args.repo,
                args.name,
                source,
                type_hint=args.type,
                version=args.version,
            )
    elif args.pkg:
        with tempfile.TemporaryDirectory(prefix="cs2lm-pkg-") as tmp:
            source, meta = extract_pkg(args.pkg, tmp)
            type_hint = args.type or (meta or {}).get("plugin_type")
            version = args.version or (meta or {}).get("version")
            plugin_name = args.name or (meta or {}).get("name")
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
        if not args.name:
            raise ValueError("A plugin name is required when adding from a local path.")
        manifest = add_plugin(
            args.repo,
            args.name,
            args.path,
            type_hint=args.type,
            version=args.version,
        )
    logger.info(
        "add",
        f"added plugin '{manifest['name']}'",
        type=manifest["plugin_type"],
        files=len(manifest["files"]),
        links=len(manifest["links"]),
    )
    return 0


def cmd_install(args: argparse.Namespace, logger: Logger) -> int:
    if args.from_registry:
        from cs2lm.manifest import add_plugin, list_plugins
        from cs2lm.registry import load_registry
        from cs2lm.url_add import (
            DownloadError,
            download_and_extract,
            resolve_addons_subdir,
        )

        entry = load_registry(args.repo).get(args.name)
        if not entry:
            raise ValueError(
                f"No registry entry found: {args.name}. Add one with "
                "'cs2lm registry add <name> <url>'."
            )
        if args.name not in list_plugins(args.repo):
            with tempfile.TemporaryDirectory(prefix="cs2lm-reg-") as tmp:
                try:
                    source = download_and_extract(entry["url"], tmp)
                except DownloadError as exc:
                    raise ValueError(str(exc)) from exc
                if entry.get("addons_subdir"):
                    source = resolve_addons_subdir(tmp, entry["addons_subdir"])
                add_plugin(
                    args.repo,
                    args.name,
                    source,
                    type_hint=entry.get("type"),
                    meta=entry,
                )
            print(f"Added '{args.name}' from registry.")

    manager = PluginManager(
        args.repo,
        dry_run=args.dry_run,
        backup=args.backup,
        force=args.force,
        yes=args.yes,
        logger=logger,
    )
    manager.install(args.name)
    return 0


def cmd_uninstall(args: argparse.Namespace, logger: Logger) -> int:
    manager = PluginManager(args.repo, dry_run=args.dry_run, logger=logger)
    manager.uninstall(args.name)
    return 0


def cmd_enable(args: argparse.Namespace, logger: Logger) -> int:
    manager = PluginManager(args.repo, dry_run=args.dry_run, logger=logger)
    manager.enable(args.name)
    return 0


def cmd_disable(args: argparse.Namespace, logger: Logger) -> int:
    manager = PluginManager(args.repo, dry_run=args.dry_run, logger=logger)
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
        pid = start_daemon(
            args.repo,
            host=host,
            port=args.port,
            auth_token=token,
            pidfile=args.pidfile,
            logfile=args.daemon_log,
        )
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
    from cs2lm.registry import registry_search

    entries = registry_search(args.repo, args.query)
    if not entries:
        print(f"No registry entries matching {args.query!r}." if args.query else "Registry is empty.")
        return 0
    for name, entry in entries:
        desc = f" — {entry.get('description')}" if entry.get("description") else ""
        print(f"{name}: {entry['url']}{desc}")
    return 0


def cmd_update(args: argparse.Namespace, logger: Logger) -> int:
    from cs2lm.registry import load_registry
    from cs2lm.updater import update_plugin

    registry = load_registry(args.repo)
    if not registry:
        print("Registry is empty. Add entries with 'cs2lm registry add <name> <url>'.")
        return 0

    names = args.names or sorted(registry.keys())
    results = []
    for name in names:
        entry = registry.get(name)
        if not entry:
            print(f"Skipping {name}: no registry entry.")
            continue
        result = update_plugin(
            args.repo,
            name,
            entry,
            dry_run=args.dry_run,
            yes=args.yes,
            logger=logger,
        )
        results.append(result)
        status = result["status"]
        if status == "up-to-date":
            print(f"{name}: already up to date.")
        elif status == "not-in-repo":
            print(f"{name}: {result['message']}")
        elif status == "aborted":
            print(f"{name}: update aborted.")
        elif status == "changed":
            print(
                f"{name}: {result['old_version']} -> {result['new_version']} "
                f"({len(result['added'])} added, {len(result['removed'])} removed, "
                f"{len(result['changed'])} changed"
                f"{', dry-run' if result.get('dry_run') else ''})."
            )
        elif status == "error":
            print(f"{name}: update failed: {result['message']}")
        else:  # pragma: no cover
            print(f"{name}: unknown update status {status!r}.")

    errors = [r for r in results if r["status"] == "error"]
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
    "web": cmd_web,
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
    logger = _make_logger(args)
    try:
        handler = HANDLERS[args.command]
        return handler(args, logger)
    except (linking.ConflictError, InstallError) as exc:
        logger.error("cli", str(exc))
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError, OSError, linking.LinkError) as exc:
        logger.error("cli", str(exc))
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        logger.close()