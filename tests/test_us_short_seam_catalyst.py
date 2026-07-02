import unittest
from importlib import import_module

from engine.us_short_catalyst import load_catalyst_governance
from engine.us_short_catalyst_source import resolve_catalyst_signals
from engine.us_short_core_score import core_score
from engine.us_short_seam_catalyst import (
    BINDING_PATH,
    COVERAGE_DISPOSITIONS,
    OUTPUT_KEYS,
    PRODUCER_REFS,
    PROJECTION_POLICY,
    CatalystSeamError,
    load_binding,
    project_catalyst_block,
)


AS_OF = "20260630"
GOV = load_catalyst_governance()
_SRC_PROV = {
    "earnings": ("fmp", "earnings_surprises"),
    "analyst": ("fmp", "analyst_estimate_revisions"),
}


def _prov(source="earnings", **kw):
    provider, endpoint = _SRC_PROV[source]
    out = {
        "provider_id": provider,
        "endpoint_or_filing_type": endpoint,
        "source_as_of": AS_OF,
        "observed_at": "2026-06-30T08:00:00-04:00",
        "coverage_status": "full",
        "parser_status": "ok",
        "lineage_ref": f"{provider}:{endpoint}:{AS_OF}#rec1",
    }
    out.update(kw)
    return out


def _earn(pct=15.0, date="20260625", prov=None):
    return {
        "earnings_surprise_pct": pct,
        "earnings_report_date": date,
        "provenance": _prov("earnings") if prov is None else prov,
    }


def _analyst(net=4, date="20260624", prov=None):
    return {
        "analyst_revision_net": net,
        "analyst_revision_date": date,
        "provenance": _prov("analyst") if prov is None else prov,
    }


class _EqBombStr(str):
    __hash__ = str.__hash__

    def __eq__(self, other):
        raise RuntimeError("eq trap")

    def __ne__(self, other):
        raise RuntimeError("ne trap")


class CatalystSeamProjectionTest(unittest.TestCase):
    def test_project_catalyst_block_accepts_real_source_output_across_dispositions(self):
        source = resolve_catalyst_signals(
            as_of=AS_OF,
            earnings={
                "aapl": _earn(15.0),
                "msft": _earn("15"),  # emitted by source, rejected by catalyst_block value rules -> neutral
                "jpm": _earn(prov=_prov("earnings", coverage_status="partial")),
            },
            analyst={"AAPL": _analyst(4)},
        )

        result = project_catalyst_block(
            catalyst_source_result=source,
            governance=GOV,
            as_of=AS_OF,
            target_tickers=["AAPL", "MSFT", "JPM", "AMZN"],
        )

        self.assertEqual(result["target_count"], 4)
        self.assertEqual(result["scored_count"], 1)
        self.assertGreater(result["catalyst_block_by_ticker"]["AAPL"], GOV["neutral_catalyst_score"])
        self.assertEqual(result["neutral_fill_tickers"], ["MSFT", "JPM", "AMZN"])
        self.assertEqual(
            result["coverage"],
            {
                "AAPL": "scored_realized_catalyst",
                "MSFT": "neutral_no_realized_catalyst",
                "JPM": "neutral_source_excluded",
                "AMZN": "neutral_missing_catalyst_source",
            },
        )

    def test_project_catalyst_block_rejects_missing_signal_provenance(self):
        source = resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL": _earn()})
        del source["provenance"]["AAPL"]["earnings_surprise_pct"]

        with self.assertRaisesRegex(CatalystSeamError, "provenance"):
            project_catalyst_block(
                catalyst_source_result=source,
                governance=GOV,
                as_of=AS_OF,
                target_tickers=["AAPL"],
            )

    def test_project_catalyst_block_rejects_signal_excluded_overlap(self):
        source = resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL": _earn()})
        source["excluded"]["AAPL"] = {"earnings_surprise_pct": "coverage=partial/parser=ok"}

        with self.assertRaisesRegex(CatalystSeamError, "overlap"):
            project_catalyst_block(
                catalyst_source_result=source,
                governance=GOV,
                as_of=AS_OF,
                target_tickers=["AAPL"],
            )

    def test_project_catalyst_block_rejects_duplicate_target_identity(self):
        source = resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL": _earn()})

        with self.assertRaisesRegex(CatalystSeamError, "duplicate"):
            project_catalyst_block(
                catalyst_source_result=source,
                governance=GOV,
                as_of=AS_OF,
                target_tickers=["AAPL", " aapl "],
            )

    def test_project_catalyst_block_rejects_bad_source_result_shape(self):
        source = resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL": _earn()})
        source["extra"] = True

        with self.assertRaisesRegex(CatalystSeamError, "keys"):
            project_catalyst_block(
                catalyst_source_result=source,
                governance=GOV,
                as_of=AS_OF,
                target_tickers=["AAPL"],
            )

    def test_project_catalyst_block_contains_hostile_provenance_values(self):
        source = resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL": _earn()})
        source["provenance"]["AAPL"]["earnings_surprise_pct"]["provider_id"] = _EqBombStr("fmp")

        with self.assertRaises(CatalystSeamError):
            project_catalyst_block(
                catalyst_source_result=source,
                governance=GOV,
                as_of=AS_OF,
                target_tickers=["AAPL"],
            )

    def test_project_catalyst_block_binding_conformance(self):
        binding = load_binding()

        self.assertTrue(str(BINDING_PATH).endswith(binding["artifact_id"] + ".json"))
        self.assertEqual(OUTPUT_KEYS, tuple(binding["output_contract"]["required_keys"]))
        self.assertEqual(PRODUCER_REFS, tuple(binding["producer_refs"]))
        self.assertEqual(PROJECTION_POLICY, binding["projection_policy"])
        self.assertEqual(COVERAGE_DISPOSITIONS, tuple(binding["output_contract"]["coverage_dispositions"]))
        self.assertEqual(
            binding["authorization_boundary"],
            {
                "provider_call": False,
                "live_data": False,
                "datahub_write": False,
                "production_runner": False,
                "broker_or_order_execution": False,
            },
        )

    def test_project_catalyst_block_binding_producer_refs_resolve_to_callables(self):
        for ref in load_binding()["producer_refs"]:
            module_path, func_name = ref.split("::", 1)
            module_name = module_path[:-3].replace("/", ".")
            self.assertTrue(callable(getattr(import_module(module_name), func_name)), ref)

    def test_project_catalyst_block_can_feed_core_score_with_neutral_fill(self):
        source = resolve_catalyst_signals(as_of=AS_OF, earnings={"MSFT": _earn("15")})
        result = project_catalyst_block(
            catalyst_source_result=source,
            governance=GOV,
            as_of=AS_OF,
            target_tickers=["MSFT"],
        )

        scored = core_score({"momentum": 50.0, "theme": 50.0})

        self.assertEqual(result["catalyst_block_by_ticker"], {})
        self.assertEqual(result["neutral_fill_tickers"], ["MSFT"])
        self.assertIn("catalyst", scored["missing_blocks"])
        self.assertEqual(scored["blocks_used"]["catalyst"], GOV["neutral_catalyst_score"])


if __name__ == "__main__":
    unittest.main()
