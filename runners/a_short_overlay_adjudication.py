"""Offline P4a entry: capture only post-publication, settle only from shared cache."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.a_short_overlay_adjudication import DEFAULT_PUBLIC_JSON, DEFAULT_PUBLIC_MD, capture_after_published_weekly, settle_and_summarize_weekly


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A-short P4a Stage3 rank-source comparison (no production writes)")
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture")
    for flag in ("root", "as_of", "run_date", "stage3_snapshot", "overlay", "weekly_out", "receipt", "egs_publish_marker", "source_identity"):
        capture.add_argument("--" + flag.replace("_", "-"), required=True)
    capture.add_argument("--forward", action="store_true")
    settle = sub.add_parser("settle")
    for flag in ("root", "daily_cache", "as_of"):
        settle.add_argument("--" + flag.replace("_", "-"), required=True)
    settle.add_argument("--public-json", default=str(DEFAULT_PUBLIC_JSON)); settle.add_argument("--public-md", default=str(DEFAULT_PUBLIC_MD))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "capture":
        result = capture_after_published_weekly(root=args.root, decision_date=args.as_of, run_date=args.run_date,
            stage3_snapshot_path=args.stage3_snapshot, overlay_path=args.overlay, out_path=args.weekly_out,
            receipt_path=args.receipt, egs_publish_marker_path=args.egs_publish_marker,
            source_identity=json.loads(Path(args.source_identity).read_text(encoding="utf-8")), forward_eligible=args.forward)
    else:
        result = settle_and_summarize_weekly(root=args.root, daily_cache_path=args.daily_cache, as_of=args.as_of,
                                               public_json_path=args.public_json, public_markdown_path=args.public_md)
    print(f"[a-short-p4a] {result['status']} (production unchanged)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
