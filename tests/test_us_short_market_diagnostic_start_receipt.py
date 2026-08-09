from __future__ import annotations

import copy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import engine.us_short_market_diagnostic_lifecycle as lifecycle
import engine.us_short_market_diagnostic_start_receipt as receipts
from engine.us_short_market_diagnostic_lifecycle import (
    MarketDiagnosticLifecycleError,
    load_lifecycle_register,
    persist_settled_weekly_record,
)
from engine.us_short_market_diagnostic_start_receipt import (
    DiagnosticStartReceiptError,
    RECEIPT_FILENAME,
    build_start_receipt,
    design_authority_sha256,
    issue_start_receipt,
    load_start_receipt,
    start_receipt_sha256,
    validate_start_receipt,
)
from engine.us_short_model_paper_portfolio import canonical_json_bytes
from tests.test_us_short_market_diagnostic import _weekly_rows


NOTIFICATION = {
    "issued_at": "2025-12-29T00:00:00+00:00",
    "issuer": "codex",
    "notification_text": "US-short 26-week diagnostic design is complete.",
}
LEGAL_EPOCH = "us-short-26w-alt"
# After the notification and after the frozen week: minting is legal from here.
AS_OF = "20260731"


def _issue(root, row, **overrides):
    kwargs = {
        "diagnostic_epoch": row["diagnostic_epoch"],
        "completion_notification": dict(NOTIFICATION),
        "first_decision_date": row["decision_date"],
        "as_of_date": AS_OF,
        "root": root,
    }
    kwargs.update(overrides)
    return issue_start_receipt(**kwargs)


def _receipt(row, **overrides):
    kwargs = {
        "diagnostic_epoch": row["diagnostic_epoch"],
        "completion_notification": dict(NOTIFICATION),
        "first_decision_date": row["decision_date"],
        "as_of_date": AS_OF,
    }
    kwargs.update(overrides)
    return build_start_receipt(**kwargs)


class StartReceiptTest(unittest.TestCase):
    """The clock has one door; these tests are about who may open it."""

    def setUp(self) -> None:
        self.rows = _weekly_rows()
        self.row = self.rows[0]

    # ---- the gate on the store -------------------------------------------------

    def test_week_one_is_refused_without_a_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            with self.assertRaises(MarketDiagnosticLifecycleError) as ctx:
                persist_settled_weekly_record(self.row, root=root)
            self.assertIn("start receipt", str(ctx.exception))
            self.assertFalse((root / "lifecycle_register.json").exists())

    def test_orphan_recovery_cannot_open_the_clock_either(self) -> None:
        """The second door: an orphan week-1 file with no register."""

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            orphan = root / "weeks" / self.row["decision_date"] / "weekly_record.json"
            orphan.parent.mkdir(parents=True, exist_ok=True)
            orphan_bytes = canonical_json_bytes(self.row)
            orphan.write_bytes(orphan_bytes)
            with mock.patch.object(
                lifecycle,
                "_require_start_receipt",
                wraps=lifecycle._require_start_receipt,
            ) as gate:
                with self.assertRaises(MarketDiagnosticLifecycleError) as ctx:
                    persist_settled_weekly_record(self.row, root=root)
            gate.assert_called_once()
            self.assertIn("start receipt", str(ctx.exception))
            self.assertFalse((root / "lifecycle_register.json").exists())
            self.assertEqual(orphan_bytes, orphan.read_bytes())

    def test_a_receipt_opens_the_clock_and_its_digest_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            issued = _issue(root, self.row)
            self.assertEqual("issued", issued["status"])
            result = persist_settled_weekly_record(self.row, root=root)
            self.assertEqual(1, result["calendar_week_index"])
            register = load_lifecycle_register(root)
            self.assertEqual(issued["receipt_sha256"], register["start_receipt_sha256"])

    def test_a_receipt_for_another_week_does_not_authorize_this_one(self) -> None:
        """A receipt is not a blanket permit; it names one decision date."""

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            _issue(root, self.row, first_decision_date=self.rows[3]["decision_date"])
            with self.assertRaises(MarketDiagnosticLifecycleError) as ctx:
                persist_settled_weekly_record(self.row, root=root)
            self.assertIn("decision date", str(ctx.exception))

    def test_the_frozen_week_must_be_a_week_this_track_actually_decides_on(self) -> None:
        """The anchor sets the weekday of all twenty-six weeks, so it is the clock.

        Refusing only Saturday and Sunday let a Wednesday -- and a Friday -- anchor
        a track that decides on Mondays. Every week after it inherits the wrong day
        by construction, because the clock advances by adding seven.
        """

        monday = self.row["decision_date"]
        self.assertEqual(0, datetime.strptime(monday, "%Y%m%d").weekday())
        self.assertIsNotNone(_receipt(self.row))          # control: the Monday mints

        for wrong, weekday in (("20260107", "Wednesday"), ("20260109", "Friday"),
                               ("20260110", "Saturday")):
            with self.subTest(weekday):
                with self.assertRaises(DiagnosticStartReceiptError) as ctx:
                    _receipt(self.row, first_decision_date=wrong)
                self.assertIn("canonical decision week", str(ctx.exception))

    def test_a_notification_that_has_not_happened_yet_authorizes_nothing(self) -> None:
        """Every other date check reasons FROM issued_at, so a future one moves them all.

        The anchor may not precede the notification and may not run away from it.
        Both bounds travel with a notification dated 2099, which re-legalizes the
        back-fill they exist to refuse -- and this is the one irreversible write on
        the track.
        """

        future = {**NOTIFICATION, "issued_at": "2099-01-05T00:00:00+00:00"}
        with self.assertRaises(DiagnosticStartReceiptError) as ctx:
            _receipt(self.row, completion_notification=future,
                     first_decision_date="20990112")
        self.assertIn("in the future", str(ctx.exception))

        # ... and the same receipt is legal once the as-of has caught up with it.
        self.assertIsNotNone(
            _receipt(self.row, completion_notification=future,
                     first_decision_date="20990112", as_of_date="20990105")
        )

    def test_the_frozen_week_cannot_back_fill_before_the_notification(self) -> None:
        with self.assertRaises(DiagnosticStartReceiptError) as ctx:
            _receipt(self.row, first_decision_date="20200106")
        self.assertIn("back-fill", str(ctx.exception))

    def test_the_frozen_week_cannot_escape_the_notification_horizon(self) -> None:
        with self.assertRaises(DiagnosticStartReceiptError) as ctx:
            _receipt(self.row, first_decision_date="20960102")
        self.assertIn("too far after", str(ctx.exception))

    def test_a_receipt_from_another_epoch_does_not_authorize_this_one(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            _issue(root, self.row, diagnostic_epoch=LEGAL_EPOCH)
            with self.assertRaises(MarketDiagnosticLifecycleError) as ctx:
                persist_settled_weekly_record(self.row, root=root)
            self.assertIn("epoch", str(ctx.exception))

    def _assert_first_week_field_is_bound(self, field, value, expected) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            _issue(root, self.row)
            mutated = copy.deepcopy(self.row)
            mutated[field] = value
            with self.assertRaises(DiagnosticStartReceiptError) as ctx:
                receipts.assert_first_week_is_authorized(mutated, root=root)
            self.assertIn(expected, str(ctx.exception))

    def test_first_week_gate_binds_calendar_week_index(self) -> None:
        self._assert_first_week_field_is_bound("calendar_week_index", 2, "calendar week")

    def test_first_week_gate_binds_decision_date(self) -> None:
        self._assert_first_week_field_is_bound(
            "decision_date", self.rows[1]["decision_date"], "decision date"
        )

    def test_first_week_gate_binds_window_id(self) -> None:
        self._assert_first_week_field_is_bound("window_id", "26w-27-52", "window")

    def test_first_week_gate_binds_diagnostic_epoch(self) -> None:
        self._assert_first_week_field_is_bound("diagnostic_epoch", LEGAL_EPOCH, "epoch")

    # ---- the digests must be earned, not asserted ------------------------------

    def test_a_receipt_whose_design_digest_is_invented_opens_nothing(self) -> None:
        """The forgery that used to work: a hand-written receipt full of zeros."""

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            root.mkdir(parents=True)
            forged = _receipt(self.row)
            forged["design_authority"]["contract_sha256"] = "0" * 64
            (root / RECEIPT_FILENAME).write_bytes(canonical_json_bytes(forged))
            with self.assertRaises(MarketDiagnosticLifecycleError) as ctx:
                persist_settled_weekly_record(self.row, root=root)
            self.assertIn("contract on disk", str(ctx.exception))
            self.assertFalse((root / "lifecycle_register.json").exists())

    def test_a_notification_digest_must_match_its_own_text(self) -> None:
        forged = _receipt(self.row)
        forged["completion_notification"]["notification_sha256"] = "0" * 64
        with self.assertRaises(DiagnosticStartReceiptError) as ctx:
            validate_start_receipt(forged)
        self.assertIn("notification text", str(ctx.exception))

    def test_the_notification_is_the_only_variable_that_can_block_minting(self) -> None:
        """No default notification exists: the clock cannot start by omission.

        The epoch is deliberately a legal one here. An illegal epoch would make
        every case below raise for a reason that has nothing to do with the
        notification, which is exactly how this test used to pass while proving
        nothing.
        """

        self.assertIsNotNone(_receipt(self.row, diagnostic_epoch=LEGAL_EPOCH))

        with self.assertRaises(TypeError):
            build_start_receipt(
                diagnostic_epoch=LEGAL_EPOCH,
                first_decision_date=self.row["decision_date"],
                as_of_date=AS_OF,
            )
        for broken in (
            {**NOTIFICATION, "issued_at": "2026-08-05 00:00:00"},   # no timezone
            {**NOTIFICATION, "notification_text": "too short"},      # not a notification
            {k: v for k, v in NOTIFICATION.items() if k != "notification_text"},
            {},
        ):
            with self.assertRaises(DiagnosticStartReceiptError):
                build_start_receipt(
                    diagnostic_epoch=LEGAL_EPOCH,
                    completion_notification=broken,
                    first_decision_date=self.row["decision_date"],
                    as_of_date=AS_OF,
                )

    # ---- authorization has to survive the moment it is granted -----------------

    def test_deleting_the_receipt_stops_the_clock_it_opened(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            _issue(root, self.row)
            persist_settled_weekly_record(self.rows[0], root=root)
            (root / RECEIPT_FILENAME).unlink()
            with self.assertRaises(MarketDiagnosticLifecycleError) as ctx:
                persist_settled_weekly_record(self.rows[1], root=root)
            self.assertIn("missing", str(ctx.exception))

    def test_swapping_the_receipt_stops_the_clock_it_opened(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            _issue(root, self.row)
            persist_settled_weekly_record(self.rows[0], root=root)
            replacement = _receipt(
                self.row,
                completion_notification={
                    **NOTIFICATION,
                    "notification_text": "US-short 26-week diagnostic design is independently complete.",
                },
            )
            (root / RECEIPT_FILENAME).write_bytes(canonical_json_bytes(replacement))
            with self.assertRaises(MarketDiagnosticLifecycleError) as ctx:
                persist_settled_weekly_record(self.rows[1], root=root)
            self.assertIn("no longer matches", str(ctx.exception))

    def test_a_register_carried_to_a_store_with_no_receipt_cannot_continue(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "market_diagnostic_private"
            _issue(source, self.row)
            persist_settled_weekly_record(self.rows[0], root=source)
            elsewhere = Path(td) / "runs_private"
            elsewhere.mkdir(parents=True)
            for item in source.rglob("*"):
                if item.is_file() and item.name != RECEIPT_FILENAME:
                    target = elsewhere / item.relative_to(source)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(item.read_bytes())
            with self.assertRaises(MarketDiagnosticLifecycleError):
                persist_settled_weekly_record(self.rows[1], root=elsewhere)

    # ---- the receipt file itself -----------------------------------------------

    def test_reissuing_the_same_receipt_is_idempotent_but_re_anchoring_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            first = _issue(root, self.row)
            again = _issue(root, self.row)
            self.assertEqual("idempotent", again["status"])
            self.assertEqual(first["receipt_sha256"], again["receipt_sha256"])
            with self.assertRaises(DiagnosticStartReceiptError) as ctx:
                _issue(root, self.row, first_decision_date=self.rows[5]["decision_date"])
            self.assertIn("already anchors", str(ctx.exception))

    def test_exclusive_create_rechecks_the_race_winner(self) -> None:
        """The preflight absence check is not ownership; O_EXCL decides the winner."""

        cases = (
            ("same", _receipt(self.row), "idempotent"),
            ("different", _receipt(self.row, diagnostic_epoch=LEGAL_EPOCH), "conflict"),
        )
        for label, winner, expected in cases:
            with self.subTest(label), tempfile.TemporaryDirectory() as td:
                root = Path(td) / "market_diagnostic_private"

                def collide(path, flags, _mode=0o777):
                    self.assertTrue(flags & receipts.os.O_EXCL, "receipt create lost O_EXCL")
                    Path(path).write_bytes(canonical_json_bytes(winner))
                    raise FileExistsError

                with mock.patch.object(receipts.os, "open", side_effect=collide):
                    if expected == "idempotent":
                        self.assertEqual(expected, _issue(root, self.row)["status"])
                    else:
                        with self.assertRaises(DiagnosticStartReceiptError) as ctx:
                            _issue(root, self.row)
                        self.assertIn("already anchors", str(ctx.exception))
                self.assertEqual(
                    canonical_json_bytes(winner), (root / RECEIPT_FILENAME).read_bytes()
                )

    def test_a_tampered_or_reflowed_stored_receipt_is_refused_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            _issue(root, self.row)
            path = root / RECEIPT_FILENAME

            doctored = json.loads(path.read_bytes().decode("utf-8"))
            doctored["boundary"]["counts_ship_gate"] = True
            path.write_bytes(canonical_json_bytes(doctored))
            with self.assertRaises(DiagnosticStartReceiptError):
                load_start_receipt(root)

            path.write_text(json.dumps(_receipt(self.row), indent=2), encoding="utf-8")
            with self.assertRaises(DiagnosticStartReceiptError) as ctx:
                load_start_receipt(root)
            self.assertIn("canonical", str(ctx.exception))

    def test_a_trailing_newline_cannot_ride_through_any_pattern(self) -> None:
        """Python's ``$`` also matches before a trailing newline; ``\\Z`` does not."""

        base = _receipt(self.row)
        for path in (
            ("diagnostic_epoch",),
            ("design_authority", "contract_sha256"),
            ("completion_notification", "notification_sha256"),
            ("first_calendar_week", "decision_date"),
        ):
            mutated = copy.deepcopy(base)
            target = mutated
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = f"{target[path[-1]]}\n"
            with self.assertRaises(DiagnosticStartReceiptError, msg=f"{path} accepted a newline"):
                validate_start_receipt(mutated)

    def test_nothing_but_a_decision_can_produce_a_receipt(self) -> None:
        """The design's named bypasses are all shut by construction."""

        receipt = _receipt(self.row)
        self.assertIs(False, receipt["boundary"]["issued_by_automatic_inference"])
        self.assertEqual(1, receipt["first_calendar_week"]["calendar_week_index"])
        self.assertEqual("26w-1-26", receipt["first_calendar_week"]["window_id"])
        self.assertEqual(design_authority_sha256(), receipt["design_authority"]["contract_sha256"])

        flipped = copy.deepcopy(receipt)
        flipped["boundary"]["issued_by_automatic_inference"] = True
        with self.assertRaises(DiagnosticStartReceiptError):
            validate_start_receipt(flipped)

        swapped = copy.deepcopy(receipt)
        swapped["design_authority"]["document_path"] = "docs/CURRENT.md"
        with self.assertRaises(DiagnosticStartReceiptError):
            validate_start_receipt(swapped)

    def test_public_entries_raise_the_modules_own_error_for_junk_input(self) -> None:
        for bad in (None, 0, 10 ** 400, float("nan"), [], {}, b"x", set(), object()):
            with self.assertRaises(DiagnosticStartReceiptError, msg=f"{bad!r} escaped typed"):
                load_start_receipt(bad)
            with self.assertRaises(DiagnosticStartReceiptError, msg=f"{bad!r} escaped typed"):
                receipts.assert_first_week_is_authorized(self.row, root=bad)

    def test_the_anchor_digest_is_what_the_register_is_checked_against(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            issued = _issue(root, self.row)
            self.assertEqual(
                issued["receipt_sha256"], start_receipt_sha256(load_start_receipt(root))
            )
            with self.assertRaises(DiagnosticStartReceiptError):
                receipts.assert_clock_authorization_still_holds("f" * 64, root=root)
            with self.assertRaises(DiagnosticStartReceiptError):
                receipts.assert_clock_authorization_still_holds(None, root=root)

    def test_ongoing_gate_rejects_a_malformed_digest_before_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            _issue(root, self.row)
            for malformed in (None, "f" * 63, "g" * 64):
                with self.subTest(malformed=malformed):
                    with self.assertRaises(DiagnosticStartReceiptError) as ctx:
                        receipts.assert_clock_authorization_still_holds(malformed, root=root)
                    self.assertIn(
                        "does not record a start receipt digest", str(ctx.exception)
                    )


if __name__ == "__main__":
    unittest.main()
