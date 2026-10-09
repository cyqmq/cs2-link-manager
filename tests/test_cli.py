import json
from pathlib import Path

import pytest

from cs2lm import cli
from cs2lm import linking

from conftest import make_css_package


def run(args):
    return cli.main(args)


def test_cli_init_add_install_list_uninstall(repo_server, tmp_path):
    repo, server = repo_server
    pkg = make_css_package(tmp_path, "CliPlugin")

    assert run(["--repo", str(repo), "add", "CliPlugin", str(pkg)]) == 0
    assert run(["--repo", str(repo), "install", "CliPlugin"]) == 0

    target = server / "game" / "csgo" / "addons" / "counterstrikesharp" / "plugins" / "CliPlugin"
    assert linking.path_exists(target)

    assert run(["--repo", str(repo), "list"]) == 0
    assert run(["--repo", str(repo), "uninstall", "CliPlugin"]) == 0
    assert not linking.path_exists(target)
    assert (
        repo
        / "plugins"
        / "CliPlugin"
        / "files"
        / "addons"
        / "counterstrikesharp"
        / "plugins"
        / "CliPlugin"
        / "CliPlugin.dll"
    ).exists()


def test_cli_init_requires_server():
    with pytest.raises(SystemExit):
        run(["init"])


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        run(["--version"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "cs2lm" in captured.out
    assert "0.1.0" in captured.out


def test_cli_dry_run_install(repo_server, tmp_path):
    repo, server = repo_server
    pkg = make_css_package(tmp_path, "DryRun")
    run(["--repo", str(repo), "add", "DryRun", str(pkg)])
    run(["--repo", str(repo), "install", "DryRun"])
    run(["--repo", str(repo), "--dry-run", "uninstall", "DryRun"])
    # dry-run uninstall must NOT remove the real link
    target = server / "game" / "csgo" / "addons" / "counterstrikesharp" / "plugins" / "DryRun"
    assert linking.path_exists(target)

    other = make_css_package(tmp_path, "DryRun2")
    run(["--repo", str(repo), "add", "DryRun2", str(other)])
    run(["--repo", str(repo), "--dry-run", "install", "DryRun2"])
    target2 = server / "game" / "csgo" / "addons" / "counterstrikesharp" / "plugins" / "DryRun2"
    assert not linking.path_exists(target2)


def test_cli_json_logging(repo_server, tmp_path):
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "JsonPlugin")
    log_file = tmp_path / "cs2lm.log.json"
    run(
        [
            "--repo",
            str(repo),
            "--log",
            str(log_file),
            "--log-format",
            "json",
            "add",
            "JsonPlugin",
            str(pkg),
        ]
    )
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert lines
    record = json.loads(lines[0])
    assert record["level"] == "INFO"
    assert "event" in record


def test_cli_doctor_error_code(repo_server, tmp_path):
    repo, server = repo_server
    pkg = make_css_package(tmp_path, "Broken")
    run(["--repo", str(repo), "add", "Broken", str(pkg)])
    run(["--repo", str(repo), "install", "Broken"])
    target = server / "game" / "csgo" / "addons" / "counterstrikesharp" / "plugins" / "Broken"
    target.unlink()
    assert run(["--repo", str(repo), "doctor"]) == 1


def test_cli_profile_flow(repo_server, tmp_path):
    repo, _server = repo_server
    a = make_css_package(tmp_path, "Alpha")
    b = make_css_package(tmp_path, "Beta")
    run(["--repo", str(repo), "add", "Alpha", str(a)])
    run(["--repo", str(repo), "add", "Beta", str(b)])
    assert run(["--repo", str(repo), "profile", "create", "fun", "Alpha"]) == 0
    assert run(["--repo", str(repo), "profile", "use", "fun"]) == 0
    assert run(["--repo", str(repo), "profile", "list"]) == 0


def test_cli_profile_use_prints_diff(repo_server, tmp_path, capsys):
    repo, _server = repo_server
    a = make_css_package(tmp_path, "Alpha")
    b = make_css_package(tmp_path, "Beta")
    run(["--repo", str(repo), "add", "Alpha", str(a)])
    run(["--repo", str(repo), "add", "Beta", str(b)])
    run(["--repo", str(repo), "profile", "create", "fun", "Alpha"])
    run(["--repo", str(repo), "profile", "use", "fun"])
    captured = capsys.readouterr()
    assert "Enabled: Alpha" in captured.out
    assert "Disabled: Beta" in captured.out


def test_cli_conflict_returns_clean_error(repo_server, tmp_path, capsys):
    repo, server = repo_server
    pkg = make_css_package(tmp_path, "Conflicted")
    run(["--repo", str(repo), "add", "Conflicted", str(pkg)])
    target = server / "game" / "csgo" / "addons" / "counterstrikesharp" / "plugins" / "Conflicted"
    target.mkdir(parents=True)
    rc = run(["--repo", str(repo), "install", "Conflicted"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "error:" in captured.err
    assert "backup" in captured.err


def test_cli_init_idempotent_prints_message(repo_server, capsys):
    repo, server = repo_server
    assert run(["--repo", str(repo), "init", "--server", str(server)]) == 0
    captured = capsys.readouterr()
    assert "already initialized" in captured.out


def test_cli_web_rejects_empty_token(repo_server, capsys):
    repo, _server = repo_server
    rc = run(["--repo", str(repo), "web", "--host", "0.0.0.0", "--auth-token", ""])
    assert rc == 1
    captured = capsys.readouterr()
    assert "must not be empty" in captured.err


def test_cli_web_requires_token_on_non_loopback(repo_server, capsys):
    repo, _server = repo_server
    rc = run(["--repo", str(repo), "web", "--host", "0.0.0.0"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "requires --auth-token" in captured.err


def test_cli_registry_roundtrip(repo_server, tmp_path):
    """registry add -> search -> install --from-registry (file:// source)."""
    import zipfile

    from cs2lm.installer import PluginManager
    from cs2lm.manifest import list_plugins

    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "RegPlugin")
    zip_path = tmp_path / "regplugin.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(pkg.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(pkg).as_posix())

    # registry add
    rc = run(
        [
            "--repo",
            str(repo),
            "registry",
            "add",
            "RegPlugin",
            zip_path.as_uri(),
            "--description",
            "A registry plugin",
            "--type",
            "css",
        ]
    )
    assert rc == 0

    # search finds it
    assert run(["--repo", str(repo), "search", "registry"]) == 0

    # install --from-registry downloads the file:// zip, adds, and installs.
    rc = run(["--repo", str(repo), "install", "RegPlugin", "--from-registry"])
    assert rc == 0
    assert "RegPlugin" in list_plugins(repo)
    installed = [p["name"] for p in PluginManager(repo).list_plugins() if p["installed"]]
    assert "RegPlugin" in installed


def test_cli_registry_sha256_mismatch(repo_server, tmp_path, capsys):
    """install --from-registry rejects a zip whose checksum does not match."""
    import hashlib
    import zipfile

    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "HashPlugin")
    zip_path = tmp_path / "hash.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(pkg.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(pkg).as_posix())

    rc = run(
        [
            "--repo",
            str(repo),
            "registry",
            "add",
            "HashPlugin",
            zip_path.as_uri(),
            "--sha256",
            "0" * 64,
        ]
    )
    assert rc == 0
    rc = run(["--repo", str(repo), "install", "HashPlugin", "--from-registry"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "Checksum mismatch" in captured.err


def test_cli_registry_sha256_match(repo_server, tmp_path):
    """A matching registry SHA-256 installs successfully."""
    import hashlib
    import zipfile

    from cs2lm.installer import PluginManager

    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "HashPlugin")
    zip_path = tmp_path / "hash.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(pkg.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(pkg).as_posix())

    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    assert (
        run(
            [
                "--repo",
                str(repo),
                "registry",
                "add",
                "HashPlugin",
                zip_path.as_uri(),
                "--sha256",
                digest,
            ]
        )
        == 0
    )
    assert run(["--repo", str(repo), "install", "HashPlugin", "--from-registry"]) == 0
    installed = [p["name"] for p in PluginManager(repo).list_plugins() if p["installed"]]
    assert "HashPlugin" in installed


def test_cli_registry_multi_plugin(repo_server, tmp_path):
    """A registry entry with ``plugins`` adds all plugins, installs the named one."""
    import zipfile

    from conftest import make_multi_css_package
    from cs2lm.installer import PluginManager
    from cs2lm.manifest import list_plugins

    repo, _server = repo_server
    pkg = make_multi_css_package(
        tmp_path, ["SimpleAdmin", "FunCommands", "StealthModule"]
    )
    zip_path = tmp_path / "multi.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(pkg.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(pkg).as_posix())

    assert (
        run(
            [
                "--repo",
                str(repo),
                "registry",
                "add",
                "SimpleAdmin",
                zip_path.as_uri(),
                "--plugins",
                "SimpleAdmin,FunCommands,StealthModule",
            ]
        )
        == 0
    )

    assert run(["--repo", str(repo), "install", "SimpleAdmin", "--from-registry"]) == 0
    assert set(list_plugins(repo)) == {"SimpleAdmin", "FunCommands", "StealthModule"}
    installed = {p["name"] for p in PluginManager(repo).list_plugins() if p["installed"]}
    assert "SimpleAdmin" in installed


# ---------------------------------------------------------------------------
# Bug 1: add/pack accept options placed between positional arguments
# ---------------------------------------------------------------------------


def test_add_intermixed_options(repo_server, tmp_path, capsys):
    """Options between `add <name>` and <path> are accepted (Bug 1)."""
    from cs2lm.manifest import list_plugins

    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "FakedMM")
    assert (
        run(
            [
                "--repo",
                str(repo),
                "add",
                "FakedMM",
                "--type",
                "css",
                str(pkg),
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "Added FakedMM" in out
    assert "FakedMM" in list_plugins(repo)


def test_add_intermixed_force_is_still_rejected(repo_server, tmp_path):
    """`--force` is not an add option and must still fail cleanly (Bug 1)."""
    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "ReproB")
    with pytest.raises(SystemExit) as excinfo:
        run(["--repo", str(repo), "add", "ReproB", "--force", str(pkg)])
    assert excinfo.value.code == 2


def test_pack_intermixed_options(repo_server, tmp_path):
    """Options between `pack` plugin names are accepted (Bug 1 pattern)."""
    repo, _server = repo_server
    run(["--repo", str(repo), "add", "Alpha", str(make_css_package(tmp_path, "Alpha"))])
    run(["--repo", str(repo), "add", "Beta", str(make_css_package(tmp_path, "Beta"))])
    out_dir = tmp_path / "out"
    assert (
        run(
            [
                "--repo",
                str(repo),
                "pack",
                "Alpha",
                "--name",
                "Combo",
                "Beta",
                "--out",
                str(out_dir),
            ]
        )
        == 0
    )
    assert (out_dir / "Combo.cs2pkg").exists()


# ---------------------------------------------------------------------------
# Issue 4: import resolves relative paths against the server root
# ---------------------------------------------------------------------------


def test_import_relative_path(repo_server):
    """import treats the path as server-relative, not CWD-relative (Issue 4)."""
    from cs2lm.manifest import list_plugins

    repo, server = repo_server
    plugin_dir = (
        server
        / "game"
        / "csgo"
        / "addons"
        / "counterstrikesharp"
        / "plugins"
        / "ServPlugin"
    )
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "ServPlugin.dll").write_bytes(b"MZ")
    (plugin_dir / "ServPlugin.deps.json").write_text("{}")
    rel = plugin_dir.relative_to(server)
    assert run(["--repo", str(repo), "import", "ServPlugin", rel.as_posix()]) == 0
    assert "ServPlugin" in list_plugins(repo)


# ---------------------------------------------------------------------------
# Issue 6: re-running init updates the server path
# ---------------------------------------------------------------------------


def test_init_repeat_updates_server_path(tmp_path):
    """Re-running init with a new --server updates config.json (Issue 6)."""
    repo = tmp_path / "repo"
    for d in ("plugins", "profiles", "state"):
        (repo / d).mkdir(parents=True, exist_ok=True)
    srv1 = tmp_path / "srv1"
    srv2 = tmp_path / "srv2"
    assert run(["--repo", str(repo), "init", "--server", str(srv1)]) == 0
    cfg1 = json.loads((repo / "config.json").read_text(encoding="utf-8"))
    assert cfg1["server_path"] == str(srv1.resolve())
    assert run(["--repo", str(repo), "init", "--server", str(srv2)]) == 0
    cfg2 = json.loads((repo / "config.json").read_text(encoding="utf-8"))
    assert cfg2["server_path"] == str(srv2.resolve())


# ---------------------------------------------------------------------------
# Bug 2: invalid .cs2pkg gives a friendly error instead of a traceback
# ---------------------------------------------------------------------------


def test_add_invalid_cs2pkg_friendly(repo_server, tmp_path, capsys):
    """A non-zip .cs2pkg file is rejected with a friendly message."""
    repo, _server = repo_server
    fake = tmp_path / "fake.cs2pkg"
    fake.write_text("not a zip", encoding="utf-8")
    assert run(["--repo", str(repo), "add", "--pkg", str(fake)]) == 1
    captured = capsys.readouterr()
    assert "not a valid zip" in (captured.out + captured.err)


# ---------------------------------------------------------------------------
# Bug 5: read-only commands with --log still populate the log file
# ---------------------------------------------------------------------------


def test_readonly_command_writes_log(repo_server, tmp_path):
    """list (a read-only command) with --log must write to the log file."""
    repo, _server = repo_server
    log_file = tmp_path / "ro.log"
    assert run(["--repo", str(repo), "--log", str(log_file), "list"]) == 0
    text = log_file.read_text(encoding="utf-8")
    assert "command completed" in text


# ---------------------------------------------------------------------------
# UX 1: distinguish "source path missing" from "repository not initialized"
# ---------------------------------------------------------------------------


def test_add_nonexistent_path_friendly(repo_server, tmp_path, capsys):
    """add with a missing path explains that the source path does not exist."""
    repo, _server = repo_server
    missing = tmp_path / "nope"
    assert run(["--repo", str(repo), "add", "Ghost", str(missing)]) == 1
    captured = capsys.readouterr()
    assert "Plugin source not found" in (captured.out + captured.err)


def test_add_uninitialized_repo_friendly(tmp_path, capsys):
    """add on an uninitialized repo tells the user to run init first."""
    repo = tmp_path / "not-init"
    assert run(["--repo", str(repo), "add", "X", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "Repository not initialized" in (captured.out + captured.err)


# ---------------------------------------------------------------------------
# UX 2: init warns when the server path does not exist
# ---------------------------------------------------------------------------


def test_init_nonexistent_server_warns(tmp_path, capsys):
    """init to a missing server path prints a warning, not silence."""
    repo = tmp_path / "repo"
    for d in ("plugins", "profiles", "state"):
        (repo / d).mkdir(parents=True, exist_ok=True)
    srv = tmp_path / "does-not-exist"
    assert run(["--repo", str(repo), "init", "--server", str(srv)]) == 0
    captured = capsys.readouterr()
    assert "WARNING: server path does not exist yet" in captured.out


# ---------------------------------------------------------------------------
# UX 3: registry add rejects strings that are obviously not URLs
# ---------------------------------------------------------------------------


def test_registry_add_rejects_non_url(repo_server, capsys):
    """registry add 'not-a-url' fails instead of silently saving it."""
    repo, _server = repo_server
    assert run(["--repo", str(repo), "registry", "add", "BadUrl", "not-a-url"]) == 1
    captured = capsys.readouterr()
    assert "Invalid registry URL" in (captured.out + captured.err)


# ---------------------------------------------------------------------------
# UX 4: profile delete warns when its plugins are still enabled
# ---------------------------------------------------------------------------


def test_profile_delete_warns_enabled_plugins(repo_server, tmp_path, capsys):
    """Deleting a profile whose plugins are enabled warns about no rollback."""
    from cs2lm.installer import PluginManager

    repo, _server = repo_server
    pkg = make_css_package(tmp_path, "ProPlugin")
    assert run(["--repo", str(repo), "add", "ProPlugin", str(pkg)]) == 0
    assert run(["--repo", str(repo), "install", "ProPlugin"]) == 0
    assert PluginManager(repo).plugin_has_links("ProPlugin")
    assert run(["--repo", str(repo), "profile", "create", "prod", "ProPlugin"]) == 0
    assert run(["--repo", str(repo), "profile", "delete", "prod"]) == 0
    captured = capsys.readouterr()
    assert "still enabled" in captured.out


# ---------------------------------------------------------------------------
# UX 5: adding an empty directory warns (README behavior) instead of erroring
# ---------------------------------------------------------------------------


def test_add_empty_dir_warns(repo_server, tmp_path, capsys):
    """An empty directory is added with a warning, matching the README."""
    repo, _server = repo_server
    empty = tmp_path / "empty"
    empty.mkdir()
    assert run(["--repo", str(repo), "add", "Empty", str(empty)]) == 0
    captured = capsys.readouterr()
    assert "does not look like a plugin" in (captured.out + captured.err)