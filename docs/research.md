# Research: CS2 plugin management and symlink compatibility

> Written as part of the cs2-link-manager project. Sources are linked inline;
> all paths below are relative to the CS2 server installation root unless
> stated otherwise.

## 1. CS2 server directory structure (verified)

CounterStrikeSharp's official
[Getting Started](https://docs.cssharp.dev/docs/guides/getting-started.html)
guide and the
[roflmuffin/CounterStrikeSharp repository](https://github.com/roflmuffin/CounterStrikeSharp)
agree on the following structure after Metamod:Source and CounterStrikeSharp
are installed:

```
<server_path>/game/csgo/addons/
├── counterstrikesharp/
│   ├── api/          # CounterStrikeSharp.API.dll and friends
│   ├── bin/          # native host binaries
│   ├── dotnet/       # .NET runtime (with-runtime builds)
│   ├── plugins/      # <PluginName>/<PluginName>.dll + .deps.json + .pdb
│   ├── configs/      # <PluginName>/*.json per-plugin configs
│   ├── gamedata/     # gamedata.json (core signatures/offsets)
│   ├── lang/         # translations
│   └── shared/       # shared plugin API assemblies
├── metamod/
│   ├── bin/          # bin/linux64/metamod.so, bin/win64/metamod.dll
│   ├── metaplugins.ini
│   ├── counterstrikesharp.vdf
│   └── README.txt
├── metamod.vdf
└── metamod_x64.vdf
```

Key facts confirmed from the docs:

- Metamod:Source is loaded by adding `Game csgo/addons/metamod` to
  `game/csgo/gameinfo.gi` (Source 2 method, per
  [AlliedModders Wiki](https://wiki.alliedmods.net/Installing_metamod:source)).
  The `metamod.vdf` / `metamod_x64.vdf` files also ship with Metamod packages.
- CounterStrikeSharp is a Metamod plugin loaded through
  `addons/metamod/counterstrikesharp.vdf` (vdf-based loading) and/or
  `metaplugins.ini`.
- CSS plugins are discovered by scanning
  `game/csgo/addons/counterstrikesharp/plugins/`; each plugin lives in its own
  directory named after the plugin, containing at least the plugin `.dll`
  (see the [Hello World guide](https://docs.cssharp.dev/docs/guides/hello-world-plugin.html)).
- Per-plugin configuration is loaded from
  `game/csgo/addons/counterstrikesharp/configs/plugins/<Name>/` (confirmed by
  the [IScriptHostConfiguration API](https://docs.cssharp.dev/api/CounterStrikeSharp.API.Core.Hosting.IScriptHostConfiguration.html)
  which exposes `ConfigsPath`, `GameDataPath`, `PluginPath`, etc.).
- Metamod plugins are loaded via `addons/metamod/metaplugins.ini` (one relative
  path per line) or via `.vdf` files placed in `addons/metamod/`
  ([Configuring Metamod:Source](https://wiki.alliedmods.net/Configuring_Metamod:Source)).

### How a CSS plugin is loaded

1. The server starts; the engine loads Metamod via `gameinfo.gi`.
2. Metamod loads CounterStrikeSharp via `counterstrikesharp.vdf`.
3. CounterStrikeSharp enumerates directories under
   `addons/counterstrikesharp/plugins/`.
4. For each directory containing a `.dll` (and the required plugin
   attributes), it loads the plugin and calls `Load()`.

Implication for this tool: **a symlinked directory under `plugins/` is a valid
plugin location**, because the loader enumerates directories and reads files
through the normal filesystem API. The same applies to
`configs/plugins/<Name>/` — the config path is just a directory lookup.

## 2. Survey of existing tools

| Tool | Language | Approach | Strengths | Weaknesses |
| --- | --- | --- | --- | --- |
| [ConchPluginManager](https://github.com/connercsbn/ConchPluginManager) | C# (CSS plugin, in-game) | Downloads GitHub release zips, extracts into `plugins/`, tracks plugins in a config; commands: `css_cpm_install/update/remove/list` | In-game management, auto-update on reload | Overwrites conflicting files without asking; only manages `plugins/` dir, not configs/gamedata; in-game only, no server-file-level safety; no symlinks, no profiles |
| [cs2pm](https://github.com/hadley31/cs2pm) | Go (CLI) | YAML manifest of plugins with `downloadUrl`, `extractPrefix`, `uninstall.directories`; `cs2pm install/uninstall` | Simple declarative manifest; CLI | Early stage; uninstall deletes tracked directories (destructive); no symlink/repo separation; no profiles; no conflict safety |
| [Plugify](https://github.com/untrustedmodders/plugify) | C++ (plugin framework) | A runtime/plugin loader with multi-language modules (C++, C#, Python, Go, ...) and a package manager (`mamba`) | Powerful, modern; language-agnostic; hot-reload | Different niche: it is a plugin *framework*, not a server plugin *manager*; manages its own plugin format, not CSS/Metamod packages |
| [L4D2-Manager](https://github.com/Q1en/L4D2-Manager-Linux) | Bash (Linux tool) | Server deployment + plugin manager for L4D2/SourceMod; keeps plugin folders in `Available_Plugins/`, records `Installed_Receipts/` (file lists), reversible uninstall moves files back | Clean reversible uninstall, modular plugin folders, multi-instance | L4D2-specific; copies files rather than symlinking; no profiles |

None of these tools combine **central repository + symlink mapping + manifest
file tracking + profile switching + conflict safety** for CS2. That is the gap
this project fills.

## 3. Symlink compatibility by path

### `addons/counterstrikesharp/plugins/` — SAFE ✅

- CSS enumerates plugin directories at startup. A directory symlink (or
  junction on Windows) is transparent to .NET directory enumeration.
- Hosting providers already symlink CSS config directories in production
  (e.g. [5Stack docs](https://docs.5stack.gg/servers/game-server-nodes/custom-plugins):
  "The configs directory is symlinked rather than copied").

### `addons/counterstrikesharp/configs/` — SAFE ✅

- Per-plugin configs live in `configs/plugins/<Name>/`. A directory symlink
  for the plugin's config directory works and is used in production (5Stack).

### `addons/counterstrikesharp/gamedata/` — PARTIAL ⚠️

- CounterStrikeSharp reads the core `gamedata/gamedata.json` (single file).
  Overwriting or symlinking that shared file is dangerous because multiple
  plugins/framework versions depend on it.
- Plugin-owned gamedata placed in subdirectories such as
  `gamedata/plugins/<Name>/` can be symlinked safely.
- **Rule**: refuse to manage `gamedata/gamedata.json`; allow plugin-owned
  subdirectories/files.

### `addons/metamod/` — PARTIAL ⚠️ (Metamod *core*)

- Metamod's native binary (`bin/linux64/metamod.so`) is loaded by the engine
  via `gameinfo.gi` search paths and `metamod.vdf`. Native library loading from
  symlinked directories generally works on Linux, but:
  - The loader files (`metamod.vdf`, `metamod_x64.vdf`) and `gameinfo.gi`
    interplay are sensitive; Steam updates and engine changes have broken
    Metamod before ([alliedmodders/metamod-source#232](https://github.com/alliedmodders/metamod-source/issues/232)).
  - On Windows, native DLL loading through symlinks is more fragile, and file
    symlinks require privileges (see §4).
- **Decision**: the tool does **not** symlink the Metamod core framework.
  Core frameworks (Metamod, CounterStrikeSharp) are considered
  *out of scope* for installation; users install them manually. Third-party
  Metamod plugins are handled conservatively:
  - `.vdf` files in `addons/metamod/` → **copy + backup + rollback**.
  - `metaplugins.ini` edits → **backup + rollback** (line append/remove).
  - Plugin binary directories (`addons/<pluginname>/`) → symlink/junction.

### `metaplugins.ini` — NOT SYMLINKED ✅ (managed as config)

- `metaplugins.ini` is a small text file. We edit it (append/remove lines)
  with a backup of the original and rollback on failure, rather than
  symlinking it.

## 4. Windows specifics (verified)

- Windows symbolic links require the **SeCreateSymbolicLinkPrivilege**; this
  means running as Administrator, or enabling **Developer Mode**
  (Windows 10 1703+). See
  [SS64 mklink](https://ss64.com/nt/mklink.html) and
  [Microsoft Learn](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/mklink).
- **Directory junctions** (`mklink /J`) do **not** require privileges and work
  for directories only.
- **File hard links** (`mklink /H`) work without privileges but only within the
  same volume, and cannot link directories.
- Strategy implemented by cs2-link-manager:
  1. Try `os.symlink` (directory symlink).
  2. On failure → try junction (`mklink /J`) for directories.
  3. On failure → copy mode, with a clear warning that symlinks require
     Administrator/Developer Mode.

## 5. Final architecture decisions

1. **Repository**: plugins are stored as immutable copies under
   `repo/plugins/<Name>/files/`, mirroring the `addons/` tree.
2. **Manifest**: every plugin has `manifest.json` recording name, version,
   type, timestamps, per-file source→target mappings, and the *links* the
   installer actually creates (directory symlinks / file symlinks / copies),
   plus optional `metaplugins.ini` lines.
3. **CSS plugins**: linked with **directory symlinks** (junction on Windows)
   at `addons/counterstrikesharp/plugins/<Name>/` and any plugin-owned
   `configs/plugins/<Name>/`, `lang/<Name>/`, `gamedata/plugins/<Name>/` paths.
4. **Metamod core**: not managed by the tool (manual install). Third-party
   Metamod plugins: `.vdf` copied with backup, plugin dirs symlinked,
   `metaplugins.ini` edited with backup.
5. **Safety**: never overwrite unmanaged files (default refuse); `--backup`
   moves conflicts to `.cs2lm-backups/`; `--force` requires confirmation;
   paths are validated to stay inside the server root; uninstall only removes
   tool-created links and never deletes repository files.

## 6. Uncertain / needs verification

- Whether CounterStrikeSharp merges multiple gamedata files beyond
  `gamedata.json` (e.g. `gamedata/plugins/*.json`). We therefore treat
  `gamedata/gamedata.json` as forbidden and only link plugin-owned subdirs.
- Exact behavior of Metamod's vdf loader with symlinked directories on Windows
  was not formally documented; hence the conservative copy strategy for
  `addons/metamod/` config files.
- Some CSS plugins write config files at runtime into `configs/plugins/<Name>/`
  or their plugin directory; uninstalling a plugin removes those symlinked
  directories (the underlying repo files remain, but runtime-generated files
  inside the *server-side* target are removed if using copy fallback; with
  symlinks they remain in the repo copy and persist).