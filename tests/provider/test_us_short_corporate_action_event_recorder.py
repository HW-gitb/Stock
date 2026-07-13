from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_security_identity as identity  # noqa: E402
from runners import us_short_corporate_action_event_recorder as runner  # noqa: E402


def input_payload() -> dict:
    accession = "0001418091-22-000001"
    return {
        "security_identity": identity.record_security_identity(issuer_cik="1418091", security_class="COMMON", current_ticker="TWTR", issuer_name="Example Issuer", primary_exchange="NYSE", observed_as_of="20260713", source_id="manual_seed", source_ref_sha256="a" * 64),
        "position": {"ticker": "TWTR", "direction": "long", "shares": 5},
        "old_ticker": "TWTR",
        "event_type": "cash_consideration",
        "successor_ticker": None,
        "successor_security_identity": None,
        "stock_ratio_numerator": None,
        "stock_ratio_denominator": None,
        "cash_per_old_share_usd": "54.20",
        "effective_date": "2022-10-28",
        "sec_accession": accession,
        "sec_url": f"https://www.sec.gov/Archives/edgar/data/1418091/{accession.replace('-', '')}/event.htm",
        "unsupported_consideration": None,
    }


class CorporateActionEventRecorderRunnerTest(unittest.TestCase):
    def test_confirm_flag_is_required_and_runner_never_fetches(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "manual_input.json"
            input_path.write_text(json.dumps(input_payload()), encoding="utf-8")
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                self.assertEqual(runner.main(["--manual-input", str(input_path)]), 0)
            self.assertEqual(json.loads(captured.getvalue())["record_status"], "manual_review")

            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                self.assertEqual(runner.main(["--manual-input", str(input_path), "--confirm"]), 0)
            self.assertEqual(json.loads(captured.getvalue())["record_status"], "confirmed_event")
            self.assertNotIn("yfinance", sys.modules)


if __name__ == "__main__":
    unittest.main()
