#!/usr/bin/env python3
"""Create atomic, secret-free daily backups of forward evidence and SQLite DBs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_INTERVAL_SECONDS = 86_400
DEFAULT_RETENTION_DAYS = 35
MINIMUM_BACKUPS_TO_KEEP = 2
BACKUP_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$")
DATABASE_NAMES = (
    "tradesv3.dual-futures-dryrun.sqlite",
    "tradesv3.dual-futures-v2r-dryrun.sqlite",
)
EVIDENCE_DIRECTORIES = (
    "reports",
    "dashboard",
    "data/binance/derivatives",
)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sqlite_online_backup(source: Path, destination: Path) -> str:
    if not source.is_file():
        raise FileNotFoundError(f"Required database is missing: {source}")
    source_uri = f"file:{source.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True, timeout=30.0)) as source_db:
        with closing(sqlite3.connect(destination, timeout=30.0)) as destination_db:
            source_db.backup(destination_db)
            result = destination_db.execute("PRAGMA integrity_check").fetchone()
    integrity = str(result[0]) if result else "missing-result"
    if integrity.lower() != "ok":
        raise RuntimeError(f"SQLite integrity_check failed for {source.name}: {integrity}")
    return integrity


def evidence_files(user_data_dir: Path) -> list[Path]:
    files: list[Path] = []
    for folder_name in EVIDENCE_DIRECTORIES:
        folder = user_data_dir / folder_name
        if not folder.exists():
            continue
        files.extend(
            path
            for path in folder.rglob("*")
            if path.is_file() and not path.name.endswith(".tmp")
        )
    return sorted(files)


def write_evidence_archive(user_data_dir: Path, destination: Path) -> int:
    files = evidence_files(user_data_dir)
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for source in files:
            archive.write(source, source.relative_to(user_data_dir).as_posix())
    return len(files)


def verify_backup_artifacts(backup_dir: Path) -> dict[str, Any]:
    """Verify that a completed backup is present, untampered, and restorable."""
    manifest_path = backup_dir / "manifest.json"
    if not backup_dir.is_dir() or not manifest_path.is_file():
        raise RuntimeError(f"Backup directory or manifest is missing: {backup_dir}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Backup manifest is unreadable: {backup_dir.name}") from exc
    records = manifest.get("artifacts")
    if not isinstance(records, list):
        raise RuntimeError(f"Backup manifest has no artifact list: {backup_dir.name}")

    expected = {*DATABASE_NAMES, "forward_evidence.zip"}
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError(f"Backup manifest has an invalid artifact record: {backup_dir.name}")
        relative = record.get("path")
        if not isinstance(relative, str) or Path(relative).name != relative:
            raise RuntimeError(f"Backup manifest has an unsafe artifact path: {backup_dir.name}")
        if relative in seen:
            raise RuntimeError(f"Backup manifest has a duplicate artifact: {relative}")
        seen.add(relative)
        artifact = backup_dir / relative
        if not artifact.is_file():
            raise RuntimeError(f"Backup artifact is missing: {relative}")
        if artifact.stat().st_size != record.get("bytes"):
            raise RuntimeError(f"Backup artifact size mismatch: {relative}")
        if sha256_file(artifact) != record.get("sha256"):
            raise RuntimeError(f"Backup artifact checksum mismatch: {relative}")

    missing = expected - seen
    if missing:
        raise RuntimeError(f"Backup is incomplete: {', '.join(sorted(missing))}")

    sqlite_integrity: dict[str, str] = {}
    for database_name in DATABASE_NAMES:
        database_path = backup_dir / database_name
        database_uri = f"file:{database_path.resolve().as_posix()}?mode=ro"
        with closing(sqlite3.connect(database_uri, uri=True, timeout=30.0)) as database:
            result = database.execute("PRAGMA integrity_check").fetchone()
        integrity = str(result[0]) if result else "missing-result"
        if integrity.lower() != "ok":
            raise RuntimeError(
                f"Backup SQLite integrity_check failed for {database_name}: {integrity}"
            )
        sqlite_integrity[database_name] = integrity

    with zipfile.ZipFile(backup_dir / "forward_evidence.zip") as archive:
        bad_member = archive.testzip()
    if bad_member is not None:
        raise RuntimeError(f"Backup evidence archive is corrupt: {bad_member}")
    return {
        "status": "PASS",
        "artifact_count": len(records),
        "sqlite_integrity_check": sqlite_integrity,
        "evidence_archive": "PASS",
    }


def run_restore_drill(backup_dir: Path) -> dict[str, Any]:
    """Restore a completed backup into a temporary directory and validate it."""
    verify_backup_artifacts(backup_dir)
    with tempfile.TemporaryDirectory(prefix="forward-backup-restore-") as temporary:
        restore_root = Path(temporary)
        sqlite_results: dict[str, str] = {}
        for database_name in DATABASE_NAMES:
            restored_database = restore_root / database_name
            shutil.copy2(backup_dir / database_name, restored_database)
            database_uri = f"file:{restored_database.resolve().as_posix()}?mode=ro"
            with closing(sqlite3.connect(database_uri, uri=True, timeout=30.0)) as database:
                result = database.execute("PRAGMA integrity_check").fetchone()
            integrity = str(result[0]) if result else "missing-result"
            if integrity.lower() != "ok":
                raise RuntimeError(
                    f"Restored SQLite integrity_check failed for {database_name}: {integrity}"
                )
            sqlite_results[database_name] = integrity

        evidence_root = restore_root / "evidence"
        evidence_root.mkdir()
        with zipfile.ZipFile(backup_dir / "forward_evidence.zip") as archive:
            for member in archive.infolist():
                member_path = Path(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise RuntimeError(f"Unsafe evidence archive member: {member.filename}")
            archive.extractall(evidence_root)
        restored_evidence = [path for path in evidence_root.rglob("*") if path.is_file()]
        forbidden = [
            path
            for path in restored_evidence
            if path.name == ".env" or path.name.startswith("config") and path.suffix == ".json"
        ]
        if forbidden:
            raise RuntimeError("Restore drill found excluded sensitive configuration files")
        manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
        expected_evidence_files = manifest.get("evidence_files_archived")
        if len(restored_evidence) != expected_evidence_files:
            raise RuntimeError("Restore drill evidence file count mismatch")
    return {
        "status": "PASS",
        "database_count": len(DATABASE_NAMES),
        "sqlite_integrity_check": sqlite_results,
        "evidence_files_restored": expected_evidence_files,
        "temporary_restore_removed": True,
    }


def verify_state_backup_reference(
    backup_root: Path, previous: dict[str, Any], last_success: datetime
) -> tuple[Path, dict[str, Any]]:
    directory_name = previous.get("last_backup_directory")
    if not isinstance(directory_name, str) or not BACKUP_NAME.fullmatch(directory_name):
        raise RuntimeError("Backup state has no safe completed directory reference")
    root = backup_root.resolve()
    backup_dir = (backup_root / directory_name).resolve()
    if backup_dir.parent != root:
        raise RuntimeError("Backup state directory escaped the configured backup root")
    verification = verify_backup_artifacts(backup_dir)
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest_time = parse_datetime(manifest.get("backup_utc"))
    if manifest_time != last_success:
        raise RuntimeError("Backup state timestamp does not match its manifest")
    return backup_dir, verification


def validated_backup_directories(backup_root: Path) -> list[tuple[datetime, Path]]:
    root = backup_root.resolve()
    candidates: list[tuple[datetime, Path]] = []
    if not root.exists():
        return candidates
    for child in root.iterdir():
        if not child.is_dir() or not BACKUP_NAME.fullmatch(child.name):
            continue
        resolved = child.resolve()
        if resolved.parent != root:
            continue
        manifest_path = child / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        backup_time = parse_datetime(manifest.get("backup_utc"))
        if backup_time is not None:
            candidates.append((backup_time, child))
    return sorted(candidates, key=lambda item: item[0])


def enforce_retention(
    backup_root: Path, now: datetime, retention_days: int
) -> list[str]:
    candidates = validated_backup_directories(backup_root)
    protected = {path.resolve() for _, path in candidates[-MINIMUM_BACKUPS_TO_KEEP:]}
    cutoff = now - timedelta(days=retention_days)
    removed: list[str] = []
    root = backup_root.resolve()
    for backup_time, path in candidates:
        resolved = path.resolve()
        if backup_time >= cutoff or resolved in protected:
            continue
        if resolved.parent != root or not BACKUP_NAME.fullmatch(resolved.name):
            raise RuntimeError(f"Refusing unsafe retention target: {resolved}")
        shutil.rmtree(resolved)
        removed.append(path.name)
    return removed


def run_backup_if_due(
    user_data_dir: Path,
    backup_root: Path,
    state_path: Path,
    now: datetime,
    *,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> dict[str, Any]:
    previous: dict[str, Any] = {}
    previous_backup_invalid: str | None = None
    if state_path.exists():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("backup state is not an object")
            previous = loaded
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            previous_backup_invalid = f"{type(exc).__name__}: {exc}"
    last_success = parse_datetime(previous.get("last_successful_backup_utc"))
    if last_success is not None:
        age_seconds = (now - last_success).total_seconds()
        if 0 <= age_seconds < interval_seconds:
            try:
                backup_dir, verification = verify_state_backup_reference(
                    backup_root, previous, last_success
                )
            except (OSError, RuntimeError, sqlite3.Error, zipfile.BadZipFile) as exc:
                previous_backup_invalid = f"{type(exc).__name__}: {exc}"
            else:
                return {
                    "status": "NOT_DUE",
                    "last_successful_backup_utc": iso_utc(last_success),
                    "backup_directory": str(backup_dir),
                    "age_seconds": age_seconds,
                    "next_due_utc": iso_utc(last_success + timedelta(seconds=interval_seconds)),
                    "retention_days": retention_days,
                    "verification": verification,
                }

    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp_name = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    final_dir = backup_root / timestamp_name
    staging_dir = backup_root / f".tmp-{timestamp_name}-{os.getpid()}"
    root = backup_root.resolve()
    if staging_dir.resolve().parent != root or final_dir.resolve().parent != root:
        raise RuntimeError("Backup target escaped the configured backup root")
    if final_dir.exists():
        verification = verify_backup_artifacts(final_dir)
        restore_test = run_restore_drill(final_dir)
        state = {
            "schema_version": "1.0",
            "last_successful_backup_utc": iso_utc(now),
            "last_backup_directory": final_dir.name,
            "interval_seconds": interval_seconds,
            "retention_days": retention_days,
        }
        atomic_write_json(state_path, state)
        return {
            "status": "RECOVERED_EXISTING",
            "last_successful_backup_utc": iso_utc(now),
            "backup_directory": str(final_dir),
            "age_seconds": 0.0,
            "next_due_utc": iso_utc(now + timedelta(seconds=interval_seconds)),
            "retention_days": retention_days,
            "verification": verification,
            "restore_test": restore_test,
        }
    staging_dir.mkdir(parents=False, exist_ok=False)
    try:
        artifact_records: list[dict[str, Any]] = []
        database_integrity: dict[str, str] = {}
        for database_name in DATABASE_NAMES:
            source = user_data_dir / database_name
            destination = staging_dir / database_name
            database_integrity[database_name] = sqlite_online_backup(source, destination)
            artifact_records.append(
                {
                    "path": destination.name,
                    "bytes": destination.stat().st_size,
                    "sha256": sha256_file(destination),
                }
            )
        evidence_archive = staging_dir / "forward_evidence.zip"
        archived_files = write_evidence_archive(user_data_dir, evidence_archive)
        artifact_records.append(
            {
                "path": evidence_archive.name,
                "bytes": evidence_archive.stat().st_size,
                "sha256": sha256_file(evidence_archive),
            }
        )
        manifest = {
            "schema_version": "1.0",
            "backup_utc": iso_utc(now),
            "source_scope": [
                f"user_data/{name}" for name in DATABASE_NAMES
            ]
            + [f"user_data/{name}/**" for name in EVIDENCE_DIRECTORIES],
            "excluded_sensitive_scope": [
                "user_data/config*.json",
                ".env",
                "API credentials",
                "webhook URL",
            ],
            "sqlite_integrity_check": database_integrity,
            "evidence_files_archived": archived_files,
            "artifacts": artifact_records,
        }
        atomic_write_json(staging_dir / "manifest.json", manifest)
        verification = verify_backup_artifacts(staging_dir)
        staging_dir.replace(final_dir)
        restore_test = run_restore_drill(final_dir)
    except Exception:
        if staging_dir.exists() and staging_dir.resolve().parent == root:
            shutil.rmtree(staging_dir)
        raise

    removed = enforce_retention(backup_root, now, retention_days)
    state = {
        "schema_version": "1.0",
        "last_successful_backup_utc": iso_utc(now),
        "last_backup_directory": final_dir.name,
        "interval_seconds": interval_seconds,
        "retention_days": retention_days,
    }
    atomic_write_json(state_path, state)
    return {
        "status": "CREATED",
        "last_successful_backup_utc": iso_utc(now),
        "backup_directory": str(final_dir),
        "database_count": len(DATABASE_NAMES),
        "evidence_files_archived": archived_files,
        "retention_days": retention_days,
        "removed_by_retention": removed,
        "next_due_utc": iso_utc(now + timedelta(seconds=interval_seconds)),
        "verification": verification,
        "restore_test": restore_test,
        "previous_backup_invalid": previous_backup_invalid is not None,
        "previous_backup_invalid_reason": previous_backup_invalid,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-data-dir", default="user_data")
    parser.add_argument("--backup-dir", default="user_data/backups")
    parser.add_argument(
        "--state", default="user_data/reports/forward_backup_state.json"
    )
    parser.add_argument(
        "--status-output",
        help="Optional JSON status file for a manual backup/verification run.",
    )
    parser.add_argument(
        "--restore-test",
        action="store_true",
        help="Run a temporary restore drill even when the backup is not due.",
    )
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    args = parser.parse_args()
    if args.interval_seconds <= 0 or args.retention_days <= 0:
        raise SystemExit("Backup interval and retention must be positive")
    result = run_backup_if_due(
        Path(args.user_data_dir),
        Path(args.backup_dir),
        Path(args.state),
        datetime.now(timezone.utc),
        interval_seconds=args.interval_seconds,
        retention_days=args.retention_days,
    )
    if args.restore_test and "restore_test" not in result:
        backup_directory = result.get("backup_directory")
        if not isinstance(backup_directory, str):
            raise RuntimeError("Backup result has no directory for the restore drill")
        result["restore_test"] = run_restore_drill(Path(backup_directory))
    if args.status_output:
        atomic_write_json(Path(args.status_output), result)
    print(json.dumps(result, separators=(",", ":"), allow_nan=False))
    return 0 if result["status"] != "ERROR" else 2


if __name__ == "__main__":
    raise SystemExit(main())
