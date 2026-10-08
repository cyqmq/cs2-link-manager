# Roadmap: multi-framework support, framework detection, web management

This document tracks the current upgrade plan. Statuses: [x] done, [~] in
progress, [ ] planned.

## P0 — `update` output convergence

- [x] Remove the "Plugins not installed (use 'cs2lm install <name>')" listing
      from `cs2lm update` so huge indexes do not drown out useful output.
      `update` only prints source status, actual updates, and orphan hints.

## P1 — Multi-framework support

Five plugin frameworks are supported (canonical id + aliases):

| Framework            | id            | aliases                     | addons/ root           |
|----------------------|---------------|-----------------------------|------------------------|
| Metamod:Source        | `metamod`     | `metamod-source`, `mm`      | `addons/metamod`       |
| CounterStrikeSharp    | `css`         | `counterstrikesharp`, `cs#` | `addons/counterstrikesharp` |
| SwiftlyS2             | `swiftly`     | `swiftly-s2`                | `addons/swiftly`       |
| Plugify               | `plugify`     | `plugify-s2`                | `addons/plugify`       |
| ModSharp              | `modsharp`    | `mod-sharp`                 | `addons/modsharp`      |

- [x] New `src/cs2lm/frameworks.py`: framework registry, alias normalisation,
      server-side detection, and the install guard.
- [x] Generalize `classify_plugin` to auto-detect each framework root.
- [x] Generalize `_copy_source` / `_collect_*_links` / plugin-directory
      normalisation so every framework's package layout maps correctly.
- [x] CLI `--type` choices and index `plugin_type` accept all framework ids.

Package layouts (target server paths, relative to the CS2 game dir):

* `metamod` — `addons/metamod` (`.vdf`), native addons `addons/<name>/bin`,
  `metaplugins.ini` lines.
* `css` — `addons/counterstrikesharp/{plugins,configs/plugins,lang,gamedata,shared}/...`.
* `swiftly` — `addons/swiftly/plugins/<name>`, `configs/plugins/<name>`.
* `plugify` — `addons/plugify/plugins/<name>`, `configs/plugins/<name>`.
* `modsharp` — `addons/modsharp/plugins/<name>`, `configs/plugins/<name>`.

## P2 — Framework detection & install guard

- [x] `detect_frameworks(server, csgo_rel)` reports which frameworks are
      actually installed under the server's `addons/` tree.
- [x] `install` refuses to link a plugin whose framework is missing from the
      server (clear error, `--force` overrides).
- [x] `doctor` reports detected/missing frameworks alongside existing checks
      (visible with `--verbose`; web always shows them via `/api/status`).

## P3 — Web management (for users without CLI access)

- [x] Status card lists detected server frameworks.
- [x] New JSON APIs: `GET /api/status`, `GET /api/plugins`,
      `GET /api/catalog`, `POST /api/install`, `POST /api/uninstall`,
      `POST /api/update`.
- [x] Page gains catalog search + one-click install + "update all".

## P4 — Tests & docs

- [x] Framework classification / detection / install-guard tests
      (`tests/test_frameworks.py`).
- [x] Web API endpoint tests (status/catalog/install/uninstall/update).
- [x] README/CHANGELOG updates for the new `plugin_type` values, update
      output behaviour, framework detection and web management.

### Future / low-priority

- [ ] Publish 0.1.0 to PyPI (`pipx install cs2-link-manager`).
- [ ] CI regression test for the example-package `pack` -> `add` round trip.
- [ ] Collate the legacy user feedback into `docs/known-issues.md` / FAQ.