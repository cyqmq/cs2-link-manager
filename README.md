# cs2-link-manager

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

* Python **3.11+** (standard library only; `tomllib` not needed — we use JSON).
* Linux (primary) or Windows (supported with junctions/copy fallback).
* A CS2 dedicated server with Metamod:Source and CounterStrikeSharp already
  installed (the tool does **not** install the core frameworks).

## Installation

```bash
git clone https://github.com/yourname/cs2-link-manager.git
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
| `add <name> <path>` | Copy a plugin package into the repo, generate `manifest.json`. |
| `install <name>` | Create links defined by the manifest (idempotent). |
| `uninstall <name>` | Remove tool-created links; keep repo files. |
| `enable <name>` / `disable <name>` | Create/remove links (same as install/uninstall). |
| `list` | Show name, type, version, enabled, installed status. |
| `profile create <name> [plugins...]` | Create a named profile. |
| `profile use <name>` | Enable profile plugins, disable all others. |
| `profile list` / `profile delete <name>` | List / delete profiles. |
| `doctor` | Check broken links, missing targets, permissions, conflicts. |
| `import <name> <path-in-server>` | Reverse-import a plugin already on the server. |

Global options: `--repo <path>` (default `plugins-repo`, or `$CS2LM_REPO`),
`--dry-run`, `--log <file>`, `--log-format text|json`, `--verbose`.

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
  * `--backup`: move the existing content to
    `<server>/.cs2lm-backups/<timestamp>/` and install;
  * `--force`: same as backup but asks for confirmation (skip with `--yes`).
* Unmanaged files are never overwritten.
* Repository files are never deleted.
* All paths are validated to stay inside the server root.
* Uninstall removes only links recorded in `state/links.json`; if a link was
  replaced by real content, uninstall refuses rather than delete data.
* Plugins that try to overwrite core framework files
  (`counterstrikesharp/bin`, `api`, `dotnet`, `gamedata/gamedata.json`,
  `metamod/bin`, `metamod.vdf`, ...) are rejected at `add` time.

## Windows notes

* Creating real symlinks requires **Administrator** privileges or **Developer
  Mode** (Windows 10 1703+).
* Directory junctions do **not** require privileges and are used
  automatically when symlink creation fails.
* If both fail, the tool falls back to **copy mode** and tells you why.
* The plugin directories (`plugins/<Name>`) are directories, so junction
  fallback works for the common case.

## Metamod handling (important)

* **Metamod/CSS core frameworks are not managed by this tool.** Install them
  manually (see [CounterStrikeSharp docs](https://docs.cssharp.dev/)). This
  is intentional: core files include native binaries and loader `.vdf` files
  whose symlinking is fragile.
* Third-party **Metamod plugins**:
  * `.vdf` files in `addons/metamod/` are managed as **copies** (backup +
    rollback on failure);
  * `metaplugins.ini` edits are made with a backup;
  * plugin binary directories (`addons/<pluginname>/`) are symlinked.

## Testing

```bash
pip install -e ".[dev]"
pytest
```

The test suite simulates a CS2 server under temporary directories — it never
touches a real server.

## Known limitations

* `add` expects a plugin package that is either an `addons/` tree or a plugin
  folder (`.dll` + `.deps.json` at its root). Zip files must be extracted
  first.
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
```

## License

MIT