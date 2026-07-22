from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from runners.us_short_paper_one_click import PaperOneClickError, _prepare_paper_inputs, run_one_click


class USShortPaperOneClickTest(unittest.TestCase):
    def test_prepares_only_a_pending_adapter_slot_without_reinitializing_capital(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            template_path, account_path = _prepare_paper_inputs(
                private_root=Path(td), decision_date="20260720"
            )
            account = json.loads(account_path.read_text(encoding="utf-8"))
            self.assertEqual({"pending_model_paper_adapter": True, "decision_date": "20260720"}, account)
            persisted = {"already": "an adapter from an earlier week"}
            account_path.write_text(json.dumps(persisted), encoding="utf-8")
            _template_again, account_again = _prepare_paper_inputs(private_root=Path(td), decision_date="20260727")
            self.assertEqual(account_path, account_again)
            self.assertEqual(persisted, json.loads(account_again.read_text(encoding="utf-8")))
            self.assertTrue(template_path.is_file())
            self.assertIn("basket_context", json.loads(template_path.read_text(encoding="utf-8")))

    def test_invalid_launcher_option_fails_before_any_provider_stage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(PaperOneClickError, "provider-pace-seconds"):
                run_one_click(
                    now_et=datetime(2026, 7, 20, 1, 0, 0),
                    private_root=Path(td),
                    state_dir=Path(td) / "state",
                    provider_pace_seconds=-1.0,
                )

    def test_cmd_entrypoint_handles_execution_policy_in_process(self) -> None:
        text = (Path(__file__).parents[1] / "runners" / "us_short_paper_one_click.cmd").read_text(
            encoding="utf-8"
        )
        self.assertIn("-ExecutionPolicy Bypass", text)


if __name__ == "__main__":
    unittest.main()
