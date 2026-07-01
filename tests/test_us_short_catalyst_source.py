# -*- coding: utf-8 -*-
"""Tests for engine/us_short_catalyst_source.py (§4.2 catalyst-source offline layer, batch5 Cut 4 offline half).

Pure/offline. Covers the single US-ticker identity policy; exact-str/hostile-key hardening (non-str, mixed, and
str-subclass __repr__/__eq__ bombs all raise CatalystSourceError, never a raw exception); §3.1/§3.5 provenance +
PIT chronology validation against the frozen binding (missing/extra field, wrong provider-endpoint, bad clocks,
observe-before-event, future observation/source past the decision as_of, bad enums, free-form lineage all fail
closed); coverage/parser EMISSION fitness (only full+ok scores; missing/failed/partial/degraded excluded); the
engine-const == binding conformance; and an end-to-end feed into catalyst_block.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_catalyst_source as cs  # noqa: E402
from engine.us_short_catalyst_source import resolve_catalyst_signals, CatalystSourceError  # noqa: E402
from engine.us_short_catalyst import catalyst_block, load_catalyst_governance  # noqa: E402

AS_OF = "20260630"
_SRC_PROV = {"earnings": ("fmp", "earnings_surprises"),
             "analyst": ("fmp", "analyst_estimate_revisions"),
             "event_8k": ("sec_edgar", "form_8k"),
             "semantic": ("llm_advisory", "semantic_advisory")}


def _prov(source="earnings", **kw):
    provider, endpoint = _SRC_PROV[source]
    # observed_at is a tz-aware RFC3339 INSTANT (premarket 08:00 ET on as_of, before the 09:30 ET cutoff);
    # source_as_of / event dates stay YYYYMMDD. lineage prefix uses source_as_of (not observed_at).
    p = {"provider_id": provider, "endpoint_or_filing_type": endpoint,
         "source_as_of": "20260630", "observed_at": "2026-06-30T08:00:00-04:00",
         "coverage_status": "full", "parser_status": "ok",
         "lineage_ref": f"{provider}:{endpoint}:20260630#rec1"}
    p.update(kw)
    return p


def _earn(pct=15.0, date="20260625", prov=None):
    return {"earnings_surprise_pct": pct, "earnings_report_date": date,
            "provenance": _prov("earnings") if prov is None else prov}


def _analyst(net=4, date="20260624", prov=None):
    return {"analyst_revision_net": net, "analyst_revision_date": date,
            "provenance": _prov("analyst") if prov is None else prov}


def _e8k(cls="positive", date="20260626", prov=None):
    return {"event_8k_class": cls, "event_8k_date": date, "provenance": _prov("event_8k") if prov is None else prov}


class TestMergeIdentity(unittest.TestCase):
    def test_merge_and_canonicalize(self):
        out = resolve_catalyst_signals(as_of=AS_OF, earnings={"aapl": _earn()}, analyst={" AAPL ": _analyst()})
        self.assertEqual(set(out["signals"]), {"AAPL"})
        self.assertEqual(out["signals"]["AAPL"], {
            "earnings_surprise_pct": 15.0, "earnings_report_date": "20260625",
            "analyst_revision_net": 4, "analyst_revision_date": "20260624"})

    def test_provenance_carried_per_signal(self):
        out = resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL": _earn()}, event_8k={"AAPL": _e8k()})
        self.assertEqual(out["provenance"]["AAPL"]["earnings_surprise_pct"]["provider_id"], "fmp")
        self.assertEqual(set(out["provenance"]["AAPL"]["earnings_surprise_pct"]), cs._PROVENANCE_FIELDS)

    def test_ashare_unicode_nonstring_excluded(self):
        out = resolve_catalyst_signals(as_of=AS_OF, earnings={
            "AAPL": _earn(), "000001.SZ": _earn(), "ſ": _earn(), 123: _earn(), None: _earn()})
        self.assertEqual(set(out["signals"]), {"AAPL"})

    def test_alias_collision_raises(self):
        with self.assertRaises(CatalystSourceError):
            resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL": _earn(), "aapl": _earn()})

    def test_class_share_kept(self):
        self.assertEqual(set(resolve_catalyst_signals(as_of=AS_OF, earnings={"BRK.B": _earn()})["signals"]),
                         {"BRK.B"})


class _ReprBombNonStr:
    __hash__ = object.__hash__
    def __eq__(self, o): return self is o
    def __repr__(self): raise RuntimeError("repr trap (non-str)")


class _ReprBombStr(str):
    def __repr__(self): raise RuntimeError("repr trap (str subclass)")


class _EqBombStr(str):
    __hash__ = str.__hash__
    def __eq__(self, o): raise RuntimeError("eq trap (str subclass)")


class _StripBombStr(str):
    def strip(self, *a): raise RuntimeError("strip trap (outer ticker str subclass)")


class TestFailClosed(unittest.TestCase):
    def test_bad_or_missing_as_of_raises(self):
        for bad in ("2026-06-30", "20261399", None, ""):
            with self.assertRaises(CatalystSourceError):
                resolve_catalyst_signals(as_of=bad, earnings={"AAPL": _earn()})

    def test_nondict_payload_or_record_raises(self):
        with self.assertRaises(CatalystSourceError):
            resolve_catalyst_signals(as_of=AS_OF, earnings="nope")
        with self.assertRaises(CatalystSourceError):
            resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL": "nope"})

    def test_partial_or_foreign_record_raises(self):
        for rec in ({"earnings_surprise_pct": 1.0, "provenance": _prov()},               # no date
                    {"earnings_report_date": "20260625", "provenance": _prov()},          # no value
                    {"earnings_surprise_pct": 1.0, "earnings_report_date": "20260625"},   # no provenance
                    {"earnings_surprise_pct": 1.0, "earnings_report_date": "20260625",
                     "provenance": _prov(), "event_8k_class": "positive"}):               # foreign extra
            with self.assertRaises(CatalystSourceError):
                resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL": rec})

    def test_hostile_keys_fail_closed(self):
        # non-str repr-bomb, str-subclass repr-bomb, AND str-subclass eq-bomb must all raise CatalystSourceError
        # (never a raw RuntimeError) — type(key) is str rejects subclasses before any set/format touches them. The
        # bomb keys use values that don't collide with the real keys' hashes (a colliding value would trip the
        # bomb at the caller's own dict literal, not in the engine).
        for bomb in (_ReprBombNonStr(), _ReprBombStr("z_repr_foreign"), _EqBombStr("z_eq_foreign")):
            rec = {"earnings_surprise_pct": 1.0, "earnings_report_date": "20260625", "provenance": _prov(),
                   bomb: "x"}
            with self.assertRaises(CatalystSourceError):
                resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL": rec})

    def test_hostile_outer_ticker_key_excluded_not_crash(self):
        # a str-subclass TICKER key whose .strip()/.isascii()/.upper() is hostile must be EXCLUDED (dropped)
        # before canonical_us_ticker touches it — never a raw exception out of resolve.
        out = resolve_catalyst_signals(as_of=AS_OF, earnings={_StripBombStr("aapl"): _earn(), "MSFT": _earn()})
        self.assertEqual(set(out["signals"]), {"MSFT"})   # bomb ticker dropped, no crash

    def test_hostile_provenance_subdict_key_raises(self):
        # a str-subclass key INSIDE the provenance dict (hostile __eq__) must raise CatalystSourceError, not leak
        # a raw exception through the provenance set() comparison.
        p = {(_EqBombStr("provider_id") if k == "provider_id" else k): v for k, v in _prov("earnings").items()}
        with self.assertRaises(CatalystSourceError):
            resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL": _earn(prov=p)})

    def test_none_sources_empty(self):
        self.assertEqual(resolve_catalyst_signals(as_of=AS_OF),
                         {"signals": {}, "provenance": {}, "excluded": {}})


class TestProvenanceValidation(unittest.TestCase):
    def test_shape_provider_endpoint_enum_lineage_raise(self):
        short = _prov(); del short["lineage_ref"]
        for bad in (short, {}, "notdict",
                    _prov("earnings", provider_id="sec_edgar"),
                    _prov("earnings", endpoint_or_filing_type="form_8k"),
                    _prov("earnings", coverage_status="unknown"),
                    _prov("earnings", parser_status="maybe"),
                    _prov("earnings", lineage_ref="trust-me"),                 # free-form
                    _prov("earnings", lineage_ref="fmp:earnings_surprises:20260630#"),   # empty record id
                    _prov("earnings", lineage_ref="wrong:prefix:20260630#r1")):
            with self.assertRaises(CatalystSourceError):
                resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL": _earn(prov=bad)})

    def test_bad_clock_formats_raise(self):
        # source_as_of must be YYYYMMDD; observed_at must be a tz-aware RFC3339 INSTANT (§3.5 sub-date cutoff)
        for bad in (_prov("earnings", source_as_of="2026-06-30"),
                    _prov("earnings", observed_at="20260630"),                # bare YYYYMMDD (no tz instant)
                    _prov("earnings", observed_at="2026-06-30"),              # date-only
                    _prov("earnings", observed_at="2026-06-30T08:00:00"),     # naive (no offset)
                    _prov("earnings", observed_at=20260630)):                 # non-str
            with self.assertRaises(CatalystSourceError):
                resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL": _earn(prov=bad)})

    def test_pit_chronology_and_cutoff_raise(self):
        def run(prov):
            resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL": _earn(date="20260625", prov=prov)})
        # observe-before-event: observed ET date 20260620 < event 20260625
        with self.assertRaises(CatalystSourceError):
            run(_prov("earnings", observed_at="2026-06-20T08:00:00-04:00"))
        # A-clock: post-open same-date observation (10:00 ET > 09:30 ET decision cutoff) is look-ahead
        with self.assertRaises(CatalystSourceError):
            run(_prov("earnings", observed_at="2026-06-30T10:00:00-04:00"))
        # future observation (ET date after as_of, also past the cutoff)
        with self.assertRaises(CatalystSourceError):
            run(_prov("earnings", observed_at="2026-07-01T08:00:00-04:00",
                      source_as_of="20260701", lineage_ref="fmp:earnings_surprises:20260701#r1"))
        # source_as_of after decision as_of
        with self.assertRaises(CatalystSourceError):
            run(_prov("earnings", source_as_of="20260701", lineage_ref="fmp:earnings_surprises:20260701#r1"))
        # source snapshot predates the observation it contains (observed 20260630 > source_as_of 20260601)
        with self.assertRaises(CatalystSourceError):
            run(_prov("earnings", source_as_of="20260601", lineage_ref="fmp:earnings_surprises:20260601#r1"))

    def test_premarket_cutoff_and_utc_offset_accepted(self):
        # premarket 08:00 ET accepted; a UTC-Z instant whose ET date is on/before as_of (11:00Z = 07:00 ET) accepted
        for obs in ("2026-06-30T08:00:00-04:00", "2026-06-30T11:00:00Z"):
            out = resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL":
                _earn(date="20260625", prov=_prov("earnings", observed_at=obs))})
            self.assertIn("AAPL", out["signals"])

    def test_half_open_cutoff_boundary(self):
        # HALF-OPEN [prior_close, decision_open), §2.1/§3.5: observed must be STRICTLY before the 09:30 ET open.
        def run(obs):
            return resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL":
                _earn(date="20260625", prov=_prov("earnings", observed_at=obs))})
        # exactly 09:30:00 ET (+ its UTC-Z equivalent + 1µs after) is OUT-OF-WINDOW -> reject (== resolve_canonical_asof)
        for obs in ("2026-06-30T09:30:00-04:00", "2026-06-30T13:30:00Z", "2026-06-30T09:30:00.000001-04:00"):
            with self.assertRaises(CatalystSourceError):
                run(obs)
        # one microsecond before the open (+ its UTC-Z equivalent) is in-window -> accept
        for obs in ("2026-06-30T09:29:59.999999-04:00", "2026-06-30T13:29:59Z"):
            self.assertIn("AAPL", run(obs)["signals"])

    def test_coverage_parser_value_type_raises(self):
        # a list/dict/bool/int/str-subclass coverage or parser VALUE must raise CatalystSourceError, never a raw
        # TypeError (unhashable) or a hash bomb — the enum value is type-checked before membership (residual-2 B)
        for bad_val in (["full"], {"x": 1}, True, 1, _EqBombStr("full")):
            with self.assertRaises(CatalystSourceError):
                resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL": _earn(prov=_prov("earnings", coverage_status=bad_val))})
            with self.assertRaises(CatalystSourceError):
                resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL": _earn(prov=_prov("earnings", parser_status=bad_val))})

    def test_all_provenance_values_exact_str(self):
        # WHOLE-CLASS residual-2 B: EVERY provenance/date VALUE compared or parsed must be exact str; a str-subclass
        # (hostile __eq__/__le__ OR benign) must raise CatalystSourceError, never a raw exception via !=/<=/parse.
        class _StrSub(str):
            pass
        for sub in (_EqBombStr, _ReprBombStr, _StrSub):     # incl a hostile __repr__ bomb (the error-message {!r} leg)
            for field, val in (("provider_id", "fmp"), ("endpoint_or_filing_type", "earnings_surprises"),
                               ("source_as_of", "20260630"), ("observed_at", "2026-06-30T08:00:00-04:00"),
                               ("lineage_ref", "fmp:earnings_surprises:20260630#r1")):
                with self.assertRaises(CatalystSourceError):
                    resolve_catalyst_signals(as_of=AS_OF, earnings={
                        "AAPL": _earn(prov=_prov("earnings", **{field: sub(val)}))})
            with self.assertRaises(CatalystSourceError):    # event_date = the record's date_key value (msg must not {!r} it)
                resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL": _earn(date=sub("20260625"))})
            with self.assertRaises(CatalystSourceError):    # as_of decision clock (msg must not echo it via {!r})
                resolve_catalyst_signals(as_of=sub("20260630"), earnings=None)

    def test_valid_provenance_passes(self):
        out = resolve_catalyst_signals(as_of=AS_OF, analyst={"AAPL": _analyst()})
        self.assertEqual(set(out["provenance"]["AAPL"]), {"analyst_revision_net"})


class TestCoverageParserEmission(unittest.TestCase):
    def test_missing_or_failed_excluded_not_scored(self):
        for prov in (_prov("earnings", coverage_status="missing"),
                     _prov("earnings", parser_status="failed"),
                     _prov("earnings", coverage_status="partial"),
                     _prov("earnings", parser_status="degraded")):
            out = resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL": _earn(prov=prov)})
            self.assertNotIn("AAPL", out["signals"])          # not score-ready
            self.assertIn("earnings_surprise_pct", out["excluded"]["AAPL"])

    def test_full_ok_emitted(self):
        out = resolve_catalyst_signals(as_of=AS_OF, earnings={"AAPL": _earn()})
        self.assertIn("earnings_surprise_pct", out["signals"]["AAPL"])
        self.assertNotIn("AAPL", out["excluded"])


class TestEngineIntegration(unittest.TestCase):
    def setUp(self):
        self.gov = load_catalyst_governance()

    def test_feeds_catalyst_block_realized_beat(self):
        out = resolve_catalyst_signals(as_of=AS_OF, earnings={"aapl": _earn(pct=15.0, date="20260625")})
        block = catalyst_block(out["signals"], self.gov, as_of=AS_OF)
        self.assertGreater(block["catalyst_block"]["AAPL"], self.gov["neutral_catalyst_score"])
        self.assertEqual(block["coverage_matrix"]["AAPL"]["realized"], ["earnings_surprise_pct"])


class TestBindingConformance(unittest.TestCase):
    """engine module consts MUST equal the frozen binding artifact (no drift)."""

    def test_engine_consts_match_binding(self):
        b = json.loads(cs.BINDING_PATH.read_text(encoding="utf-8"))
        self.assertEqual(b["schema_name"], "us_short_catalyst_source_binding")
        self.assertEqual(set(cs._SOURCES), set(b["sources"]))
        for name, (vk, dk, prov, ep) in cs._SOURCES.items():
            self.assertEqual(b["sources"][name],
                             {"value_key": vk, "date_key": dk, "provider_id": prov, "endpoint_or_filing_type": ep})
        self.assertEqual(set(b["provenance_required_fields"]), cs._PROVENANCE_FIELDS)
        self.assertEqual(set(b["coverage_status_allowed"]), cs._COVERAGE_ALLOWED)
        self.assertEqual(set(b["parser_status_allowed"]), cs._PARSER_ALLOWED)
        self.assertFalse(b["authorization_boundary"]["provider_calls_authorized"])
        self.assertTrue(b["authorization_boundary"]["sr_provider_001_gated"])
        pc = b["pit_clock_contract"]                       # PIT clock contract triangulated == engine consts
        self.assertEqual(pc["decision_timezone"], cs._DECISION_TZ_NAME)
        self.assertEqual(pc["decision_cutoff_et"],
                         f"{cs._DECISION_CUTOFF_HHMM[0]:02d}:{cs._DECISION_CUTOFF_HHMM[1]:02d}")
        self.assertEqual(pc["observed_at_format"], "rfc3339_tz_aware_instant")
        # residual-3 B: the PIT/emission/lineage POLICIES are machine-frozen + triangulated (not just vocab/text)
        self.assertEqual(pc["observed_at_cutoff_operator"], cs._CUTOFF_OPERATOR)     # strictly_before (half-open)
        self.assertEqual(tuple(pc["chronology_order"]), cs._CHRONOLOGY_ORDER)
        self.assertEqual(b["emission_fitness"]["score_ready_coverage_status"], cs._COVERAGE_EMIT)
        self.assertEqual(b["emission_fitness"]["score_ready_parser_status"], cs._PARSER_EMIT)
        self.assertEqual(b["lineage_ref_format"]["structure"], cs._LINEAGE_REF_FORMAT)


if __name__ == "__main__":
    unittest.main()
