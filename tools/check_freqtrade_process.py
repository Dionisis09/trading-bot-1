#!/usr/bin/env python3
"""Minimal Docker healthcheck for an isolated Freqtrade trade process."""

from __future__ import annotations

import argparse
from pathlib import Path


def matching_process_exists(proc_root: Path, strategy: str) -> bool:
    for cmdline_path in proc_root.glob("[0-9]*/cmdline"):
        try:
            tokens = [
                part.decode("utf-8", errors="replace")
                for part in cmdline_path.read_bytes().split(b"\0")
                if part
            ]
        except (OSError, PermissionError):
            continue
        if "trade" not in tokens or "--strategy" not in tokens:
            continue
        try:
            if tokens[tokens.index("--strategy") + 1] == strategy:
                return True
        except (ValueError, IndexError):
            continue
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"))
    args = parser.parse_args()
    return 0 if matching_process_exists(args.proc_root, args.strategy) else 1


if __name__ == "__main__":
    raise SystemExit(main())
