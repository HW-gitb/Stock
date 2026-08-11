"""Offline cross-validation of the V1 shared-cache and V5 revision contracts.

The scenarios use only temporary roots and a fake provider seam.  They prove the
boundary between the two slices rather than duplicating either slice's unit
tests: a cache can be upgraded before publication, a post-publication consumer
expansion leaves A immutable while publishing B, and settlement maturation
updates B in place without minting C.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import a_short_factor_comparison as v1  # noqa: E402
from engine.a_short_factor_comparison_v2 import (  # noqa: E402
    build_v2_public_progress,
    capture_v2_week,
    settle_v2_from_daily_payload,
)
from engine.a_short_run_revision import (  # noqa: E402
    build_revision_manifest,
    official_public_revision_root,
    public_revision_root,
    read_official_revision,
    research_revision_root,
    select_official_revision,
    write_revision_manifest,
)
from runners.a_short_factor_comparison_v2_cache_build import (  # noqa: E402
    materialize_incremental_cache,
)


DECISION_DATE = "20260811"
RUN_DATE = DECISION_DATE
PRICE_DATA_THROUGH = "20260810"
REVISION_A = "a" * 32
REVISION_B = "b" * 32


def _weekdays_ending(end_date: str, count: int) -> list[str]:
    current = date(int(end_date[:4]), int(end_date[4:6]), int(end_date[6:]))
    values: list[str] = []
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current.strftime("%Y%m%d"))
        current -= timedelta(days=1)
    return list(reversed(values))


def _weekdays_from(start_date: str, count: int) -> list[str]:
    current = date(int(start_date[:4]), int(start_date[4:6]), int(start_date[6:]))
    values: list[str] = []
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return values


def _candidate(symbol: str, *, close: float = 10.5) -> dict:
    history = _weekdays_ending(PRICE_DATA_THROUGH, 30)
    series = []
    for index, day in enumerate(history):
        series.append({
            "trade_date": day,
            "high": 15.0 if index in (22, 27) else close + 0.2,
            "low": 9.7 if index in (21, 26) else close - 0.2,
            "close": close if index >= 20 else close - 0.3,
        })
    return {
        "ts_code": symbol,
        "name": symbol,
        "close": close,
        "price_series": series,
        "egs_score": 90.0,
        "derived": {},
        "event": {},
        "liquidity": {"avg_amount_5d": 1e9},
        "iv": {"iv_percentile_252d": 50.0, "iv_value": 0.20, "hv_value": 0.18},
        "market_regime": "attack",
        "regime_fallback": {},
        "stateful_risk": {},
    }


def _run_identity(candidates: list[dict], revision: str) -> dict:
    sanitized = [v1._safe_candidate(row) for row in candidates]
    return {
        "run_id": f"cross-validation-{revision}",
        "run_date": RUN_DATE,
        "source_as_of": DECISION_DATE,
        "price_data_through": PRICE_DATA_THROUGH,
        "candidate_digest": v1._digest(sanitized),
        "official_m67_digest": "c" * 64,
        "run_revision_id": revision,
    }


class _FakeProvider:
    def __init__(self, *, missing_adjustments: bool = False):
        self.missing_adjustments = missing_adjustments
        self.calls: list[tuple[str, dict]] = []

    @staticmethod
    def _days(start_date: str, end_date: str) -> list[str]:
        current = date(int(start_date[:4]), int(start_date[4:6]), int(start_date[6:]))
        finish = date(int(end_date[:4]), int(end_date[4:6]), int(end_date[6:]))
        values: list[str] = []
        while current <= finish:
            if current.weekday() < 5:
                values.append(current.strftime("%Y%m%d"))
            current += timedelta(days=1)
        return values

    def trade_cal(self, **kwargs):
        self.calls.append(("trade_cal", kwargs))
        return pd.DataFrame({"cal_date": self._days(kwargs["start_date"], kwargs["end_date"])})

    def daily(self, **kwargs):
        self.calls.append(("daily", kwargs))
        return pd.DataFrame([
            {
                "ts_code": kwargs["ts_code"],
                "trade_date": day,
                "open": 10.0,
                "high": 10.8,
                "low": 9.8,
                "close": 10.5,
                "vol": 1000.0,
            }
            for day in self._days(kwargs["start_date"], kwargs["end_date"])
        ])

    def adj_factor(self, **kwargs):
        self.calls.append(("adj_factor", kwargs))
        if self.missing_adjustments:
            return pd.DataFrame(columns=["ts_code", "trade_date", "adj_factor"])
        return pd.DataFrame([
            {"ts_code": kwargs["ts_code"], "trade_date": day, "adj_factor": 1.0}
            for day in self._days(kwargs["start_date"], kwargs["end_date"])
        ])

    def stk_limit(self, **kwargs):
        self.calls.append(("stk_limit", kwargs))
        return pd.DataFrame([
            {
                "ts_code": kwargs["ts_code"],
                "trade_date": day,
                "up_limit": 11.0,
                "down_limit": 9.0,
            }
            for day in self._days(kwargs["start_date"], kwargs["end_date"])
        ])

    def index_daily(self, **kwargs):
        self.calls.append(("index_daily", kwargs))
        return pd.DataFrame([
            {"ts_code": kwargs["ts_code"], "trade_date": day, "open": 100.0, "close": 101.0}
            for day in self._days(kwargs["start_date"], kwargs["end_date"])
        ])


def _cache_path(root: Path) -> Path:
    return root / "state" / "a_short" / "factor_comparison_private" / "v2" / "daily_cache.json"


def _cache_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _daily_payload(symbols: list[str], days: list[str]) -> dict:
    days = sorted(set([PRICE_DATA_THROUGH, *days]))
    stocks = []
    limits = []
    for symbol in symbols:
        close = 10.6 if symbol == "600001.SH" else 10.5
        for day in days:
            stocks.append({
                "ts_code": symbol,
                "trade_date": day,
                "open": 10.0,
                "close": close,
                "adj_factor": 1.0,
                "raw_provider_observed": True,
                "adj_factor_observed": True,
                "adj_factor_source": "provider_observed",
                "corporate_action_verified": False,
            })
            limits.append({
                "ts_code": symbol,
                "trade_date": day,
                "up_limit": 11.0,
                "down_limit": 9.0,
            })
    return {"stocks": pd.DataFrame(stocks), "limits": pd.DataFrame(limits)}


def _write_and_select_revision(root: Path, revision: str, *, candidate_digest: str,
                               cache_digest: str) -> dict:
    public = public_revision_root(root, DECISION_DATE, revision)
    research = research_revision_root(root, DECISION_DATE, revision)
    public.mkdir(parents=True, exist_ok=True)
    research.mkdir(parents=True, exist_ok=True)
    analysis = public / "analysis_input.json"
    weekly = research / "weekly_m67.json"
    payload = {
        "decision_as_of": DECISION_DATE,
        "run_revision_id": revision,
        "candidate_digest": candidate_digest,
        "shared_cache_sha256": cache_digest,
    }
    encoded = json.dumps(payload, sort_keys=True) + "\n"
    analysis.write_text(encoded, encoding="utf-8")
    weekly.write_text(encoded, encoding="utf-8")
    manifest_path = research / "revision_manifest.json"
    manifest = build_revision_manifest(
        project_root=root,
        manifest_path=manifest_path,
        decision_as_of=DECISION_DATE,
        run_date=RUN_DATE,
        price_data_through=PRICE_DATA_THROUGH,
        run_revision_id=revision,
        run_id=f"cross-validation-{revision}",
        candidate_digest=candidate_digest,
        roles={"analysis_input": analysis, "weekly_m67": weekly},
    )
    write_revision_manifest(manifest_path, manifest)
    pointer = root / "research" / "results" / "a_short" / DECISION_DATE / "official_revision.json"
    result = select_official_revision(
        pointer_path=pointer,
        selection_receipt_path=pointer.with_name("official_selection_receipt.json"),
        manifest_path=manifest_path,
        transaction_dir=root / "state" / "a_short" / "revision_transactions" / DECISION_DATE,
        run_revision_id=revision,
        decision_as_of=DECISION_DATE,
    )
    return {"manifest": manifest, "manifest_path": manifest_path, "selection": result}


class V1V5CrossValidationTests(unittest.TestCase):
    def test_cache_upgrade_revision_switch_and_same_official_settlement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_root = root / "state" / "a_short" / "factor_comparison_private" / "v2"
            candidates_a = [_candidate("600000.SH")]
            candidates_b = [_candidate("600000.SH"), _candidate("600001.SH", close=10.6)]
            identity_a = _run_identity(candidates_a, REVISION_A)
            identity_b = _run_identity(candidates_b, REVISION_B)

            with patch("engine.a_short_factor_comparison_v2._today", return_value=RUN_DATE), \
                    patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                capture_v2_week(
                    root=cache_root, decision_date=DECISION_DATE, candidates=candidates_a,
                    run_identity=identity_a, forward_eligible=True, run_revision_id=REVISION_A,
                )
                first = materialize_incremental_cache(
                    root=cache_root, run_date=RUN_DATE, max_provider_calls=4,
                    pro=_FakeProvider(missing_adjustments=True),
                )
                self.assertEqual(first["status"], "cache_updated")
                first_cache = json.loads(_cache_path(root).read_text(encoding="utf-8"))
                self.assertTrue(first_cache["stocks"])
                self.assertFalse(first_cache["stocks"][0]["adj_factor_observed"])
                before_publish_capture = (cache_root / "weeks" / DECISION_DATE / "revisions" /
                                          REVISION_A / "capture.json").read_bytes()

                second = materialize_incremental_cache(
                    root=cache_root, run_date=RUN_DATE, max_provider_calls=4,
                    pro=_FakeProvider(),
                )
                self.assertEqual(second["status"], "cache_updated")
                second_cache = json.loads(_cache_path(root).read_text(encoding="utf-8"))
                self.assertTrue(all(row["adj_factor_observed"] for row in second_cache["stocks"]))
                prepublish_digest = _cache_digest(_cache_path(root))

                selected_a = _write_and_select_revision(
                    root, REVISION_A, candidate_digest=identity_a["candidate_digest"],
                    cache_digest=prepublish_digest,
                )
                self.assertEqual(selected_a["selection"]["status"], "selected")
                self.assertEqual(
                    read_official_revision(root / "research" / "results" / "a_short" /
                                           DECISION_DATE / "official_revision.json")["selected_revision_id"],
                    REVISION_A,
                )

                capture_v2_week(
                    root=cache_root, decision_date=DECISION_DATE, candidates=candidates_b,
                    run_identity=identity_b, forward_eligible=True, run_revision_id=REVISION_B,
                )
                third = materialize_incremental_cache(
                    root=cache_root, run_date=RUN_DATE, max_provider_calls=4,
                    pro=_FakeProvider(),
                )
                self.assertEqual(third["status"], "cache_updated")
                self.assertEqual(third["symbols_updated"], ["600001.SH"])
                postpublish_digest = _cache_digest(_cache_path(root))
                self.assertNotEqual(prepublish_digest, postpublish_digest)
                self.assertEqual(before_publish_capture,
                                 (cache_root / "weeks" / DECISION_DATE / "revisions" /
                                  REVISION_A / "capture.json").read_bytes())

                selected_b = _write_and_select_revision(
                    root, REVISION_B, candidate_digest=identity_b["candidate_digest"],
                    cache_digest=postpublish_digest,
                )
                self.assertEqual(selected_b["selection"]["status"], "selected")
                self.assertEqual(official_public_revision_root(root, DECISION_DATE),
                                 public_revision_root(root, DECISION_DATE, REVISION_B))
                self.assertTrue((public_revision_root(root, DECISION_DATE, REVISION_A) /
                                 "analysis_input.json").is_file())

                partial_days = [DECISION_DATE, _weekdays_from(DECISION_DATE, 2)[1]]
                partial = settle_v2_from_daily_payload(
                    root=cache_root, daily_payload=_daily_payload(
                        ["600000.SH", "600001.SH"], partial_days,
                    ), run_revision_id=REVISION_B, official_project_root=root,
                )
                self.assertEqual(partial["status"], "settled_from_existing_cache")
                b_outcome_path = (cache_root / "weeks" / DECISION_DATE / "revisions" /
                                  REVISION_B / "outcome.json")
                self.assertEqual(json.loads(b_outcome_path.read_text(encoding="utf-8"))[
                    "payload"]["questions"][0]["status"], "pending")

                full_days = _weekdays_from(DECISION_DATE, 21)
                mature = settle_v2_from_daily_payload(
                    root=cache_root, daily_payload=_daily_payload(
                        ["600000.SH", "600001.SH"], full_days,
                    ), run_revision_id=REVISION_B, official_project_root=root,
                )
                self.assertEqual(mature["status"], "settled_from_existing_cache")
                b_outcome = json.loads(b_outcome_path.read_text(encoding="utf-8"))
                self.assertEqual(b_outcome["payload"]["questions"][0]["status"], "settled")

                ledger = json.loads((cache_root / "ledger.json").read_text(encoding="utf-8"))
                keys = [(row["decision_date"], row.get("run_revision_id"), row["question_id"])
                        for row in ledger["entries"]]
                self.assertEqual(len(keys), len(set(keys)))
                self.assertTrue(all(row.get("run_revision_id") == REVISION_B
                                    for row in ledger["entries"]))

                progress = build_v2_public_progress(
                    root=cache_root, as_of=DECISION_DATE, official_project_root=root,
                )
                self.assertEqual(progress["official_revision_id"], REVISION_B)
                self.assertTrue(all(row["forward_weeks"] == 1 for row in progress["evidence"]))
                self.assertTrue(all(row["settled_weeks"] == 1 for row in progress["evidence"]))


if __name__ == "__main__":
    unittest.main()
