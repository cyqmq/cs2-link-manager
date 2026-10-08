# Changelog

All notable changes to cs2-link-manager are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **index.json plugin sources**: `cs2lm source add/list/remove/clear` manage
  an ordered list of `index.json` sources (with per-source auth headers).
  `cs2lm update` now fetches every source (ETag/If-Modified-Since cached,
  per-source failure isolated, offline fallback to the last merged table),
  merges them (highest version per plugin; earlier source wins ties), scans
  local manifests, and installs/updates/skips accordingly. Missing plugins
  are installed, lower versions are updated via atomic directory replacement
  (`.<name>.new` -> `.<name>.old` -> swap -> remove `.old`), orphans can be
  removed with `--remove-orphans`, and every action is appended to
  `state/update_log.json`. Requires supports version ranges
  (`{"DepLib": ">=1.0.0"}`) and dependencies are installed first.
- **stricter index validation**: merge skips (with warnings) entries that
  are non-SemVer, missing/invalid `sha256`, `yanked: true`, or whose
  `api_version` falls outside the configured `update.api_version_range`;
  relative `download_url` values are resolved against the source URL.
- **index spec**: `docs/INDEX.md` defines the `index.json` schema (v1):
  top-level `schema`/`name`/`generated_at`/`plugins`, per-plugin entries
  (`id`/`version`/`download_url`/`sha256`/`api_version`/`requires`/...),
  merge semantics, version rules, and extension/compatibility conventions.
- **package format spec**: `docs/format.md` documents the `.cs2pkg`
  structure, `cs2pkg.json` fields, multi-plugin `plugins` semantics,
  `requires`, version detection, and its relationship to `index.json`.
- **version auto-detection**: `cs2lm add` reads `<Name>.deps.json` target
  entries (`<AssemblyName>/<version>`, e.g. `Retakes/3.1.1`) and uses the
  detected version instead of defaulting to `1.0.0`; the version survives
  `pack` round trips.
- **shared/ support**: single-plugin CSS packages that ship a `shared/`
  tree now get it linked to the server; splitting a multi-plugin package
  reports a warning instead of silently dropping `shared/`.
- **package identity validation**: install/update verifies the zip's
  `manifest.json` `id` and `version` match the index entry before applying.
- **multi-plugin packages**: packages containing several plugin directories
  under `plugins/` (e.g. SimpleAdmin's main plugin + FunCommands +
  StealthModule) can now be split into separate repository entries via
  `--plugins SimpleAdmin,FunCommands,StealthModule` on `add`/`registry add`,
  or the `plugins` field in `cs2pkg.json` (`add --pkg` splits
  automatically). `install --from-registry` adds every plugin in the package
  and installs the requested one; `update` refreshes each plugin from the
  same registry entry.
- **web readiness**: `GET /api/health` returns a JSON health check and
  startup prints `CS2LM_READY port=...`, so wrapper scripts can detect that
  the server is listening (not merely that a process is alive).
- **web daemon**: `web --daemon [--pidfile ...] [--daemon-log ...]` starts
  the UI as a detached background process cross-platform (Linux
  `start_new_session`, Windows `DETACHED_PROCESS`), replacing per-platform
  `nohup`/`Start-Process` boilerplate in panel scripts.
- **web status card**: the page now shows Web/Auth/CS2-process/Repo/Server
  status at a glance.
- **doctor verbose**: `--verbose` reports each installed plugin's actual
  link mode (symlink / junction / copy).
- **UTF-8 output**: CLI forces UTF-8 on stdout/stderr so Windows web.log is
  identical to Linux (no more GBK mojibake).
- **cs2pkg metadata**: `cs2pkg.json` now carries optional
  author/description/license/homepage/repository/dependencies, preserved
  through `pack` and `add --pkg` round trips.
- **checksums**: every managed file records its SHA-256 in the manifest as
  groundwork for future integrity/update checks.
- **URL addons search**: `add --url` recursively finds nested `addons/`
  trees (GitHub source zips: `public/addons`, `.Compiled/addons`, etc.) and
  accepts `--addons-subdir` for explicit location.
- **local registry**: `registry add/list/remove`, `search`, and
  `install --from-registry` provide a one-command plugin install workflow
  from a plain JSON registry (`registry.json`).
- **update mechanism**: `cs2lm update [name...]` downloads each plugin's
  registry URL, compares SHA-256 checksums against the current manifest,
  shows a file-level diff, replaces repo files (only files recorded in the
  old manifest are touched), regenerates the manifest, and re-installs the
  plugin if it was installed. `--yes` skips confirmation; `--dry-run`
  reports without changing anything.
- **plugin dependencies**: manifest / cs2pkg.json / registry entries can
  declare `requires` (list of plugin names). `install` auto-installs missing
  dependencies (with cycle detection), and `uninstall` refuses to disable a
  plugin that another installed plugin requires.
- **zip checksums**: `registry add --sha256 <hex>` records the expected
  SHA-256 of the source zip; `install --from-registry` and `update` verify it
  before extraction.
- **BOM tolerance**: all JSON/text reads now use `utf-8-sig`, so manifests
  edited with BOM-writing editors (e.g. Windows PowerShell) load cleanly.
- **README**: documents the registry, URL subdirs, package metadata,
  multi-plugin rejection, the update workflow, dependency management and
  checksum verification.

### Changed

- **update**: `cs2lm update` now reads configured `index.json` sources
  instead of `registry.json` entries. `registry add` remains available for
  `install --from-registry`; for version-based updates use
  `cs2lm source add <index-url>`.
- **requires**: dependency declarations may be an object
  (`{"DepLib": ">=1.0.0"}`) as well as a plain list of plugin names; the
  installer accepts both.

### Fixed

- **split multi-plugin packages**: `split_css_plugins` no longer assumes a
  `configs/` directory exists. Packages that only ship `plugins/` +
  `shared/` (e.g. the official CS2-SimpleAdmin release) now split without
  crashing (`[WinError 3]` on a missing `configs/` path is gone).
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
  binding a non-loopback host without a token now **errors out** instead of
  just warning, and an explicitly empty token is rejected. Tokens can be
  sent via the `X-Auth-Token` header (script/API friendly) as well as the
  `?token=` query parameter / form field.
- **web**: SIGTERM triggers graceful shutdown, preventing port leaks.
- **version**: `--version` now reads from `importlib.metadata` (single
  source: `pyproject.toml`), with a fallback for source checkouts.
- **init**: running `init` again prints `Repository already initialized:
  <repo>` for easy scripting.
- **README**: documents UDP/TCP single-port coexistence and the daemon mode.

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