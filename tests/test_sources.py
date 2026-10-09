"""Tests for index-based plugin sources: merge, cache, config."""
from __future__ import annotations

import functools
import http.server
import json
import socketserver
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

from cs2lm import cli
from cs2lm.config import DEFAULT_SOURCES, default_config, load_config, save_config
from cs2lm.sources import (
    SourceError,
    add_source,
    fetch_and_merge,
    fetch_index,
    get_sources,
    list_sources,
    merge_sources,
    normalize_source_url,
    remove_source,
)

FAKE_SHA256 = "0" * 64


def write_index(path: Path, plugins: dict, schema: int = 1) -> Path:
    path.write_text(
        json.dumps({"schema": schema, "name": "test", "plugins": plugins}),
        encoding="utf-8",
    )
    return path


def make_source_result(url: str, plugins: dict) -> dict:
    return {"url": url, "index": {"schema": 1, "plugins": plugins}, "error": None}


# ---------------------------------------------------------------------------
# Config management
# ---------------------------------------------------------------------------


def test_add_remove_list_sources(repo_server):
    repo, _server = repo_server
    add_source(repo, "https://a.example/index.json", headers={"X-Token": "abc"}, name="a")
    add_source(repo, "https://b.example/index.json")
    sources = list_sources(repo)
    assert len(sources) == 2
    assert sources[0]["url"] == "https://a.example/index.json"
    assert sources[0]["headers"] == {"X-Token": "abc"}
    assert sources[0]["name"] == "a"
    assert sources[1]["url"] == "https://b.example/index.json"

    cfg = load_config(repo)
    assert get_sources(cfg) == sources

    remove_source(repo, "https://a.example/index.json")
    assert [s["url"] for s in list_sources(repo)] == ["https://b.example/index.json"]
    with pytest.raises(ValueError, match="not configured"):
        remove_source(repo, "https://a.example/index.json")


def test_init_has_default_source(tmp_path, repo_server):
    """cli init embeds the default source; source clear removes it for good."""
    _repo, _server = repo_server
    repo = tmp_path / "real-init"
    server = tmp_path / "server"
    for d in ("plugins", "profiles", "state"):
        (repo / d).mkdir(parents=True, exist_ok=True)
    assert cli.main(
        ["--repo", str(repo), "init", "--server", str(server)]
    ) == 0
    sources = list_sources(repo)
    assert [s["url"] for s in sources] == [DEFAULT_SOURCES[0]["url"]]

    # Users can remove the default source like any other.
    assert cli.main(["--repo", str(repo), "source", "remove", DEFAULT_SOURCES[0]["url"]]) == 0
    assert list_sources(repo) == []


def test_source_clear_removes_default_and_not_readded(tmp_path):
    """source clear empties the list; the default is NOT re-injected on load."""
    repo = tmp_path / "clear-repo"
    for d in ("plugins", "profiles", "state"):
        (repo / d).mkdir(parents=True, exist_ok=True)
    assert cli.main(
        ["--repo", str(repo), "init", "--server", str(tmp_path / "srv")]
    ) == 0
    assert [s["url"] for s in list_sources(repo)] == [DEFAULT_SOURCES[0]["url"]]
    assert cli.main(["--repo", str(repo), "source", "clear"]) == 0
    assert list_sources(repo) == []
    # Loading the config again must not re-add the default source.
    cfg = load_config(repo)
    assert get_sources(cfg) == []
    assert cfg.get("default_sources_applied") is True


def test_migration_adds_default_to_old_empty_repo(tmp_path):
    """A pre-default repo with no sources gets the default source once."""
    from conftest import init_repo

    repo = init_repo(tmp_path, repo_name="old-empty")
    # Simulate an old config: no sources, no marker.
    cfg = load_config(repo)
    cfg["sources"] = []
    cfg.pop("default_sources_applied", None)
    save_config(repo, cfg)

    cfg2 = load_config(repo)
    assert [s["url"] for s in get_sources(cfg2)] == [DEFAULT_SOURCES[0]["url"]]
    assert cfg2.get("default_sources_applied") is True


def test_migration_preserves_custom_sources(tmp_path):
    """A repo with custom sources keeps them; the default is not injected."""
    from conftest import init_repo

    repo = init_repo(tmp_path, repo_name="old-custom")
    cfg = load_config(repo)
    cfg["sources"] = [{"url": "https://custom.example/index.json"}]
    cfg.pop("default_sources_applied", None)
    save_config(repo, cfg)

    cfg2 = load_config(repo)
    assert [s["url"] for s in get_sources(cfg2)] == [
        "https://custom.example/index.json"
    ]
    assert cfg2.get("default_sources_applied") is True


def test_normalize_source_url():
    assert normalize_source_url("https://github.com/cyqmq/cs2pkg-port") == (
        "https://raw.githubusercontent.com/cyqmq/cs2pkg-port/main/index.json"
    )
    assert normalize_source_url("https://github.com/cyqmq/cs2pkg-port.git") == (
        "https://raw.githubusercontent.com/cyqmq/cs2pkg-port/main/index.json"
    )
    assert normalize_source_url(
        "https://github.com/cyqmq/cs2pkg-port/tree/dev"
    ) == "https://raw.githubusercontent.com/cyqmq/cs2pkg-port/dev/index.json"
    assert normalize_source_url("https://example.com/index.json") == (
        "https://example.com/index.json"
    )


def test_add_remove_source_dedup_by_normalized_url(repo_server):
    """GitHub page, .git suffix and raw index URL are the same source."""
    repo, _server = repo_server
    add_source(repo, "https://github.com/owner/repo")
    with pytest.raises(ValueError, match="already configured"):
        add_source(repo, "https://github.com/owner/repo.git")
    with pytest.raises(ValueError, match="already configured"):
        add_source(
            repo, "https://raw.githubusercontent.com/owner/repo/main/index.json"
        )
    assert [s["url"] for s in list_sources(repo)] == [
        "https://github.com/owner/repo"
    ]

    # Removal also matches across the normalized forms.
    remove_source(repo, "https://github.com/owner/repo.git")
    assert list_sources(repo) == []


# ---------------------------------------------------------------------------
# Merge semantics
# ---------------------------------------------------------------------------


def test_merge_highest_version_wins():
    results = [
        make_source_result(
            "s1",
            {"hello": {"version": "1.2.3", "download_url": "u1", "sha256": FAKE_SHA256},
             "bar": {"version": "1.0.0", "download_url": "u1bar", "sha256": FAKE_SHA256}},
        ),
        make_source_result(
            "s2",
            {"hello": {"version": "1.1.0", "download_url": "u2", "sha256": FAKE_SHA256},
             "bar": {"version": "1.5.0", "download_url": "u2bar", "sha256": FAKE_SHA256}},
        ),
        make_source_result(
            "s3",
            {"bar": {"version": "1.2.0", "download_url": "u3bar", "sha256": FAKE_SHA256}},
        ),
    ]
    merged = merge_sources(results)
    assert merged["hello"]["version"] == "1.2.3"
    assert merged["hello"]["source"] == "s1"
    assert merged["bar"]["version"] == "1.5.0"
    assert merged["bar"]["source"] == "s2"


def test_merge_same_version_earlier_source_wins():
    results = [
        make_source_result("s1", {"foo": {"version": "2.0.0", "download_url": "u1", "sha256": FAKE_SHA256}}),
        make_source_result("s2", {"foo": {"version": "2.0.0", "download_url": "u2", "sha256": FAKE_SHA256}}),
    ]
    merged = merge_sources(results)
    assert merged["foo"]["version"] == "2.0.0"
    assert merged["foo"]["source"] == "s1"


def test_merge_failed_source_is_skipped():
    results = [
        {"url": "s1", "index": None, "error": "boom"},
        make_source_result("s2", {"world": {"version": "0.4.1", "download_url": "u", "sha256": FAKE_SHA256}}),
    ]
    merged = merge_sources(results)
    assert merged["world"]["version"] == "0.4.1"
    assert "hello" not in merged


def test_merge_missing_version_skipped():
    results = [make_source_result("s1", {"bad": {"download_url": "u"}})]
    assert merge_sources(results) == {}


def test_merge_id_mismatch_uses_key():
    results = [make_source_result("s1", {"my-plugin": {"id": "Other", "version": "1.0.0", "sha256": FAKE_SHA256}})]
    merged = merge_sources(results)
    assert "my-plugin" in merged
    assert merged["my-plugin"]["id"] == "my-plugin"


def test_merge_skips_missing_sha256():
    results = [
        make_source_result("s1", {"ok": {"version": "1.0.0", "download_url": "u", "sha256": FAKE_SHA256},
                                     "no-hash": {"version": "1.0.0", "download_url": "u2"}}),
    ]
    merged = merge_sources(results)
    assert "ok" in merged
    assert "no-hash" not in merged
    assert results[0]["warnings"]


def test_merge_skips_yanked():
    results = [
        make_source_result(
            "s1",
            {"foo": {"version": "2.0.0", "download_url": "u", "sha256": FAKE_SHA256, "yanked": True},
             "bar": {"version": "2.0.0", "download_url": "u", "sha256": FAKE_SHA256}},
        ),
    ]
    merged = merge_sources(results)
    assert "bar" in merged
    assert "foo" not in merged


def test_merge_api_version_range():
    results = [
        make_source_result(
            "s1",
            {"old": {"version": "1.0.0", "download_url": "u", "sha256": FAKE_SHA256, "api_version": 1},
             "new": {"version": "2.0.0", "download_url": "u", "sha256": FAKE_SHA256, "api_version": 3}},
        ),
    ]
    merged = merge_sources(results, api_version_range=(1, 2))
    assert "old" in merged
    assert "new" not in merged


def test_merge_skips_non_semver():
    results = [
        make_source_result(
            "s1",
            {"latest": {"version": "latest", "download_url": "u", "sha256": FAKE_SHA256},
             "ok": {"version": "1.0.0", "download_url": "u", "sha256": FAKE_SHA256}},
        ),
    ]
    merged = merge_sources(results)
    assert "ok" in merged
    assert "latest" not in merged
    assert results[0]["warnings"]


def test_merge_resolves_relative_download_url():
    results = [
        {"url": "https://example.com/plugins/index.json",
         "index": {"schema": 1, "plugins": {
             "rel": {"version": "1.0.0", "download_url": "../releases/foo.zip", "sha256": FAKE_SHA256}
         }}},
    ]
    merged = merge_sources(results)
    assert merged["rel"]["download_url"] == "https://example.com/releases/foo.zip"


# ---------------------------------------------------------------------------
# Fetching & schema validation
# ---------------------------------------------------------------------------


def test_fetch_index_file_url(repo_server, tmp_path):
    repo, _server = repo_server
    index_path = write_index(tmp_path / "index.json", {"p": {"version": "1.0.0"}})
    index = fetch_index(repo, {"url": index_path.as_uri()})
    assert index["plugins"]["p"]["version"] == "1.0.0"


def test_fetch_index_rejects_bad_schema(repo_server, tmp_path):
    repo, _server = repo_server
    index_path = write_index(tmp_path / "index.json", {"p": {}}, schema=99)
    with pytest.raises(SourceError, match="unsupported index schema 99"):
        fetch_index(repo, {"url": index_path.as_uri()})


def test_fetch_index_requires_schema(repo_server, tmp_path):
    repo, _server = repo_server
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps({"plugins": {}}), encoding="utf-8")
    with pytest.raises(SourceError, match="schema"):
        fetch_index(repo, {"url": index_path.as_uri()})


class _EtagHandler(http.server.BaseHTTPRequestHandler):
    etag = '"v1"'
    body = json.dumps({"schema": 1, "plugins": {"p": {"version": "1.0.0"}}}).encode()

    def do_GET(self):  # noqa: N802
        if self.headers.get("If-None-Match") == self.etag:
            self.send_response(304)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("ETag", self.etag)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, format, *args):  # noqa: A002
        pass


@contextmanager
def serve_etag():
    handler = functools.partial(_EtagHandler)
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{port}"
        httpd.shutdown()


def test_fetch_index_etag_cache(repo_server):
    repo, _server = repo_server
    with serve_etag() as base_url:
        url = f"{base_url}/index.json"
        first = fetch_index(repo, {"url": url})
        assert first["plugins"]["p"]["version"] == "1.0.0"
        # Second fetch sends If-None-Match and gets 304 -> cached copy.
        second = fetch_index(repo, {"url": url})
        assert second == first


def test_fetch_and_merge_offline_cache(repo_server, tmp_path):
    repo, _server = repo_server
    index_path = write_index(
        tmp_path / "index.json",
        {"p": {"version": "1.0.0", "download_url": "u", "sha256": FAKE_SHA256}},
    )
    merged, results = fetch_and_merge(repo, [{"url": index_path.as_uri()}], timeout=5)
    assert "p" in merged

    # Point the source at an unreachable URL; the cached merged table is used.
    merged2, results2 = fetch_and_merge(
        repo, [{"url": "http://127.0.0.1:1/index.json"}], timeout=2
    )
    assert "p" in merged2
    assert results2[0]["error"]