"""No-secret diagnostics for A-short non-blocking sidecars."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

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

    def test_redacts_windows_and_posix_absolute_paths(self):
        summary = safe_exception_summary(RuntimeError(
            r"windows C:\Users\cnhea\private\token.txt and posix /home/cnhea/private/token.txt"
        ))

        self.assertNotIn("C:\\Users\\cnhea", summary)
        self.assertNotIn("/home/cnhea", summary)
        self.assertIn("[REDACTED_PATH]", summary)

    def test_str_failure_returns_only_exception_class(self):
        class BrokenStringError(RuntimeError):
            def __str__(self):
                raise RuntimeError("diagnostic recursion")

        self.assertEqual(safe_exception_summary(BrokenStringError()), "BrokenStringError")

    def test_redacts_secret_value_from_secret_named_environment_variable(self):
        with patch.dict(os.environ, {"CUSTOM_SIDECARE_SECRET": "env-secret-value"}, clear=False):
            summary = safe_exception_summary(RuntimeError("provider rejected env-secret-value"))

        self.assertNotIn("env-secret-value", summary)

    def test_keeps_short_secret_named_environment_fragment_locatable(self):
        with patch.dict(os.environ, {"CUSTOM_SIDECARE_SECRET": "tiny"}, clear=False):
            summary = safe_exception_summary(RuntimeError("provider rejected tiny"))

        self.assertIn("tiny", summary)
