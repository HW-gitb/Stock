from __future__ import annotations

import importlib
import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft7Validator  # noqa: E402
from engine.us_short_eligibility_gate import load_eligibility_governance  # noqa: E402
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402
from tests.provider.test_us_short_batch5_data_context import (  # noqa: E402
    _DECISION_DATE,
    _GENERATED_AT,
    _PRICE_BASIS_DATE,
    _USED_DATE,
)
from tests.provider.us_short_private_test_root import (  # noqa: E402
    temporary_us_short_directory,
    temporary_us_short_state_directory,
)


STATE_DIR = ROOT / "state" / "us_short"
SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_full_universe_overextension_20260709"
RUNNER_MODULE = "runners.us_short_batch5_full_universe_overextension_producer"
_GOV_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
_PRICE_BASIS_YMD = _USED_DATE  # "2026-06-12" — the OHLCV series as_of (== packet price_basis_date)
_SESSION = "RTH"
_ADJ = "split_adjusted"

_SPECS = {
    "AAPL": {"cik": 320193, "exchange": "NASDAQ", "shares": 15_000_000_000, "price": 200.0, "adv_usd": 50_000_000.0},
    "MSFT": {"cik": 789019, "exchange": "NASDAQ", "shares": 7_000_000_000, "price": 400.0, "adv_usd": 80_000_000.0},
    "JPM": {"cik": 19617, "exchange": "NYSE", "shares": 3_000_000_000, "price": 200.0, "adv_usd": 70_000_000.0},
    "GOOG": {"cik": 1652044, "exchange": "NASDAQ", "shares": 6_000_000_000, "price": 180.0, "adv_usd": 60_000_000.0},
    "AMZN": {"cik": 1018724, "exchange": "NASDAQ", "shares": 10_000_000_000, "price": 190.0, "adv_usd": 65_000_000.0},
}
_ALL_ELIGIBLE = ("AAPL", "MSFT", "JPM", "GOOG", "AMZN")

# Confirmed states (engine probe): AAPL parabolic → chasing_extreme; MSFT alternating → none; GOOG gentle
# late-rise over MA10+ATR (0 parabolic conds) → warning; AMZN 3-bar → insufficient_data; JPM absent → insufficient_data.
_PARA_CLOSES = [106 + i for i in range(24)] + [135]
_PARA_VOLS = [1_000_000.0] * 24 + [3_000_000.0]
_ALT_CLOSES = [100, 101] * 13
_WARN_CLOSES = [100.0] * 16 + [101.0, 100.8, 101.5, 102.0, 103.5]
_THIN_CLOSES = [100.0, 101.0, 102.0]


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _runner():
    return importlib.import_module(RUNNER_MODULE)


def _gov():
    return load_eligibility_governance(_GOV_PATH)


def _candidate_artifact(tickers):
    sec_tickers = {t: {"cik": _SPECS[t]["cik"], "exchange": _SPECS[t]["exchange"]} for t in tickers}
    sec_shares = {_SPECS[t]["cik"]: {"shares": _SPECS[t]["shares"], "end": "2026-03-31"} for t in tickers}
    market_data = {
        t: {
            "close": _SPECS[t]["price"],
            "volume": 100_000,
            "adv_usd": _SPECS[t]["adv_usd"],
            "adv_days_observed": 20,
            "price_as_of": _USED_DATE,
        }
        for t in tickers
    }
    rows = universe_fetch.apply_pass1(
        sec_tickers, sec_shares, market_data, governance=_gov(), as_of=_USED_DATE, observed_at=_GENERATED_AT
    )
    return universe_fetch.build_candidate_artifact(
        rows=rows,
        decision_date=_DECISION_DATE,
        price_basis_date=_PRICE_BASIS_DATE,
        used_date=_USED_DATE,
        observed_window_dates=[_USED_DATE, "2026-06-11"],
        generated_at=_GENERATED_AT,
        calendar_verification_status="pending_authoritative_cross_check",
    )


def _dates(n: int, *, as_of: str = _PRICE_BASIS_YMD) -> list[str]:
    end = datetime.strptime(as_of, "%Y-%m-%d").date()
    return [(end - timedelta(days=(n - 1 - idx))).isoformat() for idx in range(n)]


def _series(closes, volumes=None, *, spread: float = 0.5, as_of: str = _PRICE_BASIS_YMD,
            session: str = _SESSION, adjustment_mode: str = _ADJ) -> dict:
    pts = []
    for idx, (date, close) in enumerate(zip(_dates(len(closes), as_of=as_of), closes)):
        point = {"date": date, "high": float(close) + spread, "low": float(close) - spread, "close": float(close)}
        if volumes is not None:
            point["volume"] = float(volumes[idx])
        pts.append(point)
    return {"as_of": as_of, "session": session, "adjustment_mode": adjustment_mode, "points": pts}


def _base_series_map() -> dict:
    # AAPL chasing_extreme, MSFT none, GOOG warning (all scored); AMZN thin (insufficient_data); JPM ABSENT.
    return {
        "AAPL": _series(_PARA_CLOSES, _PARA_VOLS),
        "MSFT": _series(_ALT_CLOSES, [1_000_000.0] * len(_ALT_CLOSES)),
        "GOOG": _series(_WARN_CLOSES, [1_000_000.0] * len(_WARN_CLOSES)),
        "AMZN": _series(_THIN_CLOSES),
    }


def _series_packet(series_map, *, session: str = _SESSION, adjustment_mode: str = _ADJ,
                   grouped_session_count: int = 90, provider_id: str = "massive",
                   as_of: str = _PRICE_BASIS_YMD) -> dict:
    return {
        "schema_name": "us_short_batch5_full_universe_ohlcv_series_packet",
        "schema_version": "1.0.0",
        "generated_at": "2026-06-13T10:00:00+00:00",
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "packet_status": "full_universe_per_ticker_ohlcv_series_ready_for_local_overextension_projection",
            "full_market_reconstruction": True,
            "network_access_performed_by_packet_producer": True,
            "provider_calls_performed_by_packet_producer": True,
            "raw_payload_refs_gitignored": True,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "decision_clock": {
            "expected_decision_date": _DECISION_DATE,
            "candidate_price_basis_date": _PRICE_BASIS_DATE,
            "price_basis_date": as_of,
            "source_as_of": as_of,
        },
        "series_contract": {
            "session": session,
            "adjustment_mode": adjustment_mode,
            "as_of": as_of,
            "grouped_session_count": grouped_session_count,
        },
        "provenance": {
            "provider_id": provider_id,
            "endpoint_or_family": "grouped_daily",
            "source_as_of": as_of,
            "observed_at": "2026-06-13T10:00:00+00:00",
            "coverage_status": "full",
            "parser_status": "ok",
        },
        "series_by_ticker": series_map,
    }


class FullUniverseOverextensionProducerTest(unittest.TestCase):
    def setUp(self):
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_root = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        self._sample_root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_full_universe_overextension_20260709"
        )
        self.sample_root = Path(self._sample_root_context.__enter__())
        self.addCleanup(self._sample_root_context.__exit__, None, None, None)
        runner = importlib.import_module(RUNNER_MODULE)
        original_git_ignored = runner._git_ignored
        state_root = self.state_root.resolve()

        def _git_ignored_for_private_test(path):
            resolved = Path(path).resolve()
            if resolved == state_root or state_root in resolved.parents:
                return True
            return original_git_ignored(path)

        runner._git_ignored = _git_ignored_for_private_test
        self.addCleanup(setattr, runner, "_git_ignored", original_git_ignored)
        self.slug = f"test_full_universe_overext_{os.getpid()}_{self._testMethodName}"
        self.paths = {
            "candidate": self.state_root / f"{self.slug}_candidate.json",
            "packet": self.state_root / f"{self.slug}_ohlcv_packet.json",
            "projection": self.state_root / f"{self.slug}_overextension.json",
            "summary": self.sample_root / "full_universe_overextension_20260709" / self.slug / "summary.json",
        }
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        _write_json(self.paths["candidate"], _candidate_artifact(_ALL_ELIGIBLE))
        _write_json(self.paths["packet"], _series_packet(_base_series_map()))

    def tearDown(self):
        for path in self.paths.values():
            path.unlink(missing_ok=True)

    def _run_packet(self, **overrides):
        kwargs = {
            "candidate_artifact_path": self.paths["candidate"],
            "series_packet_path": self.paths["packet"],
            "output_projection_path": self.paths["projection"],
            "summary_path": self.paths["summary"],
            "generated_at": "2026-06-15T12:00:00+00:00",
        }
        kwargs.update(overrides)
        return _runner().run_packet(**kwargs)

    def test_runner_and_schemas_are_routed_artifacts(self):
        runner = _runner()
        self.assertTrue(runner.PACKET_SCHEMA_PATH.exists())
        self.assertTrue(runner.SUMMARY_SCHEMA_PATH.exists())

    def test_projects_all_eligible_with_honest_state_and_disposition_tally(self):
        summary = self._run_packet()

        self.assertEqual(summary["scope"]["status"], "full_universe_overextension_projection_written")
        self.assertFalse(summary["scope"]["provider_calls_performed_by_runner"])
        self.assertEqual(summary["candidate_universe"]["eligible_count"], 5)
        contract = summary["projection_contract"]
        self.assertEqual(contract["target_count"], 5)
        self.assertEqual(contract["overextension_scored_count"], 3)
        self.assertEqual(contract["disposition_counts"], {"scored": 3, "insufficient_data": 2})
        # state_counts tally ALL eligible (insufficient/absent are honestly state 'none'): none = MSFT+AMZN+JPM.
        self.assertEqual(contract["state_counts"], {"none": 3, "warning": 1, "chasing_extreme": 1})
        self.assertTrue(contract["real_ohlcv_source_consumed"])

        projection = _read_json(self.paths["projection"])
        self.assertEqual(projection["target_count"], 5)
        self.assertEqual(projection["scored_count"], 3)
        self.assertEqual(set(projection["overextension_by_ticker"]), set(_ALL_ELIGIBLE))
        states = {t: v["overextension_state"] for t, v in projection["overextension_by_ticker"].items()}
        self.assertEqual(states, {"AAPL": "chasing_extreme", "MSFT": "none", "GOOG": "warning",
                                  "AMZN": "none", "JPM": "none"})
        self.assertEqual(projection["overextension_by_ticker"]["AMZN"]["disposition"], "insufficient_data")
        self.assertEqual(projection["overextension_by_ticker"]["JPM"]["disposition"], "insufficient_data")
        self.assertEqual(
            set(projection),
            {"schema_name", "schema_version", "generated_at", "decision_clock", "source_contract",
             "candidate_binding", "overextension_by_ticker", "disposition_counts", "scored_count", "target_count"},
        )
        self.assertEqual(projection["schema_name"], "us_short_full_universe_overextension_projection")
        self.assertEqual(projection["candidate_binding"]["eligible_count"], 5)
        self.assertRegex(projection["candidate_binding"]["eligible_tickers_sha256"], r"^[0-9a-f]{64}$")

    def test_chasing_row_carries_slice_b_strip_flag_and_warning_carries_execution_flags(self):
        # the producer output is the map Slice B (compose_score_inputs) + cut 2c (_analyze_one) consume: a
        # chasing_extreme row must set strips_theme_score True (selection strip) while a warning row keeps the
        # theme score but carries the execution levers.
        self._run_packet()
        rows = _read_json(self.paths["projection"])["overextension_by_ticker"]
        self.assertIs(rows["AAPL"]["strips_theme_score"], True)
        self.assertEqual(rows["AAPL"]["execution_flags"], {})
        self.assertIs(rows["GOOG"]["strips_theme_score"], False)
        self.assertIs(rows["GOOG"]["execution_flags"]["force_pullback"], True)

    def test_huge_close_ticker_is_gracefully_dispositioned_not_bare_overflow(self):
        # a forged/corrupt huge close must NOT bare-crash (engine _finite OverflowError containment): the ticker
        # dispositions insufficient_data and the run still completes writing the projection.
        series_map = _base_series_map()
        series_map["MSFT"]["points"][10]["close"] = 10 ** 400
        _write_json(self.paths["packet"], _series_packet(series_map))

        summary = self._run_packet()
        self.assertEqual(summary["scope"]["status"], "full_universe_overextension_projection_written")
        rows = _read_json(self.paths["projection"])["overextension_by_ticker"]
        self.assertEqual(rows["MSFT"]["disposition"], "insufficient_data")

    def test_stray_non_eligible_ticker_fails_closed(self):
        series_map = _base_series_map()
        series_map["TSLA"] = _series(_ALT_CLOSES)   # not in the eligible set (no benchmarks exist here either)
        _write_json(self.paths["packet"], _series_packet(series_map))

        with self.assertRaises(_runner().FullUniverseOverextensionProducerError):
            self._run_packet()
        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_per_ticker_lookahead_as_of_fails_closed(self):
        series_map = _base_series_map()
        series_map["AAPL"]["as_of"] = "2026-06-15"   # future vs price_basis 2026-06-12 → look-ahead
        _write_json(self.paths["packet"], _series_packet(series_map))

        with self.assertRaises(_runner().FullUniverseOverextensionProducerError):
            self._run_packet()
        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_duplicate_canonical_series_key_fails_closed(self):
        series_map = _base_series_map()
        series_map["aapl"] = _series(_ALT_CLOSES)   # canonicalizes to AAPL → duplicate packet key
        _write_json(self.paths["packet"], _series_packet(series_map))

        with self.assertRaises(_runner().FullUniverseOverextensionProducerError):
            self._run_packet()
        self.assertFalse(self.paths["projection"].exists())

    def test_session_or_adjustment_mismatch_fails_closed(self):
        for field in ("session", "adjustment_mode"):
            with self.subTest(field=field):
                series_map = _base_series_map()
                series_map["AAPL"][field] = "OTHER"   # per-series clock != the contract → corrupt packet
                _write_json(self.paths["packet"], _series_packet(series_map))
                self.paths["projection"].unlink(missing_ok=True)
                self.paths["summary"].unlink(missing_ok=True)
                with self.assertRaises(_runner().FullUniverseOverextensionProducerError):
                    self._run_packet()
                self.assertFalse(self.paths["projection"].exists())

    def test_hostile_session_or_adjustment_string_is_rejected_before_write(self):
        # session / adjustment_mode flow into the TRACKED summary, so the packet schema bounds them to a safe
        # charset; a hostile value (URL / secret / ticker-list) fails closed at schema validation before any write.
        runner = _runner()
        for field, hostile in (("session", "s3://prod-secrets/massive.key"), ("adjustment_mode", "holdings=AAPL,MSFT")):
            with self.subTest(field=field):
                series_map = _base_series_map()
                for series in series_map.values():
                    series[field] = hostile
                _write_json(self.paths["packet"], _series_packet(series_map, **{field: hostile}))
                self.paths["projection"].unlink(missing_ok=True)
                self.paths["summary"].unlink(missing_ok=True)
                with self.assertRaises(runner.FullUniverseOverextensionProducerError):
                    self._run_packet()
                self.assertFalse(self.paths["projection"].exists())
                self.assertFalse(self.paths["summary"].exists())

    def test_tracked_summary_is_counts_only_no_secret_no_tickers(self):
        self._run_packet()
        text = self.paths["summary"].read_text(encoding="utf-8")
        lower = text.lower()
        for fragment in ("apikey=", "financialmodelingprep.com", "api.massive.com", "data.sec.gov",
                         "https://", "http://", "bearer ", "token=", '"points"', '"results"'):
            self.assertNotIn(fragment, lower)
        for ticker in _ALL_ELIGIBLE:
            self.assertNotIn(ticker, text)   # counts-only: no ticker lists in the tracked summary

    def test_summary_schema_rejects_scope_creep_claims(self):
        summary = self._run_packet()
        validator = Draft7Validator(_read_json(_runner().SUMMARY_SCHEMA_PATH))
        for path, value in (
            (("scope", "provider_calls_performed_by_runner"), True),
            (("scope", "full_market_call_performed"), True),
            (("prohibited_claims", "ship_gate_evidence_claimed"), True),
            (("storage", "summary_contains_ticker_lists"), True),
        ):
            mutated = json.loads(json.dumps(summary))
            cursor = mutated
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            self.assertGreater(len(list(validator.iter_errors(mutated))), 0, path)

    def test_preflight_only_validates_without_writing(self):
        result = _runner().run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            series_packet_path=self.paths["packet"],
            output_projection_path=self.paths["projection"],
            summary_path=self.paths["summary"],
            generated_at="2026-06-15T12:00:00+00:00",
        )
        self.assertEqual(result["scope"]["preflight_status"], "offline_preflight_passed")
        self.assertEqual(result["projection_preview"]["target_count"], 5)
        self.assertEqual(result["projection_preview"]["overextension_scored_count"], 3)
        self.assertEqual(result["projection_preview"]["state_counts"], {"none": 3, "warning": 1, "chasing_extreme": 1})
        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_output_projection_path_must_be_gitignored_state_json(self):
        with self.assertRaises(_runner().FullUniverseOverextensionProducerError):
            self._run_packet(output_projection_path=ROOT / "docs" / f"{self.slug}_overextension.json")

    def test_runner_level_clock_mismatch_fails_closed(self):
        # the RUNNER's own clock-coherence gates (distinct from the engine's per-series as_of check): a packet whose
        # decision_clock / series_contract / provenance clock disagrees with price_basis_date fails closed before writes.
        runner = _runner()
        for mutate in (
            lambda p: p["decision_clock"].__setitem__("source_as_of", "2026-06-11"),
            lambda p: p["series_contract"].__setitem__("as_of", "2026-06-11"),
            lambda p: p["provenance"].__setitem__("source_as_of", "2026-06-11"),
        ):
            with self.subTest(mutate=mutate):
                packet = _series_packet(_base_series_map())
                mutate(packet)   # a valid date, but != the packet price_basis_date 2026-06-12
                _write_json(self.paths["packet"], packet)
                self.paths["projection"].unlink(missing_ok=True)
                self.paths["summary"].unlink(missing_ok=True)
                with self.assertRaises(runner.FullUniverseOverextensionProducerError):
                    self._run_packet()
                self.assertFalse(self.paths["projection"].exists())

    def test_non_canonical_tracked_summary_path_fails_closed(self):
        # summary must be the canonical tracked docs path or a gitignored provider_samples path — a different
        # tracked docs location fails closed (no un-reviewed tracked artifact).
        with self.assertRaises(_runner().FullUniverseOverextensionProducerError):
            self._run_packet(summary_path=ROOT / "docs" / f"{self.slug}_not_canonical.json")

    def test_input_path_outside_state_us_short_fails_closed(self):
        with self.assertRaises(_runner().FullUniverseOverextensionProducerError):
            self._run_packet(series_packet_path=ROOT / "docs" / f"{self.slug}_packet.json")


if __name__ == "__main__":
    unittest.main()
