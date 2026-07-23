#!/usr/bin/env python3
"""Hash a local external-data snapshot without claiming historical identity."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True, help="Directory containing local raw files.")
    parser.add_argument("--output", type=Path, required=True, help="JSON file to create.")
    parser.add_argument("--glob", default="*.csv", help="Filename pattern to hash (default: *.csv).")
    parser.add_argument("--dataset-url", default=None, help="Optional public source URL for context.")
    parser.add_argument("--label", default=None, help="Optional short dataset label.")
    return parser.parse_args(argv)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_snapshot(raw_dir: Path, pattern: str, output: Path) -> dict[str, object]:
    if not raw_dir.is_dir():
        raise FileNotFoundError(f"--raw-dir is not a directory: {raw_dir}")
    output_resolved = output.resolve()
    files = sorted(
        path
        for path in raw_dir.glob(pattern)
        if path.is_file() and path.resolve() != output_resolved
    )
    if not files:
        raise FileNotFoundError(f"No files matching {pattern!r} were found in {raw_dir}")
    return {
        "scope": "current local snapshot",
        "historical_identity_status": (
            "These hashes identify only the files present when this command ran. "
            "They do not prove identity with an earlier Kaggle download or manuscript run."
        ),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "file_count": len(files),
        "files": [
            {
                "filename": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in files
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    raw_dir = args.raw_dir.resolve()
    output = args.output.resolve()
    snapshot = build_snapshot(raw_dir, args.glob, output)
    snapshot["label"] = args.label
    snapshot["dataset_url"] = args.dataset_url
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {snapshot['file_count']} current-snapshot hashes to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
