#!/usr/bin/env python3
"""Consistent hashed backups for the isolated Profit-Max V5 SQLite database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path


NAME = re.compile(r"^profit-max-v5-(\d{8}T\d{6}Z)\.sqlite$")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def integrity(path: Path) -> str:
    with closing(sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=30)) as connection:
        result = connection.execute("pragma integrity_check").fetchone()
    return str(result[0]) if result else "missing"


def atomic_json(path: Path, payload: dict) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def create_backup(database: Path, output_dir: Path, retention_days: int, *, now: datetime | None = None) -> dict:
    current = (now or now_utc()).astimezone(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"profit-max-v5-{current.strftime('%Y%m%dT%H%M%SZ')}.sqlite"
    destination = output_dir / filename
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite backup: {filename}")
    fd, temporary_name = tempfile.mkstemp(prefix=".backup-", suffix=".sqlite", dir=output_dir)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with closing(sqlite3.connect(database.resolve(), timeout=30)) as source:
            source.execute("pragma query_only = on")
            with closing(sqlite3.connect(temporary, timeout=30)) as target:
                source.backup(target)
        if integrity(temporary).lower() != "ok":
            raise RuntimeError("backup integrity_check failed")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    record = {
        "schema_version": "1.0", "created_at_utc": current.isoformat().replace("+00:00", "Z"),
        "database": filename, "bytes": destination.stat().st_size, "sha256": sha256(destination),
        "integrity_check": "ok", "live_trading_authorized": False,
    }
    atomic_json(output_dir / "latest.json", record)
    cutoff = current - timedelta(days=retention_days)
    candidates = []
    for path in output_dir.glob("profit-max-v5-*.sqlite"):
        match = NAME.fullmatch(path.name)
        if match:
            candidates.append((datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc), path))
    candidates.sort()
    protected = {path.resolve() for _, path in candidates[-2:]}
    removed = []
    root = output_dir.resolve()
    for timestamp, path in candidates:
        resolved = path.resolve()
        if timestamp >= cutoff or resolved in protected:
            continue
        if resolved.parent != root or not NAME.fullmatch(resolved.name):
            raise RuntimeError("unsafe backup retention target")
        path.unlink(); removed.append(path.name)
    record["removed_by_retention"] = removed
    return record


def healthcheck(output_dir: Path, max_age_seconds: float, *, now: datetime | None = None) -> bool:
    try:
        record = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))
        path = output_dir / record["database"]
        created = datetime.fromisoformat(record["created_at_utc"].replace("Z", "+00:00"))
        age = ((now or now_utc()).astimezone(timezone.utc) - created).total_seconds()
        return (
            0 <= age <= max_age_seconds and path.is_file() and NAME.fullmatch(path.name) is not None
            and path.stat().st_size == record["bytes"] and sha256(path) == record["sha256"]
            and integrity(path).lower() == "ok" and record.get("live_trading_authorized") is False
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, sqlite3.Error):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--retention-days", type=int, default=35)
    parser.add_argument("--loop-seconds", type=int, default=0)
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--health-max-age-seconds", type=float, default=90000)
    args = parser.parse_args()
    if args.healthcheck:
        return 0 if healthcheck(args.output_dir, args.health_max_age_seconds) else 1
    if args.database is None or args.retention_days <= 0:
        parser.error("a database and positive retention are required")
    while True:
        create_backup(args.database, args.output_dir, args.retention_days)
        if args.loop_seconds <= 0:
            return 0
        time.sleep(args.loop_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
