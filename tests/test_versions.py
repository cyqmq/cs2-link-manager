"""Tests for the lightweight semantic version comparison."""
from cs2lm.versions import (
    parse_version,
    version_eq,
    version_gt,
    version_gte,
    version_lt,
    version_satisfies,
)


def test_numeric_ordering():
    assert version_gt("1.2.3", "1.2.2")
    assert version_gt("1.10.0", "1.9.0")
    assert version_gt("2.0.0", "1.9.9")
    assert version_lt("1.0.0", "1.0.1")
    assert version_eq("1.2.3", "1.2.3")


def test_missing_parts_compare_as_zero():
    assert version_eq("1.2", "1.2.0")
    assert version_gt("1.2.1", "1.2")
    assert version_gt("1.2", "1.2.0-alpha")


def test_release_beats_prerelease():
    assert version_gt("1.0.0", "1.0.0-beta")
    assert version_gt("1.0.0-beta", "1.0.0-alpha")
    assert version_lt("1.0.0-rc.1", "1.0.0")


def test_build_metadata_ignored():
    assert version_eq("1.0.0+build5", "1.0.0")
    assert version_gt("1.0.0+build5", "1.0.0-beta")


def test_parse_version_shape():
    assert parse_version("1.2.3-beta.1")[0] == (1, 1, "")
    assert parse_version("1.2.3-beta.1")[1] == (2, 1, "")
    assert parse_version("1.2.3-beta.1")[2] == (3, 0, "beta.1")


def test_version_satisfies():
    assert version_satisfies("1.2.3", "1.2.3")
    assert version_satisfies("1.2.3", ">=1.2.0")
    assert version_satisfies("1.2.3", ">1.2.0")
    assert version_satisfies("1.2.3", "<=1.3.0")
    assert version_satisfies("1.2.3", "<1.3.0")
    assert version_satisfies("1.2.3", "=1.2.3")
    assert not version_satisfies("1.1.0", ">=1.2.0")
    assert version_satisfies("1.5.0", "1.0.0 - 2.0.0")
    assert not version_satisfies("2.5.0", "1.0.0 - 2.0.0")
    assert version_satisfies("1.2.3", ">=1.0.0, <2.0.0")
    assert version_gte("1.2.3", "1.2.3")