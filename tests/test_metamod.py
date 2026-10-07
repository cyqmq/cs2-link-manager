from pathlib import Path

from cs2lm import linking
from cs2lm.installer import PluginManager
from cs2lm.manifest import add_plugin, load_manifest

from conftest import init_repo, make_server


def make_metamod_pkg(tmp_path: Path, name: str, with_vdf: bool = True) -> Path:
    pkg = tmp_path / name
    (pkg / "addons" / name / "bin" / "linux64").mkdir(parents=True)
    (pkg / "addons" / name / "bin" / "linux64" / f"{name}.so").write_bytes(b"ELF")
    if with_vdf:
        (pkg / "addons" / "metamod").mkdir(parents=True)
        (pkg / "addons" / "metamod" / f"{name}.vdf").write_text(
            f'"Plugin" {{ "file" "addons/{name}/bin/linux64/{name}.so" }}'
        )
    return pkg


def test_metamod_plugin_with_vdf(tmp_path):
    server = make_server(tmp_path)
    repo = init_repo(tmp_path, server=server)
    pkg = make_metamod_pkg(tmp_path, "mmtest", with_vdf=True)

    manifest = add_plugin(repo, "mmtest", pkg)
    assert manifest["plugin_type"] == "metamod"
    assert manifest["ini_lines"] == []
    assert any(l["kind"] == "copy" for l in manifest["links"])
    assert any(l["target"] == "game/csgo/addons/mmtest" for l in manifest["links"])

    manager = PluginManager(repo)
    manager.install("mmtest")
    assert linking.path_exists(server / "game" / "csgo" / "addons" / "mmtest")
    assert (server / "game" / "csgo" / "addons" / "metamod" / "mmtest.vdf").exists()

    manager.uninstall("mmtest")
    assert not linking.path_exists(server / "game" / "csgo" / "addons" / "mmtest")
    assert (repo / "plugins" / "mmtest" / "files" / "addons" / "mmtest" / "bin" / "linux64" / "mmtest.so").exists()


def test_metamod_plugin_without_vdf_manages_ini(tmp_path):
    server = make_server(tmp_path)
    repo = init_repo(tmp_path, server=server)
    pkg = make_metamod_pkg(tmp_path, "mmodd", with_vdf=False)

    manifest = add_plugin(repo, "mmodd", pkg)
    assert manifest["ini_lines"] == ["addons/mmodd"]

    ini_path = server / "game" / "csgo" / "addons" / "metamod" / "metaplugins.ini"
    manager = PluginManager(repo)
    manager.install("mmodd")
    assert ini_path.exists()
    assert "addons/mmodd" in ini_path.read_text(encoding="utf-8")

    manager.uninstall("mmodd")
    assert "addons/mmodd" not in ini_path.read_text(encoding="utf-8")
    assert not linking.path_exists(server / "game" / "csgo" / "addons" / "mmodd")