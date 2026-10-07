"""Cross-platform daemonization for the web UI.

``cs2lm web --daemon --pidfile ...`` spawns a detached background process and
writes its PID to a file. Wrapper scripts (panel launchers, systemd units,
PowerShell start scripts) then only need one command instead of reimplementing
``nohup``/``Start-Process`` and PID tracking per platform.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import cs2lm


def start_daemon(
    repo: str | Path,
    host: str,
    port: int,
    auth_token: str | None = None,
    pidfile: str | Path | None = None,
    logfile: str | Path | None = None,
) -> int:
    """Spawn the web UI as a detached background process.

    Returns the PID of the spawned process. The child is the same
    ``python -m cs2lm web`` command without ``--daemon``, so it runs the
    normal foreground server loop.
    """
    cmd = [
        sys.executable,
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
    if logfile:
        log_handle.close()  # type: ignore[union-attr]

    if pidfile:
        Path(pidfile).write_text(str(proc.pid), encoding="utf-8")
    return proc.pid