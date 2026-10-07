# Changelog

All notable changes to cs2-link-manager are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-07

### Added

- **Core CLI** (`cs2lm`): `init`, `add`, `install`, `uninstall`, `enable`,
  `disable`, `list`, `profile create/use/list/delete`, `doctor`, `import`.
- **Central repository**: plugins are stored as immutable copies under
  `<repo>/plugins/<Name>/files/` with a generated `manifest.json` (files,
  links, ini lines, dependencies).
- **Link strategy**: directory symlinks for CSS plugin paths (junction
  fallback on Windows, then copy mode), copy + backup + rollback for Metamod
  `.vdf` files, line-edit + backup for `metaplugins.ini`.
- **Safety**: unmanaged conflicts refused by default; `--backup` (confirm
  then back up), `--force` (take over without asking), `--yes` (skip
  confirmation); paths validated to stay inside the server root; repository
  files never deleted; core framework files rejected at `add` time.
- **State database**: `<repo>/state/links.json` records tool-created links for
  precise uninstall and `doctor` orphan detection.
- **Profiles**: named plugin sets, switch with a diff report.
- **Doctor**: server structure checks (`gameinfo.gi`, Metamod wiring, core
  files), broken/misplaced links, permissions, conflicts, orphan links,
  CSS API version dependency checks.
- **URL install**: `add --url <zip-url>` downloads and extracts a plugin zip.
- **`.cs2pkg` package format**: standardized zip distribution
  (`cs2pkg.json` + plugin file tree); `add --pkg` installs, `pack` exports.
- **Adopt**: `adopt` copies existing server plugins into the repository for
  unified management ("landing layer" for external managers).
- **Web UI**: `web` starts a local read/write web interface (stdlib only,
  binds to 127.0.0.1 by default).
- **Logging**: text and JSON logs; global `--dry-run` for write commands.
- **Docs**: `docs/research.md`, README, `CONTRIBUTING.md`, examples.
- **CI**: GitHub Actions workflow running the test suite on Linux
  (Python 3.11, 3.12, 3.13).

### Fixed

- `profile use` now detects plugins that are marked enabled in their
  manifest but not actually installed, and enables them.
- `--backup` now requires explicit confirmation (unless `--yes`), matching
  its documented safety promise.

[0.1.0]: https://github.com/cyqmq/cs2-link-manager/releases/tag/v0.1.0