#!/usr/bin/env python3
"""Thin offline entry for P5a private capture/settlement/progress operations."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_industry_weight_comparison import (  # noqa: E402
    DEFAULT_PUBLIC_JSON, DEFAULT_PUBLIC_MD, build_public_progress, capture_after_published_weekly,
    settle_and_summarize_weekly, write_public_progress,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="P5a industry-weight comparison; comparison-only and cache-only.")
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture")
    capture.add_argument("--root", required=True); capture.add_argument("--as-of", required=True)
    capture.add_argument("--run-date", required=True); capture.add_argument("--analysis-input", required=True)
    capture.add_argument("--weight-comparison", required=True); capture.add_argument("--weekly-out", required=True)
    capture.add_argument("--receipt", required=True); capture.add_argument("--source-identity", required=True)
    capture.add_argument("--forward", action="store_true")
    settle = sub.add_parser("settle")
    settle.add_argument("--root", required=True); settle.add_argument("--daily-cache", required=True)
    settle.add_argument("--as-of", required=True); settle.add_argument("--public-json", default=str(DEFAULT_PUBLIC_JSON))
    settle.add_argument("--public-md", default=str(DEFAULT_PUBLIC_MD))
    progress = sub.add_parser("progress")
    progress.add_argument("--root", required=True); progress.add_argument("--as-of", required=True)
    progress.add_argument("--public-json", default=str(DEFAULT_PUBLIC_JSON)); progress.add_argument("--public-md", default=str(DEFAULT_PUBLIC_MD))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "capture":
        identity = json.loads(Path(args.source_identity).read_text(encoding="utf-8"))
        result = capture_after_published_weekly(root=args.root, decision_date=args.as_of, run_date=args.run_date,
                                                analysis_input_path=args.analysis_input, weight_comparison_path=args.weight_comparison,
                                                source_identity=identity, out_path=args.weekly_out, receipt_path=args.receipt,
                                                forward_eligible=args.forward)
    elif args.command == "settle":
        result = settle_and_summarize_weekly(root=args.root, daily_cache_path=args.daily_cache, as_of=args.as_of,
                                             public_json_path=args.public_json, public_markdown_path=args.public_md)
    else:
        result = build_public_progress(root=args.root, as_of=args.as_of)
        write_public_progress(result, json_path=args.public_json, markdown_path=args.public_md)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
