# -*- coding: utf-8 -*-
"""US-short VIX risk-regime fetch — scripts the §7 VIX axis input (was a manual FMP call).

VIX is provider-authorization-gated (SR-PROVIDER-001). Massive `I:VIX` is a 403 paywall; the free source is FMP
`stable/quote ^VIX` (confirmed 2026-07-09: HTTP 200, e.g. 16.9 with previous close). This runner does ONE gated FMP
call for `^VIX`, classifies it via the FROZEN §7 `classify_vix` ladder (18/25/35), and returns/prints a no-secret
result (value + regime; NEVER the apikey or the request URL).

Scope: it feeds ONLY the §7 RISK axis — `market_axis_regimes["vix"]` → position cap / new-entry permission — NEVER
selection, prices, or a hard veto; a missing/unavailable VIX is just `unknown` (the regime degrades via trend+breadth,
it never passes as 进攻). Auto-wiring this regime into the pipeline's `market_axis_regimes` slot is a SEPARATE step
(cc_r1 B4); this runner is the fetch+classify script. Selects no provider, writes no private state, claims no
production/ship-gate; SR-PROVIDER-001 stays open.

Usage:
  python runners/us_short_vix_regime_fetch.py --dry-run-env
  python runners/us_short_vix_regime_fetch.py --confirm-user-authorization
  python runners/us_short_vix_regime_fetch.py --confirm-user-authorization --summary-path docs/…json
Requires env: FMP_API_KEY (NEVER written to any output).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if _PYTHON_LIBS.exists() and str(_PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(_PYTHON_LIBS))

from engine.us_short_regime import UNKNOWN, classify_vix  # noqa: E402

AUTHORIZATION_REF = "user_chat_20260709_vix_regime_fetch"
FMP_QUOTE_URL = "https://financialmodelingprep.com/stable/quote?symbol={sym}&apikey={key}"
VIX_SYMBOL = "^VIX"


class VixRegimeFetchError(RuntimeError):
    """The VIX regime fetch cannot run or record safely."""


def _default_quote_fetcher(fmp_key: str) -> tuple[Any, int, str]:
    """Real FMP stable/quote GET for ^VIX → (payload, http_status, error_type). NEVER surfaces the key/URL."""
    url = FMP_QUOTE_URL.format(sym=urllib.parse.quote(VIX_SYMBOL), key=fmp_key)
    req = urllib.request.Request(url, headers={"User-Agent": "StockSystem/0.1 us-short-vix"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8")), int(resp.status), ""
    except urllib.error.HTTPError as exc:
        return None, int(exc.code), "http_error"
    except Exception as exc:  # noqa: BLE001 — never surface the URL (it carries the apikey)
        return None, 0, type(exc).__name__


def _vix_value_from_payload(payload: Any) -> float | None:
    if isinstance(payload, list):
        if len(payload) != 1:
            return None
        row = payload[0]
    else:
        row = payload if isinstance(payload, dict) else None
    if not isinstance(row, dict) or row.get("symbol") != VIX_SYMBOL:
        return None
    try:
        value = float(row.get("price"))
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _observation_time(generated_at: str | None) -> str:
    if isinstance(generated_at, str) and generated_at.strip():
        return generated_at
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_fetch(*, confirm_user_authorization: bool, quote_fetcher: Callable[[str], tuple] | None = None,
              summary_path: Path | None = None, generated_at: str | None = None,
              dry_run_env: bool = False) -> dict[str, Any]:
    fmp_key = os.environ.get("FMP_API_KEY", "")
    if dry_run_env:
        return {"scope": {"status": "dry_run_env_only"}, "fmp_key_present": bool(fmp_key)}
    if not confirm_user_authorization:
        raise VixRegimeFetchError(
            "VIX regime fetch requires explicit per-execution user authorization (SR-PROVIDER-001)")
    if not fmp_key:
        raise VixRegimeFetchError("FMP_API_KEY not set")

    observed_at = _observation_time(generated_at)
    payload, status, err = (quote_fetcher or _default_quote_fetcher)(fmp_key)
    value = _vix_value_from_payload(payload) if status == 200 else None
    regime = classify_vix(value) if value is not None else UNKNOWN
    summary = {
        "schema_name": "us_short_vix_regime_fetch_summary",
        "schema_version": "1.0.0",
        "authorization_ref": AUTHORIZATION_REF,
        "generated_at": observed_at,
        "observed_at": observed_at,
        "scope": {
            "market": "US", "lane": "us_short", "purpose": "vix_risk_axis_fetch",
            "feeds": "market_axis_regimes.vix (§7 position cap / new-entry only; NOT selection/prices/hard-veto)",
            "provider_selection_claimed": False, "production_storage_performed": False,
        },
        "provider": "financial_modeling_prep",
        "source_endpoint": "stable/quote",
        "symbol": VIX_SYMBOL,
        "http_status": status,
        "fetch_error": err,
        "vix_value": value,
        "vix_regime": regime,
        "vix_regime_is_unknown": regime == UNKNOWN,
        "sr_provider_001_remains_open": True,
        "tracked_summary_contains_secret_or_url": False,
    }
    if summary_path is not None:
        _write_summary_safe(summary, Path(summary_path), fmp_key)
    return summary


def _write_summary_safe(summary: dict[str, Any], path: Path, secret: str) -> None:
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    if secret and secret in text:
        raise VixRegimeFetchError("summary would contain the FMP_API_KEY value — refusing to write")
    if "apikey=" in text or "financialmodelingprep.com" in text:
        raise VixRegimeFetchError("summary would contain a request URL — refusing to write")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="US-short VIX risk-regime fetch (§7 axis; FMP stable/quote ^VIX)")
    parser.add_argument("--confirm-user-authorization", action="store_true")
    parser.add_argument("--dry-run-env", action="store_true")
    parser.add_argument("--summary-path", type=Path, default=None)
    parser.add_argument("--generated-at", default=None)
    args = parser.parse_args(argv)
    try:
        summary = run_fetch(
            confirm_user_authorization=args.confirm_user_authorization, summary_path=args.summary_path,
            generated_at=args.generated_at, dry_run_env=args.dry_run_env)
    except VixRegimeFetchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
