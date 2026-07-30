from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.backtest_execution import iso_now, validate_json_schema


SCHEMA_PATH = ROOT / "schemas" / "a_short_variant_tracking.schema.json"
DEFAULT_TEMPLATE_PATH = ROOT / "schemas" / "examples" / "a_short_variant_tracking.example.json"
DEFAULT_OUT_DIR = Path("result") / "a_short" / "backtest" / "variants"
DEFAULT_OUT_NAME = "a_short_variant_tracking_plan.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize a schema-valid Phase 6b A-short variant tracking plan. "
            "This runner consumes the tracking contract only; it does not compute "
            "evidence, promote variants, mutate EGS, or implement burst_lane."
        )
    )
    parser.add_argument(
        "--template-path",
        type=Path,
        default=DEFAULT_TEMPLATE_PATH,
        help=(
            "Source tracking template. Defaults to "
            "schemas/examples/a_short_variant_tracking.example.json."
        ),
    )
    parser.add_argument(
        "--out-path",
        type=Path,
        help=(
            "Output JSON path. Defaults to "
            "result/a_short/backtest/variants/a_short_variant_tracking_plan.json."
        ),
    )
    parser.add_argument(
        "--generated-at",
        help="Optional deterministic generated_at timestamp for tests or replay.",
    )
    return parser.parse_args(argv)


def output_path(out_path: Path | None) -> Path:
    if out_path is not None:
        return out_path
    return DEFAULT_OUT_DIR / DEFAULT_OUT_NAME


def load_template(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"variant tracking template must be a JSON object: {path}")
    return payload


def materialize_payload(template: dict[str, Any], generated_at: str | None = None) -> dict[str, Any]:
    payload = copy.deepcopy(template)
    payload["generated_at"] = generated_at or iso_now()
    return payload


def write_payload(payload: dict[str, Any], path: Path) -> None:
    validate_json_schema(payload, SCHEMA_PATH, "a_short_variant_tracking")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = materialize_payload(
        load_template(args.template_path),
        generated_at=args.generated_at,
    )
    out_path = output_path(args.out_path)
    write_payload(payload, out_path)
    print(f"[OK] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
