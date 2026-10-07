import pytest

from cs2lm import profiles
from cs2lm.installer import PluginManager
from cs2lm.manifest import add_plugin, load_manifest

from conftest import make_css_package


def add_two_plugins(repo, tmp_path):
    add_plugin(repo, "Alpha", make_css_package(tmp_path, "Alpha"))
    add_plugin(repo, "Beta", make_css_package(tmp_path, "Beta"))
    return "Alpha", "Beta"


def test_profile_create_list(repo_server, tmp_path):
    repo, _server = repo_server
    add_two_plugins(repo, tmp_path)
    profiles.create_profile(repo, "competitive", ["Alpha"])
    assert profiles.list_profiles(repo) == ["competitive"]
    profile = profiles.get_profile(repo, "competitive")
    assert profile["plugins"] == ["Alpha"]


def test_profile_create_unknown_plugin(repo_server, tmp_path):
    repo, _server = repo_server
    add_two_plugins(repo, tmp_path)
    with pytest.raises(ValueError, match="Unknown plugin"):
        profiles.create_profile(repo, "bad", ["Nope"])


def test_profile_use_switches_enabled_set(repo_server, tmp_path):
    repo, _server = repo_server
    alpha, beta = add_two_plugins(repo, tmp_path)
    profiles.create_profile(repo, "a", [alpha])
    profiles.create_profile(repo, "b", [beta])

    manager = PluginManager(repo)
    profiles.use_profile(repo, "a", manager)
    assert load_manifest(repo, alpha)["enabled"] is True
    assert load_manifest(repo, beta)["enabled"] is False

    manager = PluginManager(repo)
    profiles.use_profile(repo, "b", manager)
    assert load_manifest(repo, alpha)["enabled"] is False
    assert load_manifest(repo, beta)["enabled"] is True


def test_profile_use_empty_profile_disables_all(repo_server, tmp_path):
    repo, _server = repo_server
    alpha, beta = add_two_plugins(repo, tmp_path)
    profiles.create_profile(repo, "empty", [])
    manager = PluginManager(repo)
    manager.install(alpha)
    manager.install(beta)
    profiles.use_profile(repo, "empty", manager)
    assert load_manifest(repo, alpha)["enabled"] is False
    assert load_manifest(repo, beta)["enabled"] is False


def test_profile_use_returns_diff_lists(repo_server, tmp_path):
    repo, _server = repo_server
    alpha, beta = add_two_plugins(repo, tmp_path)
    profiles.create_profile(repo, "a", [alpha])
    profiles.create_profile(repo, "b", [beta])

    manager = PluginManager(repo)
    profiles.use_profile(repo, "a", manager)
    manager = PluginManager(repo)
    result = profiles.use_profile(repo, "b", manager)
    assert result["enabled"] == [beta]
    assert result["disabled"] == [alpha]