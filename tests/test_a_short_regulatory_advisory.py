from __future__ import annotations

import unittest

from engine.a_short_regulatory_advisory import (
    RegulatoryAdvisoryContractError,
    attach_confirmations,
    event_fingerprint,
    holding_universe_digest,
    resolve_regulatory_advisory,
    validate_confirmation_document,
    validate_holding_confirmation_document,
)


AS_OF = "20260714"
DIGEST = "a" * 64
TS_CODE = "600000.SH"


def _event(*, url: str = "https://example.invalid/notice.pdf", severity: str = "high") -> dict:
    return {
        "source": "cninfo",
        "title": "official notice",
        "category": "regulatory",
        "disclosure_date": "20260710",
        "url_or_pdf": url,
        "risk_type": "investigation",
        "severity": severity,
    }


def _semantic(*events: dict) -> dict:
    return {"status": "risk", "had_pit_announcements": True, "events": list(events)}


def _record(decision: str) -> dict:
    return {
        "decision": decision,
        "reviewed_at": "2026-07-14T09:30:00+08:00",
        "note": "Checked the official notice manually.",
    }


class RegulatoryAdvisoryContractTests(unittest.TestCase):
    def test_unconfirmed_high_is_pending(self):
        state = resolve_regulatory_advisory(_semantic(_event()), TS_CODE)
        self.assertEqual(state["status"], "pending_confirmation")
        self.assertEqual(state["high_material"], [])
        self.assertEqual(len(state["pending_high"]), 1)

    def test_confirmed_material_full_evidence_is_advisory_veto_eligible(self):
        event = _event()
        fingerprint = event_fingerprint(TS_CODE, event)
        semantic, matched = attach_confirmations(
            _semantic(event), TS_CODE, {(TS_CODE, fingerprint): _record("confirmed_material")}
        )
        state = resolve_regulatory_advisory(semantic, TS_CODE)
        self.assertEqual(matched, {(TS_CODE, fingerprint)})
        self.assertEqual(state["status"], "confirmed_material")
        self.assertEqual(state["high_material"], [event])
        self.assertEqual(state["pending_high"], [])

    def test_confirmed_not_material_does_not_create_veto(self):
        event = _event()
        fingerprint = event_fingerprint(TS_CODE, event)
        semantic, _ = attach_confirmations(
            _semantic(event), TS_CODE, {(TS_CODE, fingerprint): _record("confirmed_not_material")}
        )
        state = resolve_regulatory_advisory(semantic, TS_CODE)
        self.assertEqual(state["status"], "confirmed_not_material")
        self.assertEqual(state["high_material"], [])
        self.assertEqual(state["confirmed_not_material_count"], 1)

    def test_provider_supplied_advisory_is_discarded_before_confirmation_binding(self):
        event = _event()
        fingerprint = event_fingerprint(TS_CODE, event)
        semantic = _semantic(event)
        semantic["regulatory_advisory"] = {"event_decisions": [
            {"event_fingerprint": fingerprint, "decision": "confirmed_material"},
        ]}
        attached, matched = attach_confirmations(semantic, TS_CODE, {})
        state = resolve_regulatory_advisory(attached, TS_CODE)
        self.assertEqual(matched, set())
        self.assertNotIn("regulatory_advisory", attached)
        self.assertEqual(state["status"], "pending_confirmation")
        self.assertEqual(state["high_material"], [])

    def test_blank_url_remains_pending_even_when_marked_material(self):
        event = _event(url="")
        fingerprint = event_fingerprint(TS_CODE, event)
        semantic, _ = attach_confirmations(
            _semantic(event), TS_CODE, {(TS_CODE, fingerprint): _record("confirmed_material")}
        )
        state = resolve_regulatory_advisory(semantic, TS_CODE)
        self.assertEqual(state["status"], "pending_confirmation")
        self.assertEqual(state["high_material"], [])
        self.assertEqual(state["pending_high"], [event])

    def test_stale_or_duplicate_event_decision_fails_closed(self):
        event = _event()
        semantic = _semantic(event)
        fingerprint = event_fingerprint(TS_CODE, event)
        semantic["regulatory_advisory"] = {"event_decisions": [
            {"event_fingerprint": fingerprint, "decision": "confirmed_material"},
            {"event_fingerprint": fingerprint, "decision": "confirmed_not_material"},
        ]}
        with self.assertRaises(RegulatoryAdvisoryContractError):
            resolve_regulatory_advisory(semantic, TS_CODE)
        semantic["regulatory_advisory"] = {"event_decisions": [
            {"event_fingerprint": "0" * 64, "decision": "confirmed_material"},
        ]}
        with self.assertRaises(RegulatoryAdvisoryContractError):
            resolve_regulatory_advisory(semantic, TS_CODE)

    def test_confirmation_document_binds_as_of_digest_and_one_event_once(self):
        event = _event()
        fingerprint = event_fingerprint(TS_CODE, event)
        payload = {
            "schema_name": "a_short_regulatory_advisory_confirmation",
            "schema_version": "1.0.0",
            "as_of": AS_OF,
            "candidate_digest": DIGEST,
            "confirmations": [{
                "ts_code": TS_CODE,
                "event_fingerprint": fingerprint,
                **_record("confirmed_material"),
            }],
        }
        mapped = validate_confirmation_document(payload, AS_OF, DIGEST)
        self.assertEqual(mapped[(TS_CODE, fingerprint)]["decision"], "confirmed_material")
        with self.assertRaises(RegulatoryAdvisoryContractError):
            validate_confirmation_document(payload, "20260711", DIGEST)
        with self.assertRaises(RegulatoryAdvisoryContractError):
            validate_confirmation_document(payload, AS_OF, "b" * 64)
        payload["confirmations"][0]["reviewed_at"] = "2026-07-14"
        with self.assertRaises(RegulatoryAdvisoryContractError):
            validate_confirmation_document(payload, AS_OF, DIGEST)
        payload["confirmations"][0]["reviewed_at"] = "2026-07-14T09:30:00+08:00"
        payload["confirmations"].append(dict(payload["confirmations"][0]))
        with self.assertRaises(RegulatoryAdvisoryContractError):
            validate_confirmation_document(payload, AS_OF, DIGEST)

    def test_holding_confirmation_binds_account_snapshot_universe_and_event(self):
        positions = [{"ts_code": TS_CODE}, {"ts_code": "000001.SZ"}]
        universe_digest = holding_universe_digest(positions)
        event = _event()
        fingerprint = event_fingerprint(TS_CODE, event)
        payload = {
            "schema_name": "a_short_regulatory_holding_confirmation",
            "schema_version": "1.0.0",
            "as_of": AS_OF,
            "account_snapshot_digest": DIGEST,
            "holding_universe_digest": universe_digest,
            "confirmations": [{
                "ts_code": TS_CODE,
                "event_fingerprint": fingerprint,
                **_record("confirmed_material"),
            }],
            "boundary": {
                "advisory_only": True,
                "modifies_egs_or_rule6": False,
                "automates_order": False,
                "private_account_only": True,
            },
        }
        mapped = validate_holding_confirmation_document(
            payload, AS_OF, DIGEST, universe_digest, {TS_CODE, "000001.SZ"}
        )
        self.assertEqual(mapped[(TS_CODE, fingerprint)]["decision"], "confirmed_material")
        self.assertEqual(holding_universe_digest(list(reversed(positions))), universe_digest)
        with self.assertRaises(RegulatoryAdvisoryContractError):
            validate_holding_confirmation_document(
                payload, AS_OF, "b" * 64, universe_digest, {TS_CODE, "000001.SZ"}
            )
        with self.assertRaises(RegulatoryAdvisoryContractError):
            validate_holding_confirmation_document(
                payload, AS_OF, DIGEST, "0" * 64, {TS_CODE, "000001.SZ"}
            )
        payload["confirmations"][0]["ts_code"] = "600001.SH"
        with self.assertRaises(RegulatoryAdvisoryContractError):
            validate_holding_confirmation_document(
                payload, AS_OF, DIGEST, universe_digest, {TS_CODE, "000001.SZ"}
            )


if __name__ == "__main__":
    unittest.main()
