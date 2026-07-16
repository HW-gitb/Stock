import json
import tempfile
import unittest
from pathlib import Path

from engine.a_short_regime_action_comparison import (
    build_action_record, m67_provenance, merge_action_records, summarize_action_records,
    validate_action_record,
)
from engine.a_short_regime_classifier import FORWARD_RETURN_BASIS


def _regime_record(*, as_of="20260714", raw="defense", returns=None):
    values = {"h1": None, "h3": None, "h5": None, "h10": None}
    values.update(returns or {})
    pending = [h for h in ("h1", "h3", "h5", "h10") if values[h] is None]
    return {"as_of": as_of, "v14_3_raw_regime": raw, "v14_3_fired_rule": "broad_index_crash" if raw == "defense" else "residual", "forward_returns": values, "forward_returns_pending": pending, "backfill_complete": not pending, "forward_return_basis": dict(FORWARD_RETURN_BASIS)}


class RegimeActionComparisonTests(unittest.TestCase):
    def _source(self):
        return {"source_schema_name": "a_short_weekly_report", "source_as_of": "20260714", "source_sha256": "a" * 64, "candidate_build_count": 2}

    def _origin(self, *, decision_as_of="20260714", run_date=None):
        return {"decision_as_of": decision_as_of, "run_date": run_date or decision_as_of}

    def test_freezes_unknown_raw_and_effective_fallback_separately(self):
        row = build_action_record(regime_record=_regime_record(), raw_v14_2_regime="unknown", effective_v14_2_regime="shock", m67_source=self._source(), forward_origin=self._origin())
        self.assertEqual(row["raw_v14_2_regime"], "unknown")
        self.assertEqual(row["effective_v14_2_regime"], "shock")
        self.assertTrue(row["action_diverges"])
        self.assertEqual(row["baseline_action"]["max_exposure_pct"], 60)
        self.assertEqual(row["candidate_action"]["max_exposure_pct"], 0)

    def test_pending_and_action_relations_fail_closed(self):
        row = build_action_record(regime_record=_regime_record(), raw_v14_2_regime="shock", effective_v14_2_regime="shock", m67_source=self._source(), forward_origin=self._origin())
        row["action_diverges"] = False
        with self.assertRaises(ValueError):
            validate_action_record(row)

    def test_forward_eligibility_is_derived_and_cannot_be_self_labelled(self):
        row = build_action_record(regime_record=_regime_record(), raw_v14_2_regime="shock",
                                  effective_v14_2_regime="shock", m67_source=self._source(),
                                  forward_origin=self._origin(run_date="20260715"))
        self.assertFalse(row["forward_eligible"])
        row["forward_eligible"] = True
        with self.assertRaises(ValueError):
            validate_action_record(row)

    def test_same_week_conflict_is_rejected(self):
        a = build_action_record(regime_record=_regime_record(), raw_v14_2_regime="shock", effective_v14_2_regime="shock", m67_source=self._source(), forward_origin=self._origin())
        b = dict(a)
        b["raw_v14_2_regime"] = "attack"
        with self.assertRaises(ValueError):
            merge_action_records([a], b)

    def test_summary_needs_full_forward_gate(self):
        rows = []
        for i in range(12):
            as_of = f"202607{i+1:02d}"
            row = build_action_record(regime_record=_regime_record(as_of=as_of, returns={"h1": 1.0, "h3": 1.0, "h5": 1.0, "h10": -1.0}), raw_v14_2_regime="shock", effective_v14_2_regime="shock", m67_source=self._source(), forward_origin=self._origin(decision_as_of=as_of))
            rows.append(row)
        self.assertEqual(summarize_action_records(rows)["status"], "review_candidate_preferred")

    def test_summary_rejects_multiple_forward_records_from_one_run_date(self):
        rows = []
        for i in range(2):
            as_of = f"202607{i + 1:02d}"
            rows.append(build_action_record(
                regime_record=_regime_record(as_of=as_of), raw_v14_2_regime="shock",
                effective_v14_2_regime="shock", m67_source=self._source(),
                forward_origin=self._origin(decision_as_of="20260714", run_date="20260714")))
        with self.assertRaises(ValueError):
            summarize_action_records(rows)

    def test_historical_replay_is_never_counted_as_forward_evidence(self):
        row = build_action_record(
            regime_record=_regime_record(returns={"h1": 1.0, "h3": 1.0, "h5": 1.0, "h10": 1.0}),
            raw_v14_2_regime="shock", effective_v14_2_regime="shock", m67_source=self._source(),
            forward_origin=self._origin(run_date="20260715"))
        summary = summarize_action_records([row])
        self.assertEqual(summary["total_forward_weeks"], 0)
        self.assertEqual(summary["historical_not_counted"], 1)
        self.assertEqual(summary["status"], "accumulating")

    def test_m67_provenance_persists_digest_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weekly.json"
            path.write_text(json.dumps({"schema_name": "a_short_weekly_report", "as_of": "20260714", "reports": [{"row_source": "egs_candidate", "m67": {"table": {"操作": "建仓"}}}]}), encoding="utf-8")
            result = m67_provenance(path, as_of="20260714")
        self.assertEqual(result["candidate_build_count"], 1)
        self.assertEqual(result["source_as_of"], "20260714")
        self.assertEqual(len(result["source_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
