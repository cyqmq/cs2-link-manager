# Changelog

All notable changes to cs2-link-manager are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **web UI language switching**: the web UI now supports English / 中文 with a
  top-right `中文 | English` switcher (also present on the login page). The
  choice is persisted in a `lang` cookie (`?lang=en|zh` sets it), falls back to
  the browser's `Accept-Language`, survives search/install/toggle actions, and
  also localizes the catalog status text.
- **embedded default source**: `cs2lm init` now includes the community port
  hub `https://github.com/cyqmq/cs2pkg-port` as a pre-configured source
  (removable like any other; `source clear` is respected and the default is
  never re-injected). Old repositories with an empty source list get it added
  once via a one-time migration. `source add` also accepts GitHub repository
  page URLs and resolves them to their raw `index.json`.
- **multi-plugin packaging**: `cs2lm pack Alpha Beta --out dir` exports several
  repository plugins as one multi-plugin `.cs2pkg` (`plugins` list in
  `cs2pkg.json`); `add --pkg` splits it back into separate entries. Mixed
  packages (CSS/Swiftly/Plugify/ModSharp standard layouts + Metamod addons)
  are split per framework.
- **game-content packages** (`kind: "content"`): `.cs2pkg` packages can now
  carry arbitrary server files (`cfg/`, `overrides/`, `gamedata/`, `addons/`)
  with a `roots` mapping, `requires_frameworks` and `platform` fields.
  `add --pkg` imports them as `content` entries; `install` copies files to the
  server (uninstall moves them to trash); framework requirements are enforced
  like plugins; `pack` re-exports the package layout. `install --components`
  selects which roots to install.
- **platform awareness**: `platform` (`windows`/`linux`/`all`) is validated on
  import/install and a warning is printed on mismatch.
- **index.json plugin sources**: `cs2lm source add/list/remove/clear` manage
  an ordered list of `index.json` sources (with per-source auth headers).
  `cs2lm update` now fetches every source (ETag/If-Modified-Since cached,
  per-source failure isolated, offline fallback to the last merged table),
  merges them (highest version per plugin; earlier source wins ties), scans
  local manifests, and updates/skips accordingly. Lower versions are updated
  via atomic directory replacement (`.<name>.new` -> `.<name>.old` -> swap ->
  remove `.old`), orphans can be removed with `--remove-orphans`, and every
  action is appended to `state/update_log.json`. Requires supports version
  ranges (`{"DepLib": ">=1.0.0"}`) and dependencies are installed first.
- **unified catalog search**: `cs2lm search [<query>] [--source <url>]`
  merges every configured `index.json` source plus the local registry into a
  numbered catalog (name / version / install status / source / description),
  writes the snapshot to `state/search_result.json`, and `cs2lm install #N`
  installs directly from that snapshot.
- **install from sources**: `cs2lm install <name|#N>` falls back to the
  merged index when a plugin is missing locally, downloads/verifies/installs
  it, and recursively installs `requires` dependencies from the same sources
  (still falling back to the local registry as a last resort).
- **pure update**: `cs2lm update` only updates locally installed plugins.
  Missing plugins are **not listed or auto-installed** (huge indexes would
  drown out useful output); `--self` attempts to update the tool itself (git
  pull in a checkout).
- **multi-framework support**: new `cs2lm/frameworks.py` registry covering
  Metamod:Source (`metamod`), CounterStrikeSharp (`css`), SwiftlyS2
  (`swiftly`), Plugify (`plugify`) and ModSharp (`modsharp`). `--type`
  choices and `plugin_type` accept ids/aliases; `classify_plugin` auto-detects
  each framework root in the `addons/` tree; copy/link/normalisation logic is
  generalized to `plugins/<Name>` + `configs/plugins/<Name>` layouts.
- **framework detection & install guard**: `detect_frameworks(server,
  csgo_rel)` reports which frameworks are installed; `install` refuses to link
  a plugin whose framework is missing on the server (clear error, `--force`
  overrides); `doctor --verbose` lists framework status.
- **web management API**: `web` now shows the server's installed frameworks on
  the status card and exposes `GET /api/status`, `GET /api/plugins`,
  `GET /api/catalog`, `POST /api/install`, `POST /api/uninstall` and
  `POST /api/update`; the page gains catalog search with one-click install and
  an "update all" button.
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
- **remove/trash commands**: `cs2lm remove <name>` uninstalls and moves a
  plugin to `trash/plugins/`; `cs2lm trash list` / `trash restore <name>`
  list and restore trashed plugins.
- **update --force**: `cs2lm update --force` bypasses the framework-presence
  guard when relinking updated plugins.
- **enable/disable --force**: both commands accept `--force` with the same
  semantics as `install --force`.
- **source add validation**: `source add` fetches and validates `index.json`
  (schema + `plugins` object) before saving, so a bad URL fails immediately.
- **registry add reachability probe**: a HEAD probe warns (but still saves)
  when the registry URL is unreachable.
- **doctor --verbose on subcommand**: `cs2lm doctor --verbose` works as the
  README documents (subcommand flag, not only a global flag).
- **add UX guards**: passing a `.cs2pkg` path to `add <name> <path>` suggests
  `--pkg`; packages with no `addons/` tree or binaries warn; zip packages
  without `manifest.json`/`cs2pkg.json` warn when the version defaults to
  `1.0.0` and suggest `--version`.
- **auth-free health probe**: `GET /api/health` no longer requires the auth
  token, so wrapper scripts can use it as a true readiness probe.

### Changed

- **update**: `cs2lm update` now reads configured `index.json` sources
  instead of `registry.json` entries. `registry add` remains available for
  `install --from-registry`; for version-based updates use
  `cs2lm source add <index-url>`.
- **update no longer installs missing plugins**: previously `update`
  installed every plugin absent locally; now it only reports them and
  instructs the user to run `cs2lm install <name>`. Plugin acquisition is a
  `search` -> `install` flow.
- **requires**: dependency declarations may be an object
  (`{"DepLib": ">=1.0.0"}`) as well as a plain list of plugin names; the
  installer accepts both.
- **catalog status**: `search` now distinguishes `已装(version)` (linked
  to the server) from `仓库(version,未链接)` (repo-only, not enabled), so
  a half-updated plugin is no longer shown as "installed".
- **framework detection**: marker-less frameworks (swiftly/plugify/modsharp)
  are only reported installed when their root contains framework-owned files
  beyond `plugins`/`configs`; plugin links created by a `--force` install no
  longer make the framework look installed.
- **update atomicity**: the framework guard runs *before* the atomic swap,
  and a failed relink rolls back the previous version (`.old` is kept until
  success), so a blocked/failed update never leaves a half-updated manifest.

### Fixed

- **web --daemon port conflict no longer misreports success**: each launch
  generates a random nonce that the child echoes through `/api/health`; the
  parent only reports "ready" when the response carries *this* launch's
  nonce. A second daemon on an occupied port now fails with a clear `error:`
  and leaves no pidfile behind.
- **invalid .cs2pkg friendly error**: `add --pkg` on a non-zip file now
  raises `Invalid .cs2pkg file ... not a valid zip archive` instead of a
  `zipfile.BadZipFile` traceback.
- **search with no results keeps the snapshot**: an empty search no longer
  overwrites `state/search_result.json`, so `install #N` references stay
  valid.
- **install --force is remembered**: a plugin installed with `--force` records
  `force_installed` on its manifest; a later `disable` + `enable` (or an
  `update` relink) no longer requires `--force` again.
- **read-only commands with --log**: `list`/`doctor`/`search` etc. now emit
  a `command completed` record, so `--log` produces a non-empty file.
- **friendly "Source not found"**: `add`/`import`/`add_content` now say
  "Plugin source not found: ... Check that the path exists", and `add` on an
  uninitialized repo explains to run `cs2lm init` first.
- **init warns on missing server path**: `cs2lm init --server` prints a
  warning when the server directory does not exist yet.
- **registry add rejects non-URLs**: `registry add <name> not-a-url` is
  rejected instead of being saved with only an unreachable warning.
- **profile delete warns**: deleting a profile whose plugins are still
  enabled warns that enabled state is not rolled back.
- **empty/non-plugin dirs add with a warning**: `classify_plugin` now falls
  back to `css` for directories with no recognizable layout, matching the
  README's promised warning instead of raising.
- **search version column placeholder**: entries without a version display
  `-` in the table.
- **add/pack options between positionals**: `cs2lm add Name --type css path`
  and `cs2lm pack Alpha --name X Beta --out dir` now parse correctly (argv
  is reordered so positionals come first). `--dry-run` after a subcommand is
  also accepted, e.g. `cs2lm update --dry-run` (previously only the global
  `cs2lm --dry-run update` form worked).
- **install #N registry entries**: `install #N` from a search snapshot now
  installs registry entries. Previously the snapshot's `registry_entry`
  skipped the registry download branch, so it failed with "Plugin not found in
  repository".
- **import relative paths**: `cs2lm import <name> <path>` resolves relative
  paths against the server root (matching `path-in-server`), not the CWD.
- **add success output**: `cs2lm add` now prints
  `Added <name> (<type> v<version>).` instead of being silent.
- **re-init updates server path**: running `cs2lm init --server <new>` on an
  existing repository updates `server_path`/`csgo_rel` without touching
  plugins, sources, or profiles.
- **--log missing directory**: `--log` no longer silently creates parent
  directories; a missing or unwritable parent produces a friendly `error:`.
- **install --force on the source path**: `--force` is forwarded through
  `install_from_index_with_deps()` / `install_plugin_from_index()`, so
  `install <name> --force` and `install #N --force` both bypass the
  framework guard even when the plugin is not yet in the repository.
- **update half-updated state**: when the framework is missing, `update`
  now refuses *before* touching the repository (old version + links stay
  intact), instead of swapping the directory and then failing to relink.
- **web port validation**: `--port` outside 0-65535 prints a friendly
  `error:` message instead of an `OverflowError` traceback; `run_webui` also
  converts `OverflowError` to `ValueError`.
- **unwritable --log path**: logger creation moved inside the guarded error
  block, so an unwritable log file becomes `error: ...` instead of a raw
  traceback.
- **daemon stdout buffering**: the daemon child runs `python -u`, so
  `CS2LM_READY port=...` is flushed to `--daemon-log` immediately.
- **daemon readiness confirmation**: `web --daemon` waits until the child is
  genuinely listening (probes `/api/health` or parses the log's actual port);
  on failure it returns non-zero and does not write a misleading pidfile.
- **web --port 0**: prints the *actual* bound port in the URL and
  `CS2LM_READY port=...`, matching the documented readiness contract.
- **corrupted manifest**: `load_manifest` wraps `JSONDecodeError` in a clear
  error naming the plugin and manifest path.
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