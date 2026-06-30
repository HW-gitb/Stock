# -*- coding: utf-8 -*-
r"""Supported offline builder for the US-short batch4 weekend context packet.

Closes the second half of R-USSHORT-BATCH4-ONE-CLICK-EXECUTION-ENTRYPOINT-GAP: the runner
(``runners/us_short_weekend_batch4.py``) consumes an 18-key closed-world context packet, but until
now the only thing that produced one was a test-internal helper. This builder is the documented,
schema-first way a user assembles that packet from THREE explicit local sources:

  1. the batch1 account artifact (``us_short_account_state.json`` from the manual-tables converter),
  2. an explicitly supplied local batch2/3 analysis fixture (the 11 non-path keys — the offline
     selection/analysis layer the user provides; see schemas/examples/*context_packet*.example.json),
  3. reviewed calendar / governance paths + the private lifecycle/output roots.

It validates the account, reconciles the fixture holdings 1:1 with the account positions, assembles
the packet, validates it against ``schemas/us_short_weekend_batch4_context_packet.schema.json``, and
writes it to a private (gitignored / external) path. A real packet carries ticker/holding/score data,
so the output is held to the same §18.0 P0 fail-closed private-path floor as every other US-short
persister. This is OFFLINE only: no provider call, network, broker, order, or live authorization.

``--analysis-fixture`` accepts either a bare 11-analysis-key file OR a full 18-key packet/example
template (its 7 ``*_path``/``*_root`` keys are ignored and overridden by the CLI args), so the committed
example templates under ``schemas/examples/`` are directly consumable. Failures are REDACTED: the CLI
prints an error code + safe path/location/counts, never a ticker / holding / account value / score /
raw invalid value.

PowerShell copy/paste sequence (set the first two variables for your machine):
    $PythonExe = 'C:\Path\To\python.exe'
    $PrivateRoot = 'C:\Path\To\private\us_short'
    & $PythonExe runners/us_short_weekend_batch4_context_builder.py `
        --account "$PrivateRoot\us_short_account_state.json" `
        --analysis-fixture schemas/examples/us_short_weekend_batch4_context_packet.empty.example.json `
        --calendar presets/us_short_market_calendar_2026_2027.json `
        --governance presets/us_short_eligibility_governance_20260624.json `
        --lifecycle-register "$PrivateRoot\lifecycle\lifecycle_register.json" `
        --runs-private-root "$PrivateRoot\runs_private" --weekly-private-root "$PrivateRoot\weekly_private" `
        --out "$PrivateRoot\packet.json"
    & $PythonExe runners/us_short_weekend_batch4.py --context "$PrivateRoot\packet.json" `
        --now-et 2026-06-13T10:00:00 --bootstrap-lifecycle --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_cli_redaction import safe_schema_location
from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path
from runners.us_short_account_state_from_manual_tables import ConvertError, validate_account_state

SCHEMA_PATH = ROOT / "schemas" / "us_short_weekend_batch4_context_packet.schema.json"

# the 11 batch2/3 analysis-layer keys the user supplies via --analysis-fixture; the other 7 are the
# *_path / *_root values this builder injects from its CLI arguments. The fixture may be a bare 11-key
# analysis file OR a full 18-key packet/example template (its path keys are IGNORED and overridden by
# the CLI args) — so the committed example templates are directly consumable, no shape-strip helper.
_ANALYSIS_KEYS = frozenset({
    "data_context", "per_ticker_analysis", "run_provenance", "provider_health", "market_axis_regimes",
    "prior_regime", "prior_upgrade_count", "sizing_per_ticker", "basket_context", "cost_inputs",
    "report_context",
})
_PATH_KEYS = frozenset({
    "eligibility_governance_path", "calendar_path", "account_state_path", "lifecycle_register_path",
    "lifecycle_readiness_out_path", "runs_private_root", "weekly_private_root",
})
_ALL_PACKET_KEYS = _ANALYSIS_KEYS | _PATH_KEYS


class ContextBuilderError(ValueError):
    """The account, fixture, or assembled packet is invalid (fail-closed; nothing is written).

    User-facing messages are REDACTED (error code + safe location/counts only): they never echo a
    ticker, holding, account value, score, or raw invalid value (§11/§18 no-secret contract). The
    user inspects their own private artifact for the offending value."""


def _read_json(path: Path, label: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        raise ContextBuilderError(f"READ_JSON_FAILED: {label} 无法读取为 UTF-8 JSON")


def _abs(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContextBuilderError(f"{label} 须为非空路径字符串")
    return str(Path(value).resolve())


def _validate_account(account) -> set:
    if not isinstance(account, dict):
        raise ContextBuilderError("ACCOUNT_INVALID: account_state 须为 JSON object")
    try:
        validate_account_state(account, account.get("as_of"))
    except (ConvertError, KeyError, TypeError):
        # redacted: validate_account_state messages echo account equity/cash/ticker values
        raise ContextBuilderError("ACCOUNT_INVALID: account_state 未通过校验（详见你的私密 account artifact）")
    return {p["ticker"] for p in account["positions"]}


def _reconcile_holdings(fixture: dict, account_tickers: set) -> None:
    """Enforce a TRUE 1:1 between fixture data_context.holdings and account positions: canonical tickers
    must be UNIQUE (so two duplicate holding rows of the same ticker do not pass set equality) AND equal
    the account ticker set. Redacted: counts only, never the tickers."""
    data_context = fixture.get("data_context")
    if not (isinstance(data_context, dict) and isinstance(data_context.get("holdings"), list)):
        raise ContextBuilderError("FIXTURE_DATA_CONTEXT_INVALID: data_context.holdings 须为 list")
    canon = []
    for h in data_context["holdings"]:
        c = canonical_us_ticker(h.get("ticker")) if isinstance(h, dict) else None
        if c is None:
            raise ContextBuilderError("FIXTURE_DATA_CONTEXT_INVALID: holdings 行须为 {object, 合法 ticker}")
        canon.append(c)
    if len(set(canon)) != len(canon):
        raise ContextBuilderError(
            f"HOLDINGS_DUPLICATE: data_context.holdings 含 {len(canon) - len(set(canon))} 个重复 canonical ticker（须 1:1 唯一）")
    if set(canon) != account_tickers:
        raise ContextBuilderError(
            f"HOLDINGS_RECONCILE_MISMATCH: holdings({len(set(canon))}) 与 account positions({len(account_tickers)}) 不 1:1 对应")


def _validate_packet_schema(packet: dict) -> None:
    try:
        import jsonschema
    except ImportError:
        raise ContextBuilderError("jsonschema 未安装；无法校验 context packet，拒绝降级写出")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(packet, schema)
    except jsonschema.ValidationError as exc:
        location = safe_schema_location(exc.absolute_path, allowed_roots=_ALL_PACKET_KEYS)
        raise ContextBuilderError(
            f"PACKET_SCHEMA_INVALID: assembled context packet 不符合 schema (at {location})")


def build_packet(*, account_path, analysis_fixture_path, calendar_path, governance_path,
                 lifecycle_register_path, runs_private_root, weekly_private_root,
                 lifecycle_readiness_out_path=None) -> dict:
    """Combine the batch1 account + a local batch2/3 analysis fixture + reviewed paths into a
    schema-validated 18-key packet dict. Pure (no write); raises ContextBuilderError on any invalid input."""
    account_abs = _abs(account_path, "--account")
    try:
        reject_nonprivate_output_path(account_abs)   # the account carries real holdings: must be a private path
    except PrivatePathError as exc:
        raise ContextBuilderError("--account 必须为可证明私密的路径") from exc
    account = _read_json(Path(account_abs), "us_short_account_state")
    account_tickers = _validate_account(account)

    fixture = _read_json(Path(analysis_fixture_path).resolve(), "analysis fixture")
    if not isinstance(fixture, dict):
        raise ContextBuilderError("FIXTURE_KEYS_INVALID: analysis fixture 须为 JSON object")
    keys = set(fixture)
    missing = _ANALYSIS_KEYS - keys                    # the 11 batch2/3 analysis keys are required
    unknown = keys - _ALL_PACKET_KEYS                  # only the 18 packet keys are allowed (path keys ignored)
    if missing or unknown:
        # safe: `missing` are our own constant key NAMES; `unknown` reported as a COUNT only (user-controlled)
        raise ContextBuilderError(
            f"FIXTURE_KEYS_INVALID: 缺分析键 {sorted(missing)}；{len(unknown)} 个未知顶层键（仅接受 11 分析键 + 可选 7 路径键）")
    analysis = {k: fixture[k] for k in _ANALYSIS_KEYS}  # take ONLY the analysis layer; any path keys are overridden
    _reconcile_holdings(analysis, account_tickers)

    packet = {
        **analysis,
        "eligibility_governance_path": _abs(governance_path, "--governance"),
        "calendar_path": _abs(calendar_path, "--calendar"),
        "account_state_path": account_abs,
        "lifecycle_register_path": _abs(lifecycle_register_path, "--lifecycle-register"),
        "lifecycle_readiness_out_path": (None if lifecycle_readiness_out_path is None
                                         else _abs(lifecycle_readiness_out_path, "--lifecycle-readiness-out")),
        "runs_private_root": _abs(runs_private_root, "--runs-private-root"),
        "weekly_private_root": _abs(weekly_private_root, "--weekly-private-root"),
    }
    _validate_packet_schema(packet)
    return packet


def _write_packet(packet: dict, out_path: str) -> Path:
    out_abs = Path(_abs(out_path, "--out"))
    try:
        reject_nonprivate_output_path(out_abs)   # the packet carries tickers/holdings/scores: private floor
    except PrivatePathError as exc:
        raise ContextBuilderError("--out 必须为可证明私密的路径") from exc
    out_abs.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_abs.with_suffix(out_abs.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(packet, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, out_abs)
    return out_abs


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Assemble a US-short batch4 weekend context packet (offline)")
    p.add_argument("--account", required=True, help="batch1 us_short_account_state.json (ABSOLUTE private path)")
    p.add_argument("--analysis-fixture", required=True,
                   help="local batch2/3 fixture: bare 11-key analysis object or full 18-key packet/example")
    p.add_argument("--calendar", required=True, help="reviewed frozen NYSE/NASDAQ calendar artifact")
    p.add_argument("--governance", required=True, help="reviewed eligibility governance preset")
    p.add_argument("--lifecycle-register", required=True, help="private lifecycle register path")
    p.add_argument("--runs-private-root", required=True, help="private machine-record root")
    p.add_argument("--weekly-private-root", required=True, help="private weekly-report/action-table root")
    p.add_argument("--lifecycle-readiness-out", default=None, help="optional private lifecycle readiness sidecar")
    p.add_argument("--out", required=True, help="output packet path (ABSOLUTE private path)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        packet = build_packet(
            account_path=args.account, analysis_fixture_path=args.analysis_fixture,
            calendar_path=args.calendar, governance_path=args.governance,
            lifecycle_register_path=args.lifecycle_register, runs_private_root=args.runs_private_root,
            weekly_private_root=args.weekly_private_root,
            lifecycle_readiness_out_path=args.lifecycle_readiness_out)
        out_abs = _write_packet(packet, args.out)
    except ContextBuilderError as exc:
        print(f"US-short batch4 context builder failed: {exc}", file=sys.stderr)   # already redacted
        return 2
    except Exception as exc:
        # redacted: surface only the error CLASS for any unexpected propagated error, never str(exc)
        print(f"US-short batch4 context builder failed: {type(exc).__name__}（已脱敏）", file=sys.stderr)
        return 2
    # no-secret summary: count of analysis tickers + the output path, never the tickers/account values themselves
    n_analysis = len(packet["per_ticker_analysis"])
    print(json.dumps({"packet_written": str(out_abs), "per_ticker_analysis_count": n_analysis,
                      "top_level_key_count": len(packet)}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
