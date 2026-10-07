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
    p_add.add_argument("name", help="Plugin name")
    p_add.add_argument(
        "path",
        nargs="?",
        help="Path to the plugin package or folder (omit when using --url)",
    )
    p_add.add_argument("--url", default=None, help="Download a zip package from this URL")
    p_add.add_argument("--type", choices=["css", "metamod"], default=None)
    p_add.add_argument("--version", default=None)

    p_install = sub.add_parser("install", help="Install a plugin (create links)")
    p_install.add_argument("name")
    p_install.add_argument("--backup", action="store_true", help="Back up conflicting targets")
    p_install.add_argument("--force", action="store_true", help="Force install with confirmation")
    p_install.add_argument("--yes", action="store_true", help="Skip confirmation with --force")

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

    return parser


def _make_logger(args: argparse.Namespace) -> Logger:
    return Logger(path=args.log, fmt=args.log_format, verbose=args.verbose)


def cmd_init(args: argparse.Namespace, logger: Logger) -> int:
    repo = Path(args.repo).expanduser().resolve()
    server = Path(args.server).expanduser().resolve()
    if (repo / "config.json").exists():
        logger.warn("init", f"repository already initialized: {repo}")
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
    from cs2lm.manifest import add_plugin
    from cs2lm.url_add import DownloadError, download_and_extract

    if args.url and args.path:
        raise ValueError("Provide either a local path or --url, not both")
    if not args.url and not args.path:
        raise ValueError("Provide a local path or --url for the plugin package")

    if args.url:
        with tempfile.TemporaryDirectory(prefix="cs2lm-url-") as tmp:
            try:
                source = download_and_extract(args.url, tmp)
            except DownloadError as exc:
                raise ValueError(str(exc)) from exc
            manifest = add_plugin(
                args.repo,
                args.name,
                source,
                type_hint=args.type,
                version=args.version,
            )
    else:
        manifest = add_plugin(
            args.repo,
            args.name,
            args.path,
            type_hint=args.type,
            version=args.version,
        )
    logger.info(
        "add",
        f"added plugin '{args.name}'",
        type=manifest["plugin_type"],
        files=len(manifest["files"]),
        links=len(manifest["links"]),
    )
    return 0


def cmd_install(args: argparse.Namespace, logger: Logger) -> int:
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
    issues = run_doctor(args.repo, logger=logger)
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
    "install": cmd_install,
    "uninstall": cmd_uninstall,
    "enable": cmd_enable,
    "disable": cmd_disable,
    "list": cmd_list,
    "doctor": cmd_doctor,
    "import": cmd_import,
    "profile": cmd_profile,
}


def main(argv: list[str] | None = None) -> int:
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