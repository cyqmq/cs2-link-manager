"""Tests for adopting existing server plugins into the repository."""
from __future__ import annotations

from cs2lm import cli
from cs2lm.adopt import adopt_css_plugins, find_css_plugins
from cs2lm.manifest import list_plugins

from conftest import make_css_package


def install_plugin_on_server(server, name):
    """Simulate an external tool having installed a plugin on the server."""
    pkg = server / "game" / "csgo" / "addons" / "counterstrikesharp" / "plugins" / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / f"{name}.dll").write_bytes(b"MZ")
    (pkg / f"{name}.deps.json").write_text("{}")


def test_find_css_plugins_names(repo_server):
    repo, server = repo_server
    install_plugin_on_server(server, "Alpha")
    install_plugin_on_server(server, "Beta")
    found = dict(find_css_plugins(repo))
    assert set(found) == {"Alpha", "Beta"}


def test_adopt_imports_plugins(repo_server):
    repo, server = repo_server
    install_plugin_on_server(server, "Alpha")
    install_plugin_on_server(server, "Beta")
    adopted = adopt_css_plugins(repo)
    assert set(adopted) == {"Alpha", "Beta"}
    assert set(list_plugins(repo)) == {"Alpha", "Beta"}


def test_adopt_skips_existing(repo_server):
    repo, server = repo_server
    install_plugin_on_server(server, "Alpha")
    adopt_css_plugins(repo)
    # second run: nothing new to adopt
    assert adopt_css_plugins(repo) == []


def test_adopt_only(repo_server):
    repo, server = repo_server
    install_plugin_on_server(server, "Alpha")
    install_plugin_on_server(server, "Beta")
    adopted = adopt_css_plugins(repo, only="Alpha")
    assert adopted == ["Alpha"]
    assert list_plugins(repo) == ["Alpha"]


def test_cli_adopt(repo_server, tmp_path):
    repo, server = repo_server
    # a repo plugin that is already tracked must not be adopted twice
    pkg = make_css_package(tmp_path, "Tracked")
    cli.main(["--repo", str(repo), "add", "Tracked", str(pkg)])
    install_plugin_on_server(server, "Tracked")
    install_plugin_on_server(server, "NewOne")

    rc = cli.main(["--repo", str(repo), "adopt"])
    assert rc == 0
    assert "Tracked" in list_plugins(repo)
    assert "NewOne" in list_plugins(repo)