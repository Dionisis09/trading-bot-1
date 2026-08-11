#!/usr/bin/env python3
"""Authenticated readiness probe that waits for Freqtrade's first completed loop."""

from __future__ import annotations

import argparse
import base64
import json
import urllib.request
from pathlib import Path


def check_ready(config_path: Path, base_url: str, timeout_seconds: float) -> bool:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    api = config.get("api_server", {})
    username = api.get("username")
    password = api.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return False
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/v1/health",
        headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return False
    return isinstance(payload, dict) and any(
        payload.get(name) not in (None, "")
        for name in ("last_process", "last_process_ts")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--timeout-seconds", type=float, default=3.0)
    args = parser.parse_args()
    return 0 if check_ready(Path(args.config), args.url, args.timeout_seconds) else 1


if __name__ == "__main__":
    raise SystemExit(main())
