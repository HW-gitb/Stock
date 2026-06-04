from __future__ import annotations

from collections.abc import Iterable


NON_MAIN_BOARD_PREFIXES = ("300", "301", "688", "689", "920", "8", "4")


def board_bucket_from_ts_code(ts_code: object) -> str:
    code = "" if ts_code is None else str(ts_code).strip().upper()
    symbol = code.split(".", 1)[0]
    if code.endswith(".BJ") or symbol.startswith(("920", "8", "4")):
        return "bj"
    if symbol.startswith(("300", "301")):
        return "chinext"
    if symbol.startswith(("688", "689")):
        return "star"
    return "main"


def is_main_board_ts_code(ts_code: object) -> bool:
    return board_bucket_from_ts_code(ts_code) == "main"


def non_main_board_symbols(symbols: Iterable[object]) -> list[str]:
    return [str(symbol) for symbol in symbols if not is_main_board_ts_code(symbol)]


def assert_main_board_only(symbols: Iterable[object], *, context: str) -> None:
    violations = non_main_board_symbols(symbols)
    if violations:
        joined = ", ".join(violations)
        raise ValueError(f"{context} must be A-share main-board only; non-main symbols: {joined}")
