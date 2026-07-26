from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


MODULE = "runners.us_short_llm_theme_discovery"
STATE_DIR = ROOT / "state" / "us_short"


def _runner():
    return importlib.import_module(MODULE)


def _payload():
    return {
        "source_refs": [
            {"source_id": "web:ai-storage-1", "source_type": "web", "observed_at": "2026-06-12T12:00:00Z"},
            {"source_id": "x:ai-storage-1", "source_type": "x", "observed_at": "2026-06-12T12:05:00Z"},
            {"source_id": "llm:ai-storage-1", "source_type": "llm", "observed_at": "2026-06-12T12:10:00Z"},
        ],
        "themes": [
            {
                "theme_id": "ai_storage",
                "display_name": "AI storage",
                "summary": "A provisional cross-industry theme discovered from local source references.",
                "observed_at": "2026-06-12T12:15:00Z",
                "source_ref_ids": ["web:ai-storage-1", "x:ai-storage-1", "llm:ai-storage-1"],
                "members": [
                    {"ticker": "msft", "source_ref_ids": ["llm:ai-storage-1"]},
                    {"ticker": "AAPL", "source_ref_ids": ["web:ai-storage-1", "x:ai-storage-1"]},
                ],
            }
        ],
    }


class OfflineLLMThemeDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.slug = f"test_llm_theme_discovery_{os.getpid()}_{self._testMethodName}"
        self.tempdir = tempfile.TemporaryDirectory(dir=ROOT / "provider_samples")
        self.test_state_dir = Path(self.tempdir.name) / "state" / "us_short"
        self.runner_module = _runner()
        self.state_patch = mock.patch.object(self.runner_module, "STATE_US_SHORT_DIR", self.test_state_dir)
        self.state_patch.start()
        self.test_state_dir.mkdir(parents=True, exist_ok=True)
        self.input_path = self.test_state_dir / f"{self.slug}_input.json"
        self.output_path = self.runner_module.default_output_path("20260615")
        self.input_path.write_text(json.dumps(_payload(), ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.state_patch.stop()
        self.tempdir.cleanup()

    def test_run_packet_freezes_source_bound_provisional_artifact_without_effect(self):
        runner = _runner()
        summary = runner.run_packet(
            input_path=self.input_path,
            output_path=self.output_path,
            expected_decision_date="20260615",
            generated_at="2026-06-12T12:20:00Z",
        )
        self.assertTrue(self.output_path.exists())
        self.assertEqual(summary["status"], "offline_discovery_artifact_written")
        self.assertFalse(summary["network_access_performed"])
        self.assertFalse(summary["scoring_or_top15_effect"])
        self.assertFalse(summary["operation_advice_effect"])
        artifact = json.loads(self.output_path.read_text(encoding="utf-8"))
        self.assertEqual(artifact["discovery_contract"]["membership_status"], "provisional_unvalidated")
        self.assertFalse(artifact["discovery_contract"]["scoring_eligible"])
        self.assertFalse(artifact["discovery_contract"]["top15_effect_enabled"])
        self.assertFalse(artifact["discovery_contract"]["operation_advice_effect_enabled"])
        self.assertEqual(artifact["themes"][0]["members"][0]["ticker"], "AAPL")
        self.assertEqual(artifact["themes"][0]["status"], "provisional_discovered")
        self.assertEqual(artifact["themes"][0]["market_confirmation_status"], "not_run")

    def test_preflight_does_not_write_output(self):
        runner = _runner()
        result = runner.run_preflight(
            input_path=self.input_path,
            output_path=self.output_path,
            expected_decision_date="20260615",
            generated_at="2026-06-12T12:20:00Z",
        )
        self.assertEqual(result["status"], "offline_preflight_passed")
        self.assertEqual(result["theme_count"], 1)
        self.assertEqual(result["member_count"], 2)
        self.assertFalse(self.output_path.exists())

    def test_future_source_is_rejected_before_write(self):
        payload = _payload()
        payload["source_refs"][0]["observed_at"] = "2026-06-15T13:31:00Z"  # 09:31 ET after the open
        self.input_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(_runner().LLMThemeDiscoveryError, "before the decision open"):
            _runner().run_packet(
                input_path=self.input_path,
                output_path=self.output_path,
                expected_decision_date="20260615",
                generated_at="2026-06-12T12:20:00Z",
            )
        self.assertFalse(self.output_path.exists())

    def test_member_source_must_be_bound_to_theme_sources(self):
        payload = _payload()
        payload["themes"][0]["members"][0]["source_ref_ids"] = ["web:not-declared"]
        self.input_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(_runner().LLMThemeDiscoveryError):
            _runner().run_preflight(
                input_path=self.input_path,
                output_path=self.output_path,
                expected_decision_date="20260615",
                generated_at="2026-06-12T12:20:00Z",
            )

    def test_operational_score_injection_is_rejected(self):
        payload = _payload()
        payload["themes"][0]["score"] = 99
        self.input_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(_runner().LLMThemeDiscoveryError, "operational fields"):
            _runner().run_preflight(
                input_path=self.input_path,
                output_path=self.output_path,
                expected_decision_date="20260615",
                generated_at="2026-06-12T12:20:00Z",
            )

    def test_non_ascii_or_a_share_identity_is_rejected(self):
        for ticker in ("ſAPL", "000001.SZ"):
            payload = _payload()
            payload["themes"][0]["members"][0]["ticker"] = ticker
            self.input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(_runner().LLMThemeDiscoveryError):
                _runner().run_preflight(
                    input_path=self.input_path,
                    output_path=self.output_path,
                    expected_decision_date="20260615",
                    generated_at="2026-06-12T12:20:00Z",
                )

    def test_secret_like_source_id_is_rejected(self):
        payload = _payload()
        payload["source_refs"][0]["source_id"] = "web:api_key"
        self.input_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(_runner().LLMThemeDiscoveryError):
            _runner().run_preflight(
                input_path=self.input_path,
                output_path=self.output_path,
                expected_decision_date="20260615",
                generated_at="2026-06-12T12:20:00Z",
                )

    def test_semantic_ingest_guards_reject_each_poisoned_shape(self):
        """Optional-s: every semantic ingest boundary has a direct dying input control."""
        mutations = {
            "duplicate_source": lambda p: p["source_refs"].append(dict(p["source_refs"][0])),
            "invalid_source_id": lambda p: p["source_refs"][0].update(source_id="web bad"),
            "duplicate_theme": lambda p: p["themes"].append(json.loads(json.dumps(p["themes"][0]))),
            "invalid_theme_id": lambda p: p["themes"][0].update(theme_id="bad theme"),
            "duplicate_member": lambda p: p["themes"][0]["members"].append(dict(p["themes"][0]["members"][0])),
            "unbound_member_ref": lambda p: p["themes"][0]["members"][0].update(source_ref_ids=["web:missing"]),
            "source_after_theme": lambda p: p["source_refs"][0].update(observed_at="2026-06-12T12:30:00Z"),
            "empty_members": lambda p: p["themes"][0].update(members=[]),
            "overlong_display": lambda p: p["themes"][0].update(display_name="x" * 121),
            "overlong_summary": lambda p: p["themes"][0].update(summary="x" * 1001),
            "operational_key": lambda p: p["themes"][0].update(score=1),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                payload = _payload()
                mutate(payload)
                self.input_path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(self.runner_module.LLMThemeDiscoveryError):
                    self.runner_module.run_preflight(
                        input_path=self.input_path, output_path=self.output_path,
                        expected_decision_date="20260615", generated_at="2026-06-12T12:20:00Z",
                    )

    def test_persisted_text_requires_a_credential_value_not_an_ordinary_financial_phrase(self):
        for phrase in (
            "Password manager stocks surge.", "Secret Service contract lifts defense names.",
            "Bearer bonds rally while Access token sales grow.",
        ):
            with self.subTest(phrase=phrase):
                payload = _payload()
                payload["themes"][0]["summary"] = phrase
                self.input_path.write_text(json.dumps(payload), encoding="utf-8")
                self.assertEqual(self.runner_module.run_preflight(
                    input_path=self.input_path, output_path=self.output_path,
                    expected_decision_date="20260615", generated_at="2026-06-12T12:20:00Z",
                )["theme_count"], 1)
        payload = _payload()
        payload["themes"][0]["summary"] = "provider api_key=real-looking-fixture must not persist"
        self.input_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(self.runner_module.LLMThemeDiscoveryError, "credential-like"):
            self.runner_module.run_preflight(
                input_path=self.input_path, output_path=self.output_path,
                expected_decision_date="20260615", generated_at="2026-06-12T12:20:00Z",
            )
        payload = _payload()
        payload["themes"][0]["summary"] = 'provider api_key: "real-looking-fixture" must not persist'
        self.input_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(self.runner_module.LLMThemeDiscoveryError, "credential-like"):
            self.runner_module.run_preflight(
                input_path=self.input_path, output_path=self.output_path,
                expected_decision_date="20260615", generated_at="2026-06-12T12:20:00Z",
            )

    def test_extreme_timestamp_is_wrapped_as_discovery_error(self):
        with self.assertRaises(self.runner_module.LLMThemeDiscoveryError):
            self.runner_module._parse_rfc3339(
                "0001-01-01T00:00:00+14:00", field="fixture_time",
            )

    def test_knife1_sink_rejects_unencodable_payload_without_temp_residue(self):
        payload = _payload()
        payload["themes"][0]["summary"] = "bad\ud800"
        self.input_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(self.runner_module.LLMThemeDiscoveryError):
            self.runner_module.run_packet(
                input_path=self.input_path, output_path=self.output_path,
                expected_decision_date="20260615", generated_at="2026-06-12T12:20:00Z",
            )
        self.assertFalse(self.output_path.exists())
        self.assertEqual(list(self.test_state_dir.glob("*.tmp")), [])

    def test_shared_publish_policy_guard_terms_are_independently_live(self):
        """K3-R47: each policy term has its own control, not a sibling guard."""
        from runners import us_short_discovery_publish_policy as policy

        valid_slot = self.test_state_dir / "us_short_llm_theme_discovery_20260615.json"
        with self.assertRaises(policy.DiscoveryPublishPolicyError):
            policy.validate_exact_decision_slot(
                ROOT / "docs" / "outside.json", ROOT / "docs" / "outside.json",
                root=ROOT, state_dir=self.test_state_dir,
            )
        with self.assertRaises(policy.DiscoveryPublishPolicyError):
            policy.validate_exact_decision_slot(
                self.test_state_dir / "not-json.txt", self.test_state_dir / "not-json.txt",
                root=ROOT, state_dir=self.test_state_dir,
            )
        with mock.patch.object(policy, "_gitignored", return_value=False):
            with self.assertRaises(policy.DiscoveryPublishPolicyError):
                policy.validate_exact_decision_slot(
                    valid_slot, valid_slot, root=ROOT, state_dir=self.test_state_dir,
                )
        valid_slot.write_bytes(b"{not-json")
        with self.assertRaises(policy.DiscoveryPublishPolicyError):
            policy.write_immutable_json({"evidence": "safe"}, valid_slot)
        valid_slot.unlink()
        with self.assertRaises(policy.DiscoveryPublishPolicyError):
            policy.write_immutable_json({"evidence": "bad\ud800"}, valid_slot)
        self.assertFalse(valid_slot.exists())
        self.assertEqual(list(self.test_state_dir.glob("*.tmp")), [])

        self.assertFalse(policy.write_immutable_json({"evidence": "frozen"}, valid_slot))
        frozen = valid_slot.read_bytes()
        with self.assertRaises(policy.DiscoveryPublishPolicyError):
            policy.write_immutable_json({"evidence": "bad\ud800"}, valid_slot)
        self.assertEqual(valid_slot.read_bytes(), frozen)

        race_slot = self.test_state_dir / "race.json"
        with mock.patch.object(policy.os, "link", side_effect=FileExistsError):
            with mock.patch.object(policy, "frozen_artifact_matches", return_value=True) as existing:
                self.assertTrue(policy.write_immutable_json({"evidence": "safe"}, race_slot))
        existing.assert_called_once_with(
                    {"evidence": "safe"}, race_slot,
                    clock_keys=policy.CLOCK_KEYS_ARTIFACT, recursive=False, verify=None,
                )
        self.assertFalse(race_slot.exists())
        self.assertEqual(list(self.test_state_dir.glob("*.tmp")), [])

    def test_publish_policy_refuses_a_target_outside_this_lane_state_dir(self):
        """The containment term has its own control: the slot pin alone would also refuse, so this
        aims at a path the pin would accept as `expected_path` and only containment can reject."""
        from runners import us_short_discovery_publish_policy as policy

        outside = ROOT / "state" / "a_short" / "us_short_llm_theme_discovery_20260615.json"
        with self.assertRaisesRegex(policy.DiscoveryPublishPolicyError, "must stay under state/us_short"):
            policy.validate_exact_decision_slot(
                outside, outside, root=ROOT, state_dir=self.test_state_dir, gitignored=lambda path: True,
            )
        # The one MUTABLE writer carries the same policy, so a second caller cannot aim it at
        # another lane's state or at a tracked file.
        with self.assertRaisesRegex(policy.DiscoveryPublishPolicyError, "must stay under state/us_short"):
            policy.write_mutable_ledger(
                {"ledger": 1}, outside, root=ROOT, state_dir=self.test_state_dir,
                gitignored=lambda path: True,
            )
        self.assertFalse(outside.exists())
        # ...and it may only replace its own mutable family, never an immutable artifact slot.
        immutable = self.test_state_dir / 'us_short_llm_theme_discovery_20260615.json'
        self.assertFalse(policy.write_immutable_json({'evidence': 'frozen'}, immutable))
        frozen = immutable.read_bytes()
        with self.assertRaisesRegex(policy.DiscoveryPublishPolicyError, 'only replace the reservation ledger'):
            policy.write_mutable_ledger(
                {'ledger': 1}, immutable, root=ROOT, state_dir=self.test_state_dir,
                gitignored=lambda path: True,
            )
        self.assertEqual(immutable.read_bytes(), frozen)

    def test_lost_race_against_different_evidence_is_refused_not_reused(self):
        """The `FileExistsError` fallback must re-check evidence: returning `True` there would
        silently accept a winner holding DIFFERENT evidence for the same decision date."""
        from runners import us_short_discovery_publish_policy as policy

        slot = self.test_state_dir / "us_short_llm_theme_discovery_20260615.json"
        slot.write_text(json.dumps({"generated_at": "t0", "evidence": "rival week"}) + "\n", encoding="utf-8")
        rival = slot.read_bytes()
        real_exists = policy.Path.exists
        first_look = {"done": False}

        def free_on_first_look(path_self):
            # Simulate the race: the slot looks free, then a rival creates it before the link.
            if path_self == slot and not first_look["done"]:
                first_look["done"] = True
                return False
            return real_exists(path_self)

        with mock.patch.object(policy.Path, "exists", free_on_first_look):
            with mock.patch.object(policy.os, "link", side_effect=FileExistsError):
                with self.assertRaisesRegex(policy.DiscoveryPublishPolicyError, "different evidence"):
                    policy.write_immutable_json({"generated_at": "t1", "evidence": "mine"}, slot)
        self.assertEqual(slot.read_bytes(), rival)
        self.assertEqual(sorted(path.name for path in self.test_state_dir.glob(".*")), [])

    def test_pair_publish_rolls_back_when_a_concurrent_winner_holds_different_evidence(self):
        """The policy-error rollback branch needs its own control: the existing tests force an
        `OSError`, which exercises only the other branch, so a half-published pair could survive."""
        from runners import us_short_discovery_publish_policy as policy

        first = self.test_state_dir / "us_short_llm_theme_discovery_20260615.json"
        second = self.test_state_dir / "us_short_llm_theme_discovery_20260616.json"
        second.write_text(json.dumps({"generated_at": "t0", "evidence": "rival"}) + "\n", encoding="utf-8")
        real_exists = policy.Path.exists
        real_link = policy.os.link
        first_look = {"done": False}
        calls = {"n": 0}

        def free_on_first_look(path_self):
            if path_self == second and not first_look["done"]:
                first_look["done"] = True
                return False
            return real_exists(path_self)

        def second_link_loses(source, target):
            calls["n"] += 1
            if calls["n"] == 2:
                raise FileExistsError("concurrent winner")
            real_link(source, target)

        with mock.patch.object(policy.Path, "exists", free_on_first_look):
            with mock.patch.object(policy.os, "link", side_effect=second_link_loses):
                with self.assertRaisesRegex(policy.DiscoveryPublishPolicyError, "different evidence"):
                    policy.publish_immutable_pair(
                        [({"generated_at": "t1", "evidence": "mine-first"}, first),
                         ({"generated_at": "t1", "evidence": "mine-second"}, second)],
                        clock_keys=policy.CLOCK_KEYS_ARTIFACT, recursive=False,
                    )
        self.assertFalse(first.exists(), "a refused pair must not leave its first slot published")
        self.assertEqual(sorted(path.name for path in self.test_state_dir.glob(".*")), [])

    def test_only_own_decision_date_slot_can_be_published(self):
        runner = self.runner_module
        bad_paths = (
            self.test_state_dir / "us_short_llm_theme_discovery_20260616.json",
            self.test_state_dir / "us_short_llm_theme_discovery_web_20260615.json",
            self.test_state_dir / "us_short_llm_theme_discovery_web_tavily_20260615_budget.json",
            self.test_state_dir / "lifecycle" / "operator_state.json",
        )
        for output_path in bad_paths:
            with self.subTest(output_path=output_path.name):
                with self.assertRaisesRegex(runner.LLMThemeDiscoveryError, "decision-date artifact slot"):
                    runner.run_preflight(
                        input_path=self.input_path, output_path=output_path,
                        expected_decision_date="20260615", generated_at="2026-06-12T12:20:00Z",
                    )

    def test_immutable_retry_reuses_only_same_evidence(self):
        runner = self.runner_module
        first = runner.run_packet(
            input_path=self.input_path, output_path=self.output_path,
            expected_decision_date="20260615", generated_at="2026-06-12T12:20:00Z",
        )
        frozen = self.output_path.read_bytes()
        retry = runner.run_packet(
            input_path=self.input_path, output_path=self.output_path,
            expected_decision_date="20260615", generated_at="2026-06-12T12:25:00Z",
        )
        self.assertEqual(first["status"], "offline_discovery_artifact_written")
        self.assertEqual(retry["status"], "offline_discovery_artifact_reused")
        self.assertEqual(self.output_path.read_bytes(), frozen)
        payload = _payload()
        payload["themes"][0]["summary"] = "Changed source evidence after the frozen decision packet."
        self.input_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(runner.LLMThemeDiscoveryError, "different evidence"):
            runner.run_packet(
                input_path=self.input_path, output_path=self.output_path,
                expected_decision_date="20260615", generated_at="2026-06-12T12:30:00Z",
            )

    def test_credential_bearing_url_is_rejected_before_persisting(self):
        for locator in (
            "https://example.invalid/article?sig=fixture",
            "example.invalid/article?sig=fixture",
        ):
            with self.subTest(locator=locator):
                payload = _payload()
                payload["themes"][0]["summary"] = f"Fixture URL {locator} must not persist."
                self.input_path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(self.runner_module.LLMThemeDiscoveryError, "credential-like"):
                    self.runner_module.run_preflight(
                        input_path=self.input_path, output_path=self.output_path,
                        expected_decision_date="20260615", generated_at="2026-06-12T12:20:00Z",
                    )
                self.assertFalse(self.output_path.exists())


if __name__ == "__main__":
    unittest.main()
