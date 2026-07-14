from __future__ import annotations

import ast
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from runners import a_short_preflight
from runners import backtest_rank
from runners import materialize_execution_price_data_tushare as execution_materializer

ROOT = Path(__file__).resolve().parents[1]


class AShortPreflightTests(unittest.TestCase):
    def test_preflight_lists_every_missing_dependency_in_one_result(self) -> None:
        present = {"jsonschema", "numpy"}
        result = a_short_preflight.build_result(
            find_spec=lambda name: object() if name in present else None
        )
        self.assertEqual(result["status"], "fail")
        self.assertEqual(
            [item["module"] for item in result["missing"]],
            ["akshare", "openpyxl", "pandas", "requests", "tqdm", "tushare"],
        )

    def test_a_short_provider_initializers_pass_token_without_set_token(self) -> None:
        class _FakeDataApi:
            pass
        setattr(_FakeDataApi, "_DataApi__http_url", "old")
        fake_tushare = types.SimpleNamespace(
            __version__="1.4.29",
            pro=types.SimpleNamespace(client=types.SimpleNamespace(DataApi=_FakeDataApi)),
            pro_api=mock.Mock(),
        )
        fake_tushare.pro_api.return_value = object()
        with mock.patch.dict(sys.modules, {"tushare": fake_tushare}), mock.patch.dict(
            os.environ, {"TUSHARE_TOKEN": "masked-test-token"}
        ):
            backtest_rank._tushare_pro()
            execution_materializer.tushare_pro()
        self.assertEqual(fake_tushare.pro_api.call_args_list, [
            mock.call("masked-test-token"),
            mock.call("masked-test-token"),
        ])

    def test_no_a_short_python_callsite_invokes_set_token(self) -> None:
        paths = [ROOT / "A-EGS" / "egs_main.py", ROOT / "runners" / "backtest_rank.py"]
        paths.extend(sorted((ROOT / "runners").glob("a_short_*.py")))
        paths.append(ROOT / "runners" / "materialize_execution_price_data_tushare.py")
        offenders: list[str] = []
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            if any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "set_token"
                for node in ast.walk(tree)
            ):
                offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])

    def test_tracked_python_resolver_does_not_pin_agent_private_runtime(self) -> None:
        text = (ROOT / ".tools" / "Resolve-AshortPython.ps1").read_text(encoding="utf-8")
        self.assertNotIn("codex-runtimes", text.lower())
        self.assertNotIn("claude", text.lower())


if __name__ == "__main__":
    unittest.main()
