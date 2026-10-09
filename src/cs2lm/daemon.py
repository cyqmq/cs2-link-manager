"""Cross-platform daemonization for the web UI.

``cs2lm web --daemon --pidfile ...`` spawns a detached background process and
writes its PID to a file. Wrapper scripts (panel launchers, systemd units,
PowerShell start scripts) then only need one command instead of reimplementing
``nohup``/``Start-Process`` and PID tracking per platform.

The parent process waits until the child is actually listening (probed via
``/api/health`` or the ``CS2LM_READY port=...`` line in the log file) before
reporting success, so a failed bind (port already in use) surfaces immediately
instead of printing "Started web UI daemon" while the child is already dead.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import cs2lm

_READY_TIMEOUT = 5.0
_POLL_INTERVAL = 0.2


class DaemonError(Exception):
    """Raised when the daemonized web UI fails to start."""


def _probe_ready(
    host: str,
    port: int,
    auth_token: str | None,
) -> bool:
    """Return ``True`` when the child web UI answers ``/api/health``."""
    check_host = "127.0.0.1" if host in ("0.0.0.0", "::", "::0") else host
    url = f"http://{check_host}:{port}/api/health"
    headers = {}
    if auth_token:
        headers["X-Auth-Token"] = auth_token
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=0.5) as resp:
            return resp.status == 200
    except (OSError, urllib.error.HTTPError, ValueError):
        return False


def _log_ready_port(logfile: str | Path) -> int | None:
    """Parse ``CS2LM_READY port=<n>`` from the daemon log file."""
    path = Path(logfile)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r"CS2LM_READY port=(\d+)", text)
    return int(match.group(1)) if match else None


def start_daemon(
    repo: str | Path,
    host: str,
    port: int,
    auth_token: str | None = None,
    pidfile: str | Path | None = None,
    logfile: str | Path | None = None,
) -> int:
    """Spawn the web UI as a detached background process.

    Returns the PID of the spawned process after confirming it is listening.
    Raises :class:`DaemonError` when the child exits or never becomes ready.
    """
    if not 0 <= port <= 65535:
        raise DaemonError(f"Invalid port: {port}. Port must be between 0 and 65535.")
    if port == 0 and not logfile:
        raise DaemonError(
            "--port 0 with --daemon requires --daemon-log so the actual "
            "listening port can be reported."
        )

    # `-u` keeps stdout unbuffered so the CS2LM_READY line is flushed to the
    # log file immediately, not when the child process exits.
    cmd = [
        sys.executable,
        "-u",
        "-m",
        "cs2lm",
        "--repo",
        str(Path(repo).resolve()),
        "web",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if auth_token:
        cmd += ["--auth-token", auth_token]

    # Make the child able to import cs2lm even when running from a source
    # checkout (not pip-installed). In installed environments this is a no-op.
    env = os.environ.copy()
    pkg_parent = str(Path(cs2lm.__file__).resolve().parent.parent)
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = pkg_parent + os.pathsep + existing_pythonpath

    stdin = subprocess.DEVNULL
    log_handle = None
    if logfile:
        log_path = Path(logfile)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(log_path, "a", encoding="utf-8")
        stdout: object = log_handle
        stderr: object = log_handle
    else:
        stdout = subprocess.DEVNULL
        stderr = subprocess.DEVNULL

    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
        kwargs["close_fds"] = True
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(
        cmd,
        stdin=stdin,
        stdout=stdout,  # type: ignore[arg-type]
        stderr=stderr,  # type: ignore[arg-type]
        env=env,
        **kwargs,
    )
    if log_handle is not None:
        log_handle.close()  # type: ignore[union-attr]

    # Wait until the child is genuinely listening (or has died).
    deadline = time.monotonic() + _READY_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise DaemonError(
                f"web UI daemon exited immediately (code {proc.returncode}). "
                "Check --daemon-log for details; the port may already be in use."
            )
        ready = False
        if port != 0:
            ready = _probe_ready(host, port, auth_token)
        elif logfile:
            actual_port = _log_ready_port(logfile)
            if actual_port is not None:
                ready = _probe_ready(host, actual_port, auth_token)
        if ready:
            if pidfile:
                Path(pidfile).write_text(str(proc.pid), encoding="utf-8")
            return proc.pid
        time.sleep(_POLL_INTERVAL)

    raise DaemonError(
        f"web UI daemon (pid {proc.pid}) did not become ready within "
        f"{_READY_TIMEOUT:.0f}s. Check --daemon-log for details."
    )