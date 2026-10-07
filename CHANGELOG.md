# Changelog

All notable changes to cs2-link-manager are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **doctor**: Metamod binary detection now uses the real CS2 paths
  (`bin/linuxsteamrt64/metamod.2.cs2.so` and
  `bin/win64/metamod.2.cs2.dll`) instead of generic `linux64/metamod.so` /
  `win64/metamod.dll`, eliminating a false `missing-metamod-bin` warning on
  correctly installed servers. Test fixtures updated to the same paths.
- **doctor**: CSS API version comparison is normalized, so a plugin
  declaring `1.0.376` no longer mismatches an installed
  `CounterStrikeSharp.API.dll` version `1.0.376.0`.
- **add**: the repository name now wins over the package's internal plugin
  directory name. `cs2lm add Renamed ./DemoPlugin/` renames the plugin
  directories to `Renamed` (plugins/, configs/plugins/, lang/, gamedata/),
  so install/uninstall and profile switching no longer target the internal
  name. `add --pkg` can omit the name and uses `cs2pkg.json`'s `name`.
- **adopt**: symlinked plugin directories are skipped (with a hint) instead
  of crashing the whole scan when another repository manages plugins on the
  same server.
- **import**: rejecting a symlink path now explains that the path is likely
  already managed by this tool or another repository.
- **web**: `--auth-token <token>` adds a required shared token to the web UI;
  binding a non-loopback host without a token prints a warning. Tokens can be
  sent via the `X-Auth-Token` header (script/API friendly) as well as the
  `?token=` query parameter / form field.

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