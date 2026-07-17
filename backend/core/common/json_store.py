# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import Lock

_LOCKS: dict[str, Lock] = {}
_LOCKS_GUARD = Lock()


def _path_lock(path: Path) -> Lock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = Lock()
            _LOCKS[key] = lock
        return lock


def read_json(path: Path, default):
    if not path.exists() or path.stat().st_size == 0:
        return default
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return default


def write_json(path: Path, payload, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _path_lock(path)
    with lock:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=f".{path.stem}_",
            suffix=path.suffix or ".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(
                    payload,
                    file,
                    ensure_ascii=False,
                    indent=None if compact else 2,
                    separators=(",", ":") if compact else None,
                )
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
