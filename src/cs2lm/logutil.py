"""Logging utility supporting plain text and JSON output."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Logger:
    """Minimal logger that writes to stderr and an optional log file.

    Supports both human-readable text lines and JSON records.
    """

    def __init__(self, path: str | None = None, fmt: str = "text", verbose: bool = False):
        self.fmt = fmt if fmt in ("text", "json") else "text"
        self.verbose = verbose
        self._file = None
        if path:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._file = p.open("a", encoding="utf-8")

    def _emit(self, level: str, event: str, message: str, **fields: object) -> None:
        if self.fmt == "json":
            record = {
                "ts": _ts(),
                "level": level,
                "event": event,
                "message": message,
                **fields,
            }
            line = json.dumps(record, ensure_ascii=False, default=str)
        else:
            parts = [f"[{_ts()}]", f"[{level}]", message]
            if fields:
                parts.append(" ".join(f"{k}={v}" for k, v in fields.items()))
            line = " ".join(parts)
        if self.verbose or level in ("WARN", "ERROR", "ACTION"):
            print(line, file=sys.stderr)
        if self._file:
            self._file.write(line + "\n")
            self._file.flush()

    def info(self, event: str, message: str, **fields: object) -> None:
        self._emit("INFO", event, message, **fields)

    def warn(self, event: str, message: str, **fields: object) -> None:
        self._emit("WARN", event, message, **fields)

    def error(self, event: str, message: str, **fields: object) -> None:
        self._emit("ERROR", event, message, **fields)

    def action(self, message: str, **fields: object) -> None:
        self._emit("ACTION", "fs", message, **fields)

    def close(self) -> None:
        if self._file:
            self._file.close()