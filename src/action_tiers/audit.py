"""Append-only audit log. One JSON line per decision, hash-chained.

Each record carries the hash of the record before it. Change, delete or
reorder any line and `verify` reports the first line that no longer fits.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

GENESIS = "0" * 64


def _digest(record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq, self._last_hash = 0, GENESIS
        for record in read(self.path):
            self._seq, self._last_hash = record["seq"], record["hash"]

    def append(self, entry: dict) -> dict:
        record = {"seq": self._seq + 1, "prev_hash": self._last_hash, **entry}
        record["hash"] = _digest(record)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        self._seq, self._last_hash = record["seq"], record["hash"]
        return record


def read(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def verify(path: str | Path) -> tuple[bool, int | None]:
    """Return (True, None) if the chain is intact, else (False, bad_line_number)."""
    prev = GENESIS
    for line_no, record in enumerate(read(path), start=1):
        if record.get("seq") != line_no or record.get("prev_hash") != prev:
            return False, line_no
        if record.get("hash") != _digest(record):
            return False, line_no
        prev = record["hash"]
    return True, None
