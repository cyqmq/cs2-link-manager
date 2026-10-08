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