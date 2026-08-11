#!/usr/bin/env python3
"""Redact secrets from Freqtrade backtest ZIP config snapshots in place."""

from __future__ import annotations

import argparse
import json
import os
import zipfile
from pathlib import Path
from typing import Any


SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "jwt_secret_key",
    "key",
    "password",
    "secret",
    "secret_key",
    "token",
    "ws_token",
}
REDACTION = "REDACTED"


class SanitizeError(RuntimeError):
    pass


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTION if key.lower() in SENSITIVE_KEYS and item not in (None, "") else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def assert_redacted(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if key.lower() in SENSITIVE_KEYS and item not in (None, "", REDACTION):
                raise SanitizeError(f"Sensitive value remains at {child}")
            assert_redacted(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_redacted(item, f"{path}[{index}]")


def sanitize_archive(path: Path) -> dict[str, int | str]:
    if not path.is_file():
        raise SanitizeError(f"Archive does not exist: {path}")
    temporary = path.with_suffix(path.suffix + ".sanitizing")
    config_count = 0
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED
        ) as target:
            for info in source.infolist():
                payload = source.read(info.filename)
                if info.filename.endswith("_config.json"):
                    parsed = json.loads(payload)
                    parsed = redact(parsed)
                    assert_redacted(parsed)
                    payload = json.dumps(parsed, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
                    config_count += 1
                target.writestr(info, payload)
        if config_count != 1:
            raise SanitizeError(f"Expected one config snapshot in {path.name}, found {config_count}")
        with zipfile.ZipFile(temporary, "r") as check:
            if check.testzip() is not None:
                raise SanitizeError(f"ZIP integrity failed for {path.name}")
            config_names = [name for name in check.namelist() if name.endswith("_config.json")]
            assert_redacted(json.loads(check.read(config_names[0])))
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"archive": str(path), "config_snapshots_redacted": config_count, "zip_integrity": "PASS"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="+", type=Path)
    args = parser.parse_args()
    for archive in args.archive:
        print(json.dumps(sanitize_archive(archive), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
