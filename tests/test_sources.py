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

from cs2lm.config import load_config
from cs2lm.sources import (
    SourceError,
    add_source,
    fetch_and_merge,
    fetch_index,
    get_sources,
    list_sources,
    merge_sources,
    remove_source,
)


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


# ---------------------------------------------------------------------------
# Merge semantics
# ---------------------------------------------------------------------------


def test_merge_highest_version_wins():
    results = [
        make_source_result(
            "s1",
            {"hello": {"version": "1.2.3", "download_url": "u1"},
             "bar": {"version": "1.0.0", "download_url": "u1bar"}},
        ),
        make_source_result(
            "s2",
            {"hello": {"version": "1.1.0", "download_url": "u2"},
             "bar": {"version": "1.5.0", "download_url": "u2bar"}},
        ),
        make_source_result(
            "s3",
            {"bar": {"version": "1.2.0", "download_url": "u3bar"}},
        ),
    ]
    merged = merge_sources(results)
    assert merged["hello"]["version"] == "1.2.3"
    assert merged["hello"]["source"] == "s1"
    assert merged["bar"]["version"] == "1.5.0"
    assert merged["bar"]["source"] == "s2"


def test_merge_same_version_earlier_source_wins():
    results = [
        make_source_result("s1", {"foo": {"version": "2.0.0", "download_url": "u1"}}),
        make_source_result("s2", {"foo": {"version": "2.0.0", "download_url": "u2"}}),
    ]
    merged = merge_sources(results)
    assert merged["foo"]["version"] == "2.0.0"
    assert merged["foo"]["source"] == "s1"


def test_merge_failed_source_is_skipped():
    results = [
        {"url": "s1", "index": None, "error": "boom"},
        make_source_result("s2", {"world": {"version": "0.4.1", "download_url": "u"}}),
    ]
    merged = merge_sources(results)
    assert merged["world"]["version"] == "0.4.1"
    assert "hello" not in merged


def test_merge_missing_version_skipped():
    results = [make_source_result("s1", {"bad": {"download_url": "u"}})]
    assert merge_sources(results) == {}


def test_merge_id_mismatch_uses_key():
    results = [make_source_result("s1", {"my-plugin": {"id": "Other", "version": "1.0.0"}})]
    merged = merge_sources(results)
    assert "my-plugin" in merged
    assert merged["my-plugin"]["id"] == "my-plugin"


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
    index_path = write_index(tmp_path / "index.json", {"p": {"version": "1.0.0"}})
    merged, results = fetch_and_merge(repo, [{"url": index_path.as_uri()}], timeout=5)
    assert "p" in merged

    # Point the source at an unreachable URL; the cached merged table is used.
    merged2, results2 = fetch_and_merge(
        repo, [{"url": "http://127.0.0.1:1/index.json"}], timeout=2
    )
    assert "p" in merged2
    assert results2[0]["error"]