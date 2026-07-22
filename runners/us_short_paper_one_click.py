#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Single-command US-short weekly paper-account runner.

This is the operator-facing paper path.  It delegates paper state to the
head-bound model-paper store, lets the capstone derive the exact Pass2 budget
inside the same process, and then runs the complete provider-backed source
pipeline once.  A blank account is never recreated per week: the capstone
derives its account input from the mature paper adapter.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path  # noqa: E402
from runners.us_short_weekly_capstone import (  # noqa: E402
    WeeklyCapstoneError,
    resolve_capstone_context,
    run_weekly_capstone,
)


DEFAULT_PRIVATE_ROOT = ROOT / "state" / "us_short"
DEFAULT_STATE_DIR = ROOT / "state" / "us_short"
TEMPLATE_SOURCE = ROOT / "schemas" / "examples" / "us_short_weekend_batch4_context_packet.empty.example.json"


class PaperOneClickError(RuntimeError):
    """The one-click paper launcher could not prepare or run its private inputs."""


def _parse_now_et(raw: str) -> datetime:
    try:
        value = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("now-et must be YYYY-MM-DDTHH:MM:SS in Eastern Time") from exc
    return value


def _current_now_et() -> datetime:
    return datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).replace(tzinfo=None)


def _private_root(path: Path) -> Path:
    # The capstone root itself is ``state/us_short`` (the ignored private
    # families are its child directories).  The capstone and the generated
    # input directory perform the actual private-path checks at write time.
    return path.resolve()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def _prepare_paper_inputs(*, private_root: Path, decision_date: str) -> tuple[Path, Path]:
    if not TEMPLATE_SOURCE.is_file():
        raise PaperOneClickError(f"missing tracked paper template: {TEMPLATE_SOURCE}")
    input_root = private_root / "weekly_private" / "_run_inputs"
    try:
        reject_nonprivate_output_path(input_root)
    except PrivatePathError as exc:
        raise PaperOneClickError(f"paper input directory rejected: {input_root}") from exc

    template_path = input_root / "paper_batch4_template.json"
    account_path = input_root / "paper_account_state.adapter.json"
    template = json.loads(TEMPLATE_SOURCE.read_text(encoding="utf-8"))
    _write_json(template_path, template)

    # This placeholder is never a sizing input.  The first local capstone
    # stage replaces it with the head-bound adapter after it has matured the
    # prior paper decision in memory.  On later runs it preserves the prior
    # adapter until that replacement; it never resets cash or positions.
    if not account_path.exists():
        _write_json(account_path, {"pending_model_paper_adapter": True, "decision_date": decision_date})
    return template_path, account_path


def run_one_click(
    *,
    now_et: datetime,
    private_root: Path = DEFAULT_PRIVATE_ROOT,
    state_dir: Path = DEFAULT_STATE_DIR,
    momentum_top_k: int = 200,
    provider_pace_seconds: float = 1.0,
) -> dict:
    private_root = _private_root(private_root)
    state_dir = state_dir.resolve()
    if type(momentum_top_k) is not int or not 1 <= momentum_top_k <= 250:
        raise PaperOneClickError("momentum-top-k must be an integer from 1 through 250")
    if provider_pace_seconds < 0:
        raise PaperOneClickError("provider-pace-seconds must be nonnegative")

    # Resolve the canonical week before writing any generated input.  This is
    # the same resolver used by the capstone, so the wrapper cannot drift to a
    # different decision date.
    placeholder_template = private_root / "weekly_private" / "_run_inputs" / "paper_batch4_template.json"
    placeholder_account = private_root / "weekly_private" / "_run_inputs" / "paper_account_state_pending.json"
    context = resolve_capstone_context(
        now_et=now_et,
        private_root=private_root,
        batch4_template_path=placeholder_template,
        account_state_path=placeholder_account,
        authorized_momentum_top_k=momentum_top_k,
        calendar_path=ROOT / "presets" / "us_short_market_calendar_2026_2027.json",
        confirm_user_authorization=True,
        state_dir=state_dir,
        sample_root=ROOT,
    )
    template_path, account_path = _prepare_paper_inputs(
        private_root=private_root, decision_date=context.decision_date)

    print(
        f"[US-SHORT PAPER] decision_date={context.decision_date} price_basis_date={context.price_basis_date}",
        file=sys.stderr,
    )
    print(f"[US-SHORT PAPER] python={sys.executable}", file=sys.stderr)
    summary = run_weekly_capstone(
        now_et=now_et,
        private_root=private_root,
        batch4_template_path=template_path,
        account_state_path=account_path,
        authorized_momentum_top_k=momentum_top_k,
        authorized_pass2_call_budget=None,
        calendar_path=ROOT / "presets" / "us_short_market_calendar_2026_2027.json",
        confirm_user_authorization=True,
        dry_run=False,
        provider_pace_seconds=provider_pace_seconds,
        state_dir=state_dir,
        sample_root=ROOT,
        auto_authorize_pass2_budget=True,
        model_paper_store_root=private_root / "model_paper_private",
        model_paper_run_account_mode="paper_only",
    )
    return {
        **summary,
        "paper_account_mode": "paper_only",
        "manual_account_read": False,
        "automatic_broker_execution": False,
        "ship_gate_eligible": False,
        "paper_account_state_path": str(account_path),
        "model_paper_store_root": str(private_root / "model_paper_private"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="US-short weekly one-click paper-account runner")
    parser.add_argument("--now-et", type=_parse_now_et, default=None)
    parser.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE_ROOT)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--momentum-top-k", type=int, default=200)
    parser.add_argument("--provider-pace-seconds", type=float, default=1.0)
    args = parser.parse_args(argv)
    try:
        summary = run_one_click(
            now_et=args.now_et or _current_now_et(),
            private_root=args.private_root,
            state_dir=args.state_dir,
            momentum_top_k=args.momentum_top_k,
            provider_pace_seconds=args.provider_pace_seconds,
        )
    except (PaperOneClickError, WeeklyCapstoneError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
