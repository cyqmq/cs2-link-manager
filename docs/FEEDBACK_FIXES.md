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