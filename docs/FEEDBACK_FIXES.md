# Feedback fix plan (from user bug report)

Status: [x] done, [~] in progress, [ ] planned.

## Bugs (by severity)

### B1 — `install #N --force` / source install ignores `--force`
- [x] `catalog.install_from_index_with_deps()` accepts `force` and forwards it to
      `install_plugin_from_index()` / `PluginManager`.
- [x] `catalog.install_plugin()` forwards `force` when falling back to sources.
- [x] Regression test: source-install with `--force` bypasses framework guard.

### B2 — `update` leaves a half-updated state; no `--force`
- [x] `update` gains `--force`; framework guard in `update_plugin` can be bypassed.
- [x] Framework check runs *before* the atomic swap, so a blocked update leaves
      old version + links untouched.
- [x] On relink failure after a swap, `_atomic_rollback` restores the old version.
- [x] Regression test: failing update keeps manifest/link state consistent and
      `update --force` completes the job.

### B3/B7 — unhandled tracebacks for invalid port / unwritable log path
- [x] `web --port` validates range 0-65535 with a friendly error.
- [x] `run_webui` converts `OverflowError` to `ValueError`.
- [x] `--log` unwritable path prints a friendly error (logger creation moved into
      the guarded try block; `OverflowError` branch added).
- [x] Tests for both.

### B4/B5 — daemon stdout buffering; `--port 0` shows wrong port
- [x] daemon child runs `python -u -m cs2lm`.
- [x] `web --port 0` prints the actually-bound port in URL + CS2LM_READY.
- [x] Test: health endpoint works without token; daemon test still passes.

### B6 — daemon reports success even when the child dies on bind
- [x] daemon waits/confirms the child is listening (`/api/health` probe or
      `CS2LM_READY port=` in the log) before reporting success.
- [x] Returns non-zero (`DaemonError` -> ValueError) and does not write the
      pidfile when the child fails to become ready.
- [x] Test: daemon test still passes.

### B8 — corrupted manifest raises raw Python exception
- [x] `load_manifest` wraps `JSONDecodeError` in a friendly `ValueError` naming
      the plugin and manifest path.
- [x] Test.

## UX / polish (U1-U11)

- [x] U1 `enable`/`disable` accept `--force` like `install`.
- [x] U2 `add <path.cs2pkg>` detects a `.cs2pkg` and suggests `--pkg`.
- [x] U3 `add --type` warns when no `addons/` tree was found (or no binaries).
- [x] U4 `source add` validates index.json (reachable + schema).
- [x] U5 `registry add` warns when URL is unreachable.
- [x] U6 add `cs2lm remove <name>` (repo) and `trash list`/`restore`.
- [x] U7 catalog status distinguishes repo version vs server-linked state.
- [x] U8 `doctor` accepts `--verbose` (CLI).
- [x] U9 `profile create` error message clarity.
- [x] U10 `add --url` warns when zip lacks manifest.json / version stays 1.0.0.
- [x] U11 `/api/health` auth-free readiness probe (documented).

## Docs
- [x] README/CHANGELOG updates for each behavior change.

## Feature request — 全家桶/整合包（CS2-Bot-Improver 等）
- [x] Short-term: multi-plugin packaging. `pack` accepts multiple names and
      produces one multi-plugin `.cs2pkg` (`plugins` field), round-trips via
      `add --pkg`.
- [x] Long-term: game-content packages. `.cs2pkg` gains `kind: "content"`,
      `roots` (multi-root: `cfg/`, `overrides/`, `addons/`, `game/`),
      `requires_frameworks` and `platform`. Content entries install by copy,
      uninstall to trash, and are shown as `content` in `list`.
- [x] Selective installation: `install --components cfg,addons` installs only
      the chosen content roots.
- [x] Mixed-framework splitting: `split_package_plugins` routes standard
      framework plugins and Metamod addons per-framework.
- [x] Platform awareness: `platform` mismatch warns on import/install.
- [x] Tests + docs for all of the above.

## Second-round feedback (old users)

### B1 — `add` options mixed between positional arguments fail to parse
- [x] `_normalize_argv` reorders argv so positionals come first; `add Name
      --type css path` and `pack Alpha --name X Beta --out dir` work.
- [x] `--dry-run` may appear before or after the subcommand (promoted to a
      global position; subparser duplicates would break argparse's global
      flag, so they are not added).
- [x] Tests: intermixed add/pack, `--dry-run` after `update`, invalid
      `add --force` still exits 2.

### B2 — `install #N` ignores registry entries
- [x] `catalog.install_plugin()` enters the registry branch when the snapshot
      provides `registry_entry` (condition now includes
      `registry_entry is not None`).
- [x] Test: `install #1` from a registry-only search snapshot installs.

### B3 — `update --dry-run` unrecognized
- [x] `--dry-run` after the subcommand is accepted and honored.

### U4 — `import` path semantics
- [x] `importer.import_plugin` resolves relative paths against the server
      root; `import <name> game/csgo/...` works from any CWD.
- [x] Help text + README updated.

### U5 — `add` success prints nothing
- [x] `cmd_add` prints `Added <name> (<type> v<version>).` on every path
      (local, URL, --pkg, content, multi-plugin split).

### U6 — repeated `init` cannot change server path
- [x] `cmd_init` on an existing repo updates `server_path` / `csgo_rel`
      (plugins/sources/profiles untouched) and reports the change.

### U7 — `--log` silently creates missing directories
- [x] `Logger` no longer mkdirs the parent; missing/unwritable parent raises
      a friendly `ValueError` ("directory ... does not exist / is not writable").
- [x] Test for missing parent + existing unwritable parent.

## Docs
- [x] README/CHANGELOG updated for every item above.

## Third-round feedback (5 bugs + 6 UX)

### B1 — `web --daemon` port conflict falsely reports success
- [x] `start_daemon` generates a per-launch nonce (`CS2LM_READY_NONCE`) that
      the child echoes through `/api/health`; `_probe_ready` only returns true
      when the health body carries *this* launch's nonce.
- [x] On an occupied port the second child exits, the parent raises
      `DaemonError`, no pidfile is written.
- [x] Unit test: `_probe_ready` matches/refuses nonces against a local HTTP
      server.

### B2 — invalid `.cs2pkg` throws a traceback
- [x] `extract_pkg` wraps `zipfile.BadZipFile` in a friendly `ValueError`
      ("Invalid .cs2pkg file ... not a valid zip archive").
- [x] CLI test: `add --pkg fake.cs2pkg` returns 1 with a friendly message.

### B3 — `search` with no results overwrites the install snapshot
- [x] `save_search_results` returns False and preserves the old snapshot when
      a search yields no rows; `cmd_search` prints a note.
- [x] Test: a no-result search keeps the previous `install #N` snapshot.

### B4 — `install --force` vs `enable` inconsistency
- [x] `_install_plugin` skips the framework guard when the manifest carries
      `force_installed`; a force install records it, so plain `enable` after
      `disable` works without `--force`.
- [x] Test: force-install -> disable -> enable without force.

### B5 — read-only commands with `--log` produce an empty file
- [x] `main` logs a `command completed` record after every successful command,
      so `list`/`doctor`/`search` populate `--log`.

### U1 — "Source not found" too vague / uninit repo not distinguished
- [x] `add_plugin`/`add_content` say "Plugin source not found ... check the
      path"; `cmd_add` checks initialization first and tells the user to run
      `cs2lm init`.

### U2 — `init` to a nonexistent server path silently succeeds
- [x] `cmd_init` prints a warning when `--server` does not exist yet.

### U3 — `registry add not-a-url` is saved despite a warning
- [x] `registry_add` rejects URLs whose scheme is not http/https/file.

### U4 — `profile delete` of an in-use profile has no warning
- [x] `cmd_profile delete` warns when the deleted profile's plugins are
      still enabled (no rollback).

### U5 — README promises warning for non-plugin dirs but `add` errors
- [x] `classify_plugin` defaults directories with no recognizable layout to
      `css`, so the existing "does not look like a plugin" warning runs
      (README behavior restored).

### U6 — `search` version column blank for versionless entries
- [x] `print_catalog` displays `-` for entries without a version.

## Docs
- [x] README/CHANGELOG updated for every item above; tests: 217 passing.