from pathlib import Path

import pytest

from cs2lm import importer
from cs2lm.manifest import list_plugins, load_manifest

from conftest import make_css_package


def test_import_plugin_from_server(repo_server, tmp_path):
    repo, server = repo_server
    # simulate an already-installed plugin in the server
    installed = server / "game" / "csgo" / "addons" / "counterstrikesharp" / "plugins" / "Existing"
    installed.mkdir(parents=True)
    (installed / "Existing.dll").write_bytes(b"MZ")
    (installed / "Existing.deps.json").write_text("{}")

    manifest = importer.import_plugin(repo, "Existing", installed)

    assert manifest["imported"] is True
    assert manifest["enabled"] is False
    assert list_plugins(repo) == ["Existing"]
    assert (
        "game/csgo/addons/counterstrikesharp/plugins/Existing/Existing.dll"
        in {f["target"] for f in manifest["files"]}
    )
    # original files are untouched
    assert (installed / "Existing.dll").exists()


def test_import_requires_path_inside_server(repo_server, tmp_path):
    repo, _server = repo_server
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "X.dll").write_bytes(b"MZ")
    with pytest.raises(ValueError, match="inside the server directory"):
        importer.import_plugin(repo, "X", outside)


def test_import_rejects_symlink_with_clear_message(repo_server, tmp_path):
    repo, server = repo_server
    external = tmp_path / "external" / "ApiPlugin"
    external.mkdir(parents=True)
    (external / "ApiPlugin.dll").write_bytes(b"MZ")
    plugins_dir = server / "game" / "csgo" / "addons" / "counterstrikesharp" / "plugins"
    link = plugins_dir / "ApiPlugin"
    link.symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        importer.import_plugin(repo, "ApiPlugin", link)