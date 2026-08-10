from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import unittest

from engine import us_short_llm_theme_discovery_policy_decision as decision
from engine import us_short_serenity_structural_theme_annotation as annotation
from tests.provider.us_short_private_test_root import temporary_us_short_directory


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "us_short_serenity_structural_theme_annotation_v0_1.json"
PACKET_REF = "docs/us_short_soft_discovery_query_quality_probe_packet_20260809.json"
LEGACY_SOURCE_PACKET_REF = "docs/us_short_soft_discovery_query_quality_probe_packet_20260730.json"
PACKET_ID = "packet_20260809_blade3_fixture"
FIXED_NOW = datetime(2026, 8, 10, tzinfo=timezone.utc)


def _reverse_mappings(value):
    if isinstance(value, dict):
        return {key: _reverse_mappings(value[key]) for key in reversed(list(value))}
    if isinstance(value, list):
        return [_reverse_mappings(item) for item in value]
    return value


def _copy_newline_normalized(source: Path, target: Path) -> None:
    """Copy a tracked text artifact with LF newlines.

    The fixture's ``input_artifact_sha256`` and the decision id derived from it
    are digests of these bytes.  Copying the checkout verbatim would make both
    depend on how the working tree happens to render newlines, which is green in
    one worktree and red in another for identical content.
    """
    target.write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))


@contextmanager
def _materialized_root(*, policy_version: str, disposition: str = "KEEP"):
    with temporary_us_short_directory(ROOT, Path("state") / "us_short") as temp_dir:
        root = Path(temp_dir)
        packet_path = root / PACKET_REF
        packet_path.parent.mkdir(parents=True, exist_ok=True)
        _copy_newline_normalized(ROOT / PACKET_REF, packet_path)
        if policy_version == "soft_discovery_query_policy_v0.2.0":
            legacy_path = root / LEGACY_SOURCE_PACKET_REF
            legacy_path.parent.mkdir(parents=True, exist_ok=True)
            _copy_newline_normalized(ROOT / LEGACY_SOURCE_PACKET_REF, legacy_path)
        result = decision.build_policy_decision_result(
            input_packet_id=PACKET_ID,
            input_packet_ref=PACKET_REF,
            input_packet_sha256=hashlib.sha256(packet_path.read_bytes()).hexdigest(),
            decision_date="20260809",
            policy_version=policy_version,
            policy_disposition=disposition,
            generated_at="2026-08-10T00:00:00+00:00",
            root=root,
        )
        result_path = root / "docs" / (
            f"us_short_llm_theme_discovery_policy_decision_{PACKET_ID}_20260809_{policy_version}.json"
        )
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        yield root, result


class SerenityStructuralThemeAnnotationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def _build_annotation(self, root, result, *, policy_version=None):
        selected_policy_version = policy_version or result["canonical_decision"]["policy_version"]
        return annotation.build_structural_theme_annotation(
            upstream_input_packet_id=PACKET_ID,
            upstream_decision_result_id=result["decision_result_id"],
            upstream_policy_version=selected_policy_version,
            upstream_decision_date="20260809",
            source_cutoff_at="2026-08-09T23:59:00+00:00",
            annotation_author_kind="human",
            prompt_or_protocol_id="serenity_blade3_rubric_v0.1.0",
            model_identity=None,
            generated_at="2026-08-10T00:00:00+00:00",
            review_status="candidate_offline",
            valid_through="2030-01-01T00:00:00+00:00",
            canonical_annotation=self.fixture["canonical_annotation"],
            root=root,
        )

    def test_offline_fixture_is_valid_and_effect_free(self):
        with _materialized_root(policy_version="soft_discovery_query_policy_v0.3.0") as (root, result):
            self.assertEqual(result["decision_result_id"], self.fixture["identity_envelope"]["upstream_decision_result_id"])
            self.assertTrue(annotation.validate_annotation(self.fixture, root=root, now=FIXED_NOW))
            self.assertEqual(self.fixture["effect_boundary"], annotation.EFFECT_BOUNDARY)
            self.assertFalse(self.fixture["canonical_annotation"]["structural_fit_candidate"])
            self.assertNotIn("policy_disposition", self.fixture)
            self.assertNotIn("policy_disposition", self.fixture["identity_envelope"])
            self.assertNotIn("policy_disposition", self.fixture["canonical_annotation"])

    def test_same_input_binds_v02_and_v03_without_cross_read(self):
        with _materialized_root(policy_version="soft_discovery_query_policy_v0.2.0") as (root, result_v02):
            annotation_v02 = self._build_annotation(root, result_v02)
            self.assertTrue(annotation.validate_annotation(annotation_v02, root=root, now=FIXED_NOW))
            crossed = deepcopy(annotation_v02)
            crossed["identity_envelope"]["upstream_decision_result_id"] = self.fixture["identity_envelope"]["upstream_decision_result_id"]
            with self.assertRaises(annotation.StructuralAnnotationError):
                annotation.validate_annotation(crossed, root=root, now=FIXED_NOW)
        with _materialized_root(policy_version="soft_discovery_query_policy_v0.3.0") as (root, result_v03):
            annotation_v03 = self._build_annotation(root, result_v03)
            self.assertTrue(annotation.validate_annotation(annotation_v03, root=root, now=FIXED_NOW))
            self.assertNotEqual(result_v02["decision_result_id"], result_v03["decision_result_id"])
            self.assertNotEqual(
                annotation_v02["identity_envelope"]["upstream_policy_version"],
                annotation_v03["identity_envelope"]["upstream_policy_version"],
            )

    def test_missing_unknown_and_mismatched_identity_fail_closed(self):
        with _materialized_root(policy_version="soft_discovery_query_policy_v0.3.0") as (root, _):
            for field in (
                "upstream_input_packet_id",
                "upstream_decision_result_id",
                "upstream_policy_version",
                "upstream_decision_date",
            ):
                missing = deepcopy(self.fixture)
                del missing["identity_envelope"][field]
                with self.assertRaises(annotation.StructuralAnnotationError):
                    annotation.validate_annotation(missing, root=root, now=FIXED_NOW)
            unknown_policy = deepcopy(self.fixture)
            unknown_policy["identity_envelope"]["upstream_policy_version"] = "soft_discovery_query_policy_v9.9.9"
            with self.assertRaises(annotation.StructuralAnnotationError):
                annotation.validate_annotation(unknown_policy, root=root, now=FIXED_NOW)
            wrong_result = deepcopy(self.fixture)
            wrong_result["identity_envelope"]["upstream_decision_result_id"] = "f" * 64
            with self.assertRaises(annotation.StructuralAnnotationError):
                annotation.validate_annotation(wrong_result, root=root, now=FIXED_NOW)
            wrong_input = deepcopy(self.fixture)
            wrong_input["identity_envelope"]["input_artifact_sha256"] = "0" * 64
            with self.assertRaises(annotation.StructuralAnnotationError):
                annotation.validate_annotation(wrong_input, root=root, now=FIXED_NOW)
            wrong_date = deepcopy(self.fixture)
            wrong_date["identity_envelope"]["upstream_decision_date"] = "20260810"
            with self.assertRaises(annotation.StructuralAnnotationError):
                annotation.validate_annotation(wrong_date, root=root, now=FIXED_NOW)

    def test_legacy_locator_does_not_rewrite_frozen_packet(self):
        with _materialized_root(policy_version="soft_discovery_query_policy_v0.2.0") as (root, result):
            source_path = root / LEGACY_SOURCE_PACKET_REF
            before = source_path.read_bytes()
            payload = self._build_annotation(root, result)
            self.assertTrue(annotation.validate_annotation(payload, root=root, now=FIXED_NOW))
            self.assertEqual(before, source_path.read_bytes())

    def test_policy_disposition_is_not_annotation_content(self):
        with _materialized_root(policy_version="soft_discovery_query_policy_v0.3.0", disposition="KEEP") as (root, result_keep):
            keep = self._build_annotation(root, result_keep)
        with _materialized_root(policy_version="soft_discovery_query_policy_v0.3.0", disposition="REVIEW") as (root, result_review):
            review = self._build_annotation(root, result_review)
        self.assertNotEqual(result_keep["decision_result_id"], result_review["decision_result_id"])
        self.assertEqual(annotation.canonical_annotation_bytes(keep), annotation.canonical_annotation_bytes(review))
        self.assertNotIn("policy_disposition", annotation.canonical_annotation_bytes(keep).decode("utf-8"))

    def test_rubric_mismatch_and_expired_annotation_fail(self):
        with _materialized_root(policy_version="soft_discovery_query_policy_v0.3.0") as (root, _):
            rubric_mismatch = deepcopy(self.fixture)
            rubric_mismatch["identity_envelope"]["rubric_version"] = "serenity_annotation_rubric_v9.9.9"
            with self.assertRaises(annotation.StructuralAnnotationError):
                annotation.validate_annotation(rubric_mismatch, root=root, now=FIXED_NOW)
            expired = deepcopy(self.fixture)
            with self.assertRaises(annotation.StructuralAnnotationError):
                annotation.validate_annotation(
                    expired,
                    root=root,
                    now=datetime(2031, 1, 1, tzinfo=timezone.utc),
                )

    def test_effect_flags_and_missing_source_ref_are_negative_controls(self):
        with _materialized_root(policy_version="soft_discovery_query_policy_v0.3.0") as (root, _):
            effect_enabled = deepcopy(self.fixture)
            effect_enabled["effect_boundary"]["scoring_eligible"] = True
            with self.assertRaises(annotation.StructuralAnnotationError):
                annotation.validate_annotation(effect_enabled, root=root, now=FIXED_NOW)
            missing_source = deepcopy(self.fixture)
            del missing_source["canonical_annotation"]["claims"][0]["source_ref_ids"]
            with self.assertRaises(annotation.StructuralAnnotationError):
                annotation.validate_annotation(missing_source, root=root, now=FIXED_NOW)
            candidate_enabled = deepcopy(self.fixture)
            candidate_enabled["canonical_annotation"]["structural_fit_candidate"] = True
            with self.assertRaises(annotation.StructuralAnnotationError):
                annotation.validate_annotation(candidate_enabled, root=root, now=FIXED_NOW)

    def test_canonicalizer_is_byte_stable(self):
        with _materialized_root(policy_version="soft_discovery_query_policy_v0.3.0") as (root, _):
            reordered = _reverse_mappings(self.fixture)
            self.assertEqual(
                annotation.canonicalize_annotation(self.fixture, root=root, now=FIXED_NOW),
                annotation.canonicalize_annotation(reordered, root=root, now=FIXED_NOW),
            )


if __name__ == "__main__":
    unittest.main()
