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


# Strict INCLUSION-based A-share main-board test (exact prefixes per the V14.3 governance universe):
# SSE 600/601/603/605 + SZSE 000/001/002/003 only. Unlike the exclusion-based ``is_main_board_ts_code``
# (which treats any non-rejected code as "main" and so lets B-shares 900*.SH / 200*.SZ leak through),
# this accepts ONLY the declared A-share main-board prefixes and rejects everything else (B-shares,
# ChiNext/STAR/BSE, and unknown/malformed codes). Use this for any A-share main-board universe scoping.
A_SHARE_MAIN_BOARD_SSE_PREFIXES = ("600", "601", "603", "605")
A_SHARE_MAIN_BOARD_SZSE_PREFIXES = ("000", "001", "002", "003")


def is_a_share_main_board(ts_code: object) -> bool:
    code = "" if ts_code is None else str(ts_code).strip().upper()
    if "." not in code:
        return False
    symbol, exch = code.split(".", 1)
    # require a canonical 6-ASCII-digit symbol BEFORE prefix acceptance, so malformed codes that merely
    # start with an accepted prefix (e.g. 600ABC.SH, 60000.SH, 6000000.SH, 00000A.SZ, 002.SZ) are rejected.
    if len(symbol) != 6 or not all(c in "0123456789" for c in symbol):
        return False
    if exch == "SH":
        return symbol.startswith(A_SHARE_MAIN_BOARD_SSE_PREFIXES)
    if exch == "SZ":
        return symbol.startswith(A_SHARE_MAIN_BOARD_SZSE_PREFIXES)
    return False


def non_main_board_symbols(symbols: Iterable[object]) -> list[str]:
    return [str(symbol) for symbol in symbols if not is_main_board_ts_code(symbol)]


def assert_main_board_only(symbols: Iterable[object], *, context: str) -> None:
    violations = non_main_board_symbols(symbols)
    if violations:
        joined = ", ".join(violations)
        raise ValueError(f"{context} must be A-share main-board only; non-main symbols: {joined}")
