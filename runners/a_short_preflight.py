from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_PATH = ROOT / "requirements-a-short.txt"
REQUIRED_MODULES = {
    "akshare": "akshare",
    "jsonschema": "jsonschema",
    "numpy": "numpy",
    "openpyxl": "openpyxl",
    "pandas": "pandas",
    "requests": "requests",
    "tqdm": "tqdm",
    "tushare": "tushare",
}


def missing_dependencies(
    find_spec: Callable[[str], object | None] = importlib.util.find_spec,
) -> list[dict[str, str]]:
    return [
        {"module": module, "package": package}
        for module, package in sorted(REQUIRED_MODULES.items())
        if find_spec(module) is None
    ]


def build_result(
    find_spec: Callable[[str], object | None] = importlib.util.find_spec,
) -> dict[str, object]:
    missing = missing_dependencies(find_spec)
    python_ok = sys.version_info >= (3, 10)
    return {
        "status": "pass" if python_ok and not missing else "fail",
        "python_executable": sys.executable,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "python_minimum": "3.10",
        "python_ok": python_ok,
        "requirements_file": str(REQUIREMENTS_PATH),
        "missing": missing,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline A-short interpreter/dependency preflight; performs no provider calls."
    )
    parser.add_argument("--json", action="store_true", help="Emit one JSON result.")
    args = parser.parse_args(argv)
    result = build_result()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif result["status"] == "pass":
        print(f"[OK] A-short preflight passed: {result['python_executable']}")
    else:
        print("[FATAL] A-short preflight failed.", file=sys.stderr)
        if not result["python_ok"]:
            print(
                f"- Python {result['python_version']} is below {result['python_minimum']}",
                file=sys.stderr,
            )
        for item in result["missing"]:
            print(f"- missing module {item['module']} (package {item['package']})", file=sys.stderr)
        print(
            f'Install all A-short dependencies once with:\n  "{sys.executable}" -m pip install -r "{REQUIREMENTS_PATH}"',
            file=sys.stderr,
        )
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
