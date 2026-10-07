"""Reverse-import an existing plugin from a CS2 server into the repository."""
from __future__ import annotations

from pathlib import Path

from cs2lm import linking
from cs2lm.config import load_config
from cs2lm.logutil import Logger
from cs2lm.manifest import add_plugin, load_manifest, save_manifest
from cs2lm.paths import is_relative_to


def import_plugin(
    repo: str | Path,
    name: str,
    source_path: str | Path,
    type_hint: str | None = None,
    version: str | None = None,
    logger: Logger | None = None,
) -> dict:
    """Import a plugin directory that already lives inside the server.

    The plugin content is copied into the repository and a manifest is
    generated. The original server files are left untouched; use
    ``install --backup`` (or remove them manually) before installing from
    the repository.
    """
    logger = logger or Logger()
    cfg = load_config(repo)
    server = Path(cfg["server_path"]).resolve()
    raw_source = Path(source_path).expanduser()
    source = raw_source.resolve()

    if not source.exists():
        raise FileNotFoundError(f"Source not found: {source}")
    if raw_source.is_symlink() or linking.is_junction(raw_source):
        raise ValueError(
            f"{raw_source} is a symlink (it resolves to {source}) and is "
            "likely already managed by this tool or another repository. "
            "Remove the symlink and re-run import, or point to the real "
            "plugin directory inside the server."
        )
    if not is_relative_to(source, server):
        raise ValueError(
            f"Source path must be inside the server directory ({server}): {source}"
        )

    manifest = add_plugin(
        repo,
        name,
        source,
        type_hint=type_hint,
        version=version,
    )
    manifest["imported"] = True
    manifest["enabled"] = False
    save_manifest(repo, name, manifest)

    logger.info(
        "import",
        f"imported plugin '{name}' from {source}",
        files=len(manifest.get("files", [])),
    )
    return manifest