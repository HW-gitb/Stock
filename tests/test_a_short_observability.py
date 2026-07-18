"""No-secret diagnostics for A-short non-blocking sidecars."""
from __future__ import annotations

import unittest

from engine.a_short_observability import safe_exception_summary


class SafeExceptionSummaryTests(unittest.TestCase):
    def test_preserves_benign_programming_error_detail(self):
        summary = safe_exception_summary(NameError("name 'json' is not defined"))

        self.assertEqual(summary, "NameError: name 'json' is not defined")

    def test_redacts_urls_and_secret_values_before_logging(self):
        summary = safe_exception_summary(RuntimeError(
            "request https://api.example.test/v1?token=top-secret failed; "
            "TUSHARE_TOKEN=top-secret Authorization: Bearer bearer-secret"
        ))

        self.assertIn("RuntimeError:", summary)
        self.assertNotIn("https://", summary)
        self.assertNotIn("top-secret", summary)
        self.assertNotIn("bearer-secret", summary)
        self.assertIn("[REDACTED]", summary)
