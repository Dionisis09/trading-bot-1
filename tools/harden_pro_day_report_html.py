#!/usr/bin/env python3
"""Apply the workspace-owned mobile overflow fix to a packaged ProDay report.

The canonical portable-artifact packager remains unmodified.  This postprocessor
adds one bounded CSS override to the already self-contained HTML, atomically and
idempotently.  It does not alter the embedded artifact payload or contact a
browser/network service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Sequence


STYLE_ID = "pro-day-mobile-overflow-hardening"
MARKER = "<!-- pro-day-mobile-overflow-hardening:v1 -->"
CSS = """.portable-page-header{width:auto;margin-right:-32px;margin-left:-32px}
@media screen and (max-width:760px){
  .portable-page-header{margin-right:-24px;margin-left:-24px}
  .portable-fallback,
  .portable-block-stack,
  .portable-block,
  .portable-content-card,
  .portable-table-card,
  .portable-table-source-region,
  .portable-table-scroll{min-width:0;max-width:100%}
  .portable-markdown,
  .portable-notice,
  .portable-page-heading{min-width:0;max-width:100%;overflow-wrap:anywhere;word-break:normal}
  .portable-table-source-region,
  .portable-table-scroll{contain:inline-size;width:100%}
  .portable-table-scroll{overflow-x:auto;overflow-y:hidden;overscroll-behavior-x:contain;-webkit-overflow-scrolling:touch}
}"""
STYLE_BLOCK = f'{MARKER}\n<style id="{STYLE_ID}">\n{CSS}\n</style>'


class HardeningError(ValueError):
    """Raised when a report cannot be hardened without ambiguity."""


def harden_html_text(html: str) -> tuple[str, bool]:
    """Return hardened HTML and whether a change was required."""

    marker_count = html.count(MARKER)
    style_id_count = html.count(f'id="{STYLE_ID}"')
    block_count = html.count(STYLE_BLOCK)
    if marker_count or style_id_count:
        if marker_count == style_id_count == block_count == 1:
            return html, False
        raise HardeningError("Conflicting or partial ProDay hardening marker found")

    closing_head = "</head>"
    if html.count(closing_head) != 1:
        raise HardeningError("Expected exactly one </head> element")
    return html.replace(closing_head, f"{STYLE_BLOCK}\n{closing_head}", 1), True


def atomic_write(path: Path, payload: bytes) -> None:
    """Atomically replace *path* with *payload* in the destination directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def harden_file(input_path: Path, output_path: Path | None = None) -> dict[str, object]:
    """Harden *input_path*, writing in place unless *output_path* is supplied."""

    destination = output_path if output_path is not None else input_path
    try:
        original = input_path.read_bytes()
        html = original.decode("utf-8")
    except FileNotFoundError as exc:
        raise HardeningError(f"Input report does not exist: {input_path}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise HardeningError(f"Input report is not readable UTF-8 HTML: {input_path}") from exc

    hardened, changed = harden_html_text(html)
    encoded = hardened.encode("utf-8")
    same_path = input_path.resolve() == destination.resolve()
    if changed or not same_path:
        atomic_write(destination, encoded)

    return {
        "status": "PRO_DAY_REPORT_HTML_HARDENED",
        "changed": changed,
        "input": input_path.as_posix(),
        "output": destination.as_posix(),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "bytes": len(encoded),
        "marker": STYLE_ID,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--input", type=Path, required=True)
    result.add_argument("--output", type=Path, help="Defaults to an atomic in-place update")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        receipt = harden_file(args.input, args.output)
    except HardeningError as exc:
        print(json.dumps({"status": "PRO_DAY_REPORT_HTML_HARDENING_FAILED", "error": str(exc)}))
        return 2
    print(json.dumps(receipt, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
