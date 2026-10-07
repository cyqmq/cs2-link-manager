# cs2-link-manager

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)
[![CI](https://github.com/cyqmq/cs2-link-manager/actions/workflows/ci.yml/badge.svg)](https://github.com/cyqmq/cs2-link-manager/actions/workflows/ci.yml)

A cross-platform CLI tool that manages CS2 **CounterStrikeSharp** and
**Metamod** plugins by keeping plugin files in a central **repository** and
mapping them into the server directory with **symbolic links** (junctions on
Windows, with a copy fallback).

```
┌─────────────── plugins-repo ───────────────┐        ┌─────────────── cs2-server ──────────────┐
│ plugins/<Name>/                              │        │ game/csgo/addons/...                    │
│   manifest.json   (files + targets + links) │  link  │ counterstrikesharp/plugins/<Name>  ─────┼──▶ repo
│   files/addons/... (real plugin files)      │ ─────▶ │ counterstrikesharp/configs/plugins/<Name>│
└─────────────────────────────────────────────┘        └──────────────────────────────────────────┘
```

The plugin loader only ever sees the symlinked directories, so the server
behaves exactly as if the plugin files were copied there. Uninstalling only
removes the links — the repository copy is never touched.

## Why?

* **Uninstall residue** — uninstall removes only what the tool created.
* **Switch plugin sets quickly** — profiles enable/disable whole groups.
* **CS2 updates** — plugin files live outside `game/` and are not overwritten.
* **Rollback** — repository files are immutable; reinstall = relink.

## Requirements

* Python **3.11+** (standard library only).
* Linux (primary) or Windows (supported with junctions/copy fallback).
* A CS2 dedicated server with Metamod:Source and CounterStrikeSharp already
  installed (the tool does **not** install the core frameworks).

## Installation

```bash
git clone https://github.com/cyqmq/cs2-link-manager.git
cd cs2-link-manager
pip install .
# or for development:
pip install -e ".[dev]"
```

This installs the `cs2lm` command. You can also run it without installing:

```bash
python -m cs2lm --help
```

## Quick start

```bash
# 1. Initialize a repository (repo + server paths are stored in config.json)
cs2lm init --repo ./plugins-repo --server ./cs2-server

# 2. Add a plugin package (a folder containing an addons/ tree, or a plugin folder)
cs2lm add MyPlugin ./downloads/MyPlugin/

# 3. Install (create symlinks in the server)
cs2lm install MyPlugin

# 4. Verify
cs2lm list
cs2lm doctor

# 5. Remove links (repository copy is kept)
cs2lm uninstall MyPlugin

# 6. Profiles
cs2lm profile create competitive MatchZy SimpleAdmin
cs2lm profile use competitive
```

## Command reference

| Command | Description |
| --- | --- |
| `init --server <dir>` | Create repository skeleton and `config.json`. |
| `add <name> <path>` / `add <name> --url <zip-url>` / `add <name> --pkg <file.cs2pkg>` | Copy a plugin package (local, downloaded zip, or `.cs2pkg`) into the repo, generate `manifest.json`. |
| `pack <name> [--out <dir>]` | Package a repository plugin as a `.cs2pkg` file. |
| `install <name>` | Create links defined by the manifest (idempotent). |
| `uninstall <name>` | Remove tool-created links; keep repo files. |
| `enable <name>` / `disable <name>` | Create/remove links (same as install/uninstall). |
| `list` | Show name, type, version, enabled, installed status. |
| `profile create <name> [plugins...]` | Create a named profile. |
| `profile use <name>` | Enable profile plugins, disable all others, and print a diff report. |
| `profile list` / `profile delete <name>` | List / delete profiles. |
| `doctor` | Check server structure, broken links, missing targets, permissions, conflicts, CSS API version dependencies. |
| `import <name> <path-in-server>` | Reverse-import a plugin already on the server. |
| `adopt [--plugin <name>]` | Adopt existing CSS plugins on the server into the repository. |
| `web [--host H] [--port P]` | Start a local web UI to browse and toggle plugins. |

Global options: `--repo <path>` (default `plugins-repo`, or `$CS2LM_REPO`),
`--dry-run`, `--log <file>`, `--log-format text|json`, `--verbose`,
`--version`.

### `--dry-run`

Every write command supports `--dry-run`; it prints the actions that would be
performed and changes nothing.

```bash
cs2lm --repo ./plugins-repo --dry-run install MyPlugin
```

## How it works

### Manifest

Each plugin in the repository has `manifest.json`:

```json
{
  "name": "MyPlugin",
  "version": "1.0.0",
  "plugin_type": "css",
  "enabled": true,
  "files": [
    {"source": "files/addons/counterstrikesharp/plugins/MyPlugin/MyPlugin.dll",
     "target": "game/csgo/addons/counterstrikesharp/plugins/MyPlugin/MyPlugin.dll"}
  ],
  "links": [
    {"source": "files/addons/counterstrikesharp/plugins/MyPlugin",
     "target": "game/csgo/addons/counterstrikesharp/plugins/MyPlugin",
     "kind": "symlink-dir"}
  ],
  "ini_lines": []
}
```

* `files` maps every repository file to its target path (relative to the
  server root).
* `links` are the actual links the installer creates — typically one
  directory symlink per plugin-owned directory (`plugins/<Name>`,
  `configs/plugins/<Name>`, `gamedata/plugins/<Name>`, ...).
* `ini_lines` (Metamod plugins only) are lines appended to
  `addons/metamod/metaplugins.ini`.

### State database

* **Location**: `<repo>/state/links.json`.
* **Purpose**: records every link `install`/`enable` creates (plugin, source,
  target, kind, timestamp). `uninstall`/`disable` remove the matching records,
  which is how the tool knows exactly what to remove and never touches
  unmanaged files.
* **If you delete it**: `uninstall` has no records to follow, so server-side
  links are left in place (the manifest `enabled` flag is still updated).
  `doctor` will report those leftover links as `orphan-link` warnings.
  To recover cleanly: remove the leftover links (as listed by `doctor`),
  then run `cs2lm install <name>` again to rebuild the records.

### Link types

| Kind | Meaning |
| --- | --- |
| `symlink-dir` | Directory symlink (Linux) / junction fallback (Windows). |
| `symlink-file` | File symlink (used for plugin-owned single files). |
| `copy` | Plain copy, used for small Metamod config files (`.vdf`). |

On Windows the strategy is: try `os.symlink` → try junction (`mklink /J`) →
fall back to copy, with a clear warning about Administrator/Developer Mode
requirements.

## Conflict & safety rules

* If a target already exists and is **not** a link created by this tool:
  * default: **refuse**;
  * `--backup`: ask for confirmation, then move the existing content to
    `<server>/.cs2lm-backups/<timestamp>/` and install;
  * `--force`: move the existing content to backups and install
    **without asking** — use when you explicitly want to take over the
    path;
  * `--yes`: skip the confirmation prompt when using `--backup` (for
    scripts/CI).
* Unmanaged files are never overwritten.
* Repository files are never deleted.
* All paths are validated to stay inside the server root.
* Uninstall removes only links recorded in `state/links.json`; if a link was
  replaced by real content, uninstall refuses rather than delete data.
* Plugins that try to overwrite core framework files
  (`counterstrikesharp/bin`, `api`, `dotnet`, `gamedata/gamedata.json`,
  `metamod/bin`, `metamod.vdf`, ...) are rejected at `add` time.

## Windows notes

* Creating a **real symbolic link** requires the
  `SeCreateSymbolicLinkPrivilege`, which normally means running as
  **Administrator** or enabling **Developer Mode** (Windows 10 1703+,
  Settings → Privacy & security → For developers).
* **Directory junctions** (`mklink /J`) do **not** require Administrator or
  Developer Mode — any user can create them on NTFS volumes. Junctions work
  for directories only. The tool automatically falls back to a junction when
  creating a directory symlink fails.
* **Copy fallback** is used when both symlink and junction fail. Typical causes:
  * the target is on a non-NTFS filesystem (FAT32/exFAT, some network shares),
  * the target is a single file, not a directory (junctions cannot link
    files),
  * the parent directory is not writable.
  You will always see a clear warning explaining which mode was used and why.
* Install/uninstall still work correctly in copy mode; the only difference is
  that plugin updates require a reinstall (copies are not kept in sync
  automatically).
* The plugin directories (`plugins/<Name>`, `configs/plugins/<Name>`,
  `lang/<Name>`, `gamedata/plugins/<Name>`) are all directories, so junction
  fallback covers the common case.

## Link strategy by path

The tool decides per-path how to link plugin files into the server. Core
framework paths are never touched.

| Path (relative to `game/csgo/`) | Strategy | Why |
| --- | --- | --- |
| `addons/counterstrikesharp/plugins/<Name>/` | **symlink** (junction on Windows) | CSS enumerates this directory; a symlinked dir is transparent to .NET |
| `addons/counterstrikesharp/configs/plugins/<Name>/` | **symlink** (junction on Windows) | Per-plugin config directory |
| `addons/counterstrikesharp/lang/<Name>/` | **symlink** (junction on Windows) | Per-plugin translations |
| `addons/counterstrikesharp/gamedata/plugins/<Name>/` | **symlink** (junction on Windows) | Plugin-owned gamedata subdirectory |
| `addons/counterstrikesharp/gamedata/gamedata.json` | **not managed** | Shared by the framework; merging is manual |
| `addons/counterstrikesharp/api`, `bin`, `dotnet`, `shared` | **not managed** | CSS core framework |
| `addons/metamod/bin/` | **not managed** | Metamod native binaries (`.so`/`.dll`) |
| `addons/metamod/*.vdf` (third-party plugin) | **copy + backup + rollback** | Loader files are sensitive to symlinking |
| `addons/metamod/metaplugins.ini` | **line edit + backup + rollback** | Small text file edited in place |
| `addons/<metamod-plugin>/` (plugin binaries) | **symlink** (copy fallback on Windows) | Third-party Metamod plugin directory |
| `addons/metamod.vdf`, `addons/metamod_x64.vdf` | **not managed** | Metamod core loader files |
| `game/csgo/gameinfo.gi` | **not managed** | Engine config; Metamod is loaded from here |

**Metamod/CSS core frameworks are not managed by this tool.** Install them
manually (see
[CounterStrikeSharp docs](https://docs.cssharp.dev/) and
[Metamod:Source install guide](https://wiki.alliedmods.net/Installing_metamod:source)).
This is intentional: core files include native binaries and loader `.vdf`
files whose symlinking is fragile — the loader chain depends on how the engine
resolves `gameinfo.gi` search paths, and Metamod has been broken by engine
updates before (see
[metamod-source issue #232](https://github.com/alliedmodders/metamod-source/issues/232)).

## Metamod handling (important)

* Third-party **Metamod plugins**:
  * `.vdf` files in `addons/metamod/` are managed as **copies** (backup +
    rollback on failure);
  * `metaplugins.ini` edits are made with a backup and rolled back on
    failure;
  * plugin binary directories (`addons/<pluginname>/`) are symlinked
    (junction/copy fallback on Windows).

## Adding plugins from a URL

```bash
cs2lm add MyPlugin --url https://example.com/MyPlugin.zip
```

The tool downloads the zip, extracts it, locates the package root (the
`addons/` tree or a single wrapping directory), classifies the plugin type,
and generates the manifest automatically. The zip is not stored in the
repository — only the extracted plugin files are copied in.

## CSS API dependency checks

When a CSS plugin declares a `CounterStrikeSharp.API` version in its
`.deps.json`, the version is recorded in the manifest and `doctor` reports a
warning if it does not match the installed API:

* `api-version-mismatch` — the server has a different `CounterStrikeSharp.API`
  version than the plugin declares.
* `api-version-unverifiable` — the plugin declares a dependency but the
  installed API version could not be read automatically; check it manually.

The API version is read directly from
`addons/counterstrikesharp/api/CounterStrikeSharp.API.dll` using a small
built-in ECMA-335 metadata reader (no third-party dependency). If the DLL
cannot be parsed, `doctor` degrades to the unverifiable warning above.

## `.cs2pkg` package format

A `.cs2pkg` file is a zip archive that standardizes plugin distribution:

* `cs2pkg.json` — package metadata (name, version, plugin_type, ini_lines);
* the plugin file tree (an `addons/` tree mirroring the server layout).

Plugin authors can publish `.cs2pkg` files; server owners install them with:

```bash
cs2lm add MyPlugin --pkg ./MyPlugin.cs2pkg
```

Repository plugins can be exported back into this format:

```bash
cs2lm pack MyPlugin --out ./releases/
# -> releases/MyPlugin.cs2pkg
```

The format reuses the existing manifest/link generation: after `add --pkg`,
the plugin is stored in the repository and managed with symlinks exactly like
any other plugin.

## Adopting existing plugins

If a server already has plugins installed by another manager (or manually),
`adopt` copies them into the repository so you can manage them with symlinks
and profiles from then on — the tool acts as the "landing layer":

```bash
cs2lm adopt
# Adopted 3 plugin(s): MatchZy, SimpleAdmin, Retakes
# The original plugin files are still on the server.
# Take over each plugin with:
#   cs2lm install <name> --backup
```

The originals are left in place so nothing is destroyed during the copy.
To take over a plugin without manual cleanup, install it with `--backup` —
the old files are moved to `<server>/.cs2lm-backups/<timestamp>/` and the
plugin is linked from the repository:

```bash
cs2lm install MatchZy --backup
cs2lm install SimpleAdmin --backup
```

Use `--plugin <name>` to adopt a single plugin. Plugins already in the
repository are skipped.

## Web UI

A small read/write web interface is available for server owners who prefer a
browser over the CLI:

```bash
cs2lm web --port 8080
# cs2-link-manager Web UI at http://127.0.0.1:8080/  (Ctrl+C to stop)
```

The page lists plugins (name, type, version, enabled, installed) with
enable/disable buttons. **Security**: it binds to `127.0.0.1` by default and
has no authentication — do not expose it to an untrusted network. To use it
from a remote machine, tunnel it over SSH instead of opening the port:

```bash
ssh -L 8080:127.0.0.1:8080 user@server-host
# then open http://127.0.0.1:8080/ locally
```

## Testing

```bash
pip install -e ".[dev]"
pytest
```

The test suite simulates a CS2 server under temporary directories — it never
touches a real server.

## Known limitations

* `add` expects a plugin package that is either an `addons/` tree or a plugin
  folder (`.dll` + `.deps.json` at its root). Remote **zip** files are handled
  automatically via `--url`, and `.cs2pkg` files via `--pkg`; other local
  zip files must still be extracted first.
* The CSS API version check is best-effort: it reads the `.deps.json`
  declaration and the installed `CounterStrikeSharp.API.dll` assembly
  version. If the DLL cannot be parsed, `doctor` tells you to check
  manually.
* Metamod plugin support is best-effort; the primary supported type is
  CounterStrikeSharp.
* `gamedata/gamedata.json` cannot be managed (shared by the framework); merge
  such changes manually.
* Runtime-written files inside plugin directories (e.g. plugin-created
  configs) persist in the repository copy when using symlinks, and are removed
  with the copy when using copy fallback.

## Project layout

```
cs2-link-manager/
  src/cs2lm/        # CLI, installer, manifests, profiles, doctor, ...
  docs/research.md   # research notes and decisions
  tests/             # pytest suite (unit + integration)
  examples/          # example profiles and plugin package
  pyproject.toml
  README.md
  CONTRIBUTING.md
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, test
instructions, and pull request guidelines.

## License

MIT