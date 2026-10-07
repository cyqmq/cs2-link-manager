# Contributing to cs2-link-manager

Thanks for your interest! This document explains how to set up a development
environment, run the test suite, and submit changes.

## Development environment

Requirements:

* Python **3.11+**
* Git
* (Optional) `pytest` — installed via the `dev` extra

Clone the repository and install it in editable mode with the dev extras:

```bash
git clone https://github.com/cyqmq/cs2-link-manager.git
cd cs2-link-manager
pip install -e ".[dev]"
```

This installs the `cs2lm` console script and `pytest`.

## Project layout

```
src/cs2lm/       # package source (cli, installer, manifest, profiles, ...)
tests/           # pytest suite
docs/research.md  # design research and decisions
examples/        # example profiles and demo plugin package
```

## Running tests

Run the full suite from the repository root:

```bash
pytest -q
```

Or run a single file:

```bash
pytest tests/test_installer.py -q
```

The test suite only uses temporary directories — it never touches a real CS2
server.

## Code style

The project follows [PEP 8](https://peps.python.org/pep-0008/). Conventions
used in this codebase:

* **Type hints everywhere** — all functions and public attributes are annotated
  (`from __future__ import annotations` is used in modules).
* **Standard library only** at runtime. The CLI, manifest handling, linking,
  installer, profiles, doctor, and importer all use `argparse`, `json`,
  `pathlib`, `os`, `shutil`, `subprocess`, and friends. Do not add third-party
  runtime dependencies without discussion.
* **Path safety** — any user-supplied path is validated against the server
  root before use (see `src/cs2lm/paths.py`).
* **Safety invariants** — never overwrite unmanaged files, never delete
  repository files, never operate outside the server root. New features must
  preserve these invariants.

## Adding or changing behavior

1. **Add a test first** (or in the same commit as the change). Every behavior
   change should be covered by a test under `tests/`.
2. Update the README command reference or docs if user-facing behavior changes.
3. If you change how paths are linked, update the "Link strategy by path"
   section in `README.md` and the design notes in `docs/research.md`.

## Commit conventions

* Keep commits small and focused.
* Use descriptive messages, e.g.
  `Add plugin dependency check to doctor` or `Fix conflict detection when
  target is a symlink`.
* Reference related issues/PRs in the message body when relevant.

## Submitting changes

1. Create a branch:
   ```bash
   git checkout -b feature/your-change
   ```
2. Make your changes and run the full test suite:
   ```bash
   pytest -q
   ```
3. Commit with a descriptive message.
4. Push the branch and open a pull request:
   ```bash
   git push -u origin feature/your-change
   ```
5. In the PR description, summarize the change, mention any new tests, and
   note any behavior that affects users (commands, link strategy, docs).

CI runs the full test suite on Linux (Python 3.11, 3.12, 3.13) for every push
and pull request.

## Reporting issues

Open a GitHub issue with:

* The `cs2lm --version` output.
* Your OS and Python version.
* The command you ran and its output.
* Whether you used symlink, junction, or copy mode (if relevant).

Thanks for helping improve cs2-link-manager!