import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location("egs_main_l3_guard_under_test", EGS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


class EgsMainL3GuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    def test_historical_asof_rejects_default_today_l3(self) -> None:
        with self.assertRaisesRegex(SystemExit, "cannot run with --l3-mode=today"):
            self.egs_main._guard_historical_asof_l3_mode(
                "20260522",
                "today",
                run_date="20260601",
            )

    def test_historical_asof_allows_pit_or_neutralize(self) -> None:
        self.egs_main._guard_historical_asof_l3_mode("20260522", "pit", run_date="20260601")
        self.egs_main._guard_historical_asof_l3_mode("20260522", "neutralize", run_date="20260601")

    def test_today_l3_requires_explicit_live_l3_declaration_for_historical_replay(self) -> None:
        self.egs_main._guard_historical_asof_l3_mode(
            "20260522",
            "today",
            allow_historical_live_l3=True,
            run_date="20260601",
        )

    def test_current_asof_keeps_default_today_l3_allowed(self) -> None:
        self.egs_main._guard_historical_asof_l3_mode("20260601", "today", run_date="20260601")


if __name__ == "__main__":
    unittest.main()
