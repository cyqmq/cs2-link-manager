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