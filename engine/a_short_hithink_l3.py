"""HiThink concept-board graph for A-short L3.

The provider publishes one complete concept catalog and one constituent list
per concept board.  A formal L3 run must receive a valid response for every
catalog entry; an explicit empty ``data.item`` is the only permitted skip.
This module deliberately has no Tushare fallback, cache, or partial result.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import os
import re
import time
from typing import Any, Callable, Mapping
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd

from engine.data.a_share_board_scope import is_a_share_main_board


SOURCE_ID = "hithink_finance"
API_KEY_ENV = "HITHINK_FINANCE_API_KEY"
API_BASE_URL = "https://fuyao.aicubes.cn"
CONCEPT_CATALOG_PATH = "/api/a-share-index/catalog/ths-index-list?tag=cn_concept"
CONSTITUENTS_PATH = "/api/a-share-index/constituents/ths-stock-list?thscode="
CONCEPT_CODE_RE = re.compile(r"^\d+\.TI$")
STOCK_CODE_RE = re.compile(r"^\d{6}\.[A-Z]{2}$")
_A_SHARE_SUFFIXES = frozenset({"SH", "SZ", "BJ"})
MIN_CONCEPT_CATALOG_BOARD_COUNT = 389


class HiThinkL3SourceError(RuntimeError):
    """The provider could not supply one complete, valid concept graph."""


@dataclass(frozen=True)
class HiThinkL3Graph:
    """A complete catalog and its current constituent graph."""

    concepts_df: pd.DataFrame
    stock_concepts: dict[str, list[str]]
    concept_members: dict[str, list[str]]
    coverage: dict[str, Any]


JsonRequester = Callable[[str, Mapping[str, str]], Any]


def _default_requester(url: str, headers: Mapping[str, str]) -> Any:
    request = Request(url, headers=dict(headers))
    with urlopen(request, timeout=30) as response:  # nosec B310: fixed HTTPS endpoint
        return json.loads(response.read().decode("utf-8"))


def _windows_user_environment_value(name: str) -> str:
    """Read a just-configured Windows user variable without logging its value."""
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
    except (FileNotFoundError, OSError):
        return ""
    return str(value or "").strip()


def _require_api_key(
    api_key: str | None,
    *,
    environment: Mapping[str, str] | None = None,
    user_env_reader: Callable[[str], str] | None = None,
) -> str:
    env = environment if environment is not None else os.environ
    value = (api_key if api_key is not None else env.get(API_KEY_ENV, "")).strip()
    if not value and api_key is None:
        value = (user_env_reader or _windows_user_environment_value)(API_KEY_ENV).strip()
    if not value:
        raise HiThinkL3SourceError(f"{API_KEY_ENV} is not configured")
    return value


def _request_with_retry(
    requester: JsonRequester,
    url: str,
    headers: Mapping[str, str],
    label: str,
    *,
    max_attempts: int,
    sleep: Callable[[float], None],
) -> Any:
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return requester(url, headers)
        except Exception as exc:  # transport/client errors are fail-closed after bounded retry
            last_error = exc
            if attempt + 1 < max_attempts:
                sleep(float(2**attempt))
    category = type(last_error).__name__ if last_error is not None else "unknown"
    raise HiThinkL3SourceError(f"{label} request failed after {max_attempts} attempts ({category})")


def _response_items(payload: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise HiThinkL3SourceError(f"{label} returned a non-success envelope")
    data = payload.get("data")
    items = data.get("item") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise HiThinkL3SourceError(f"{label} is missing its item list")
    if not all(isinstance(item, dict) for item in items):
        raise HiThinkL3SourceError(f"{label} contains a non-object item")
    return items


def _catalog_rows(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        code = str(item.get("thscode") or "").strip()
        name = str(item.get("name") or "").strip()
        if not CONCEPT_CODE_RE.fullmatch(code):
            raise HiThinkL3SourceError("concept catalog contains an invalid board code")
        if not name:
            raise HiThinkL3SourceError(f"concept catalog board {code} has no name")
        if code in seen:
            raise HiThinkL3SourceError(f"concept catalog contains duplicate board {code}")
        seen.add(code)
        rows.append({"code": code, "name": name})
    if not rows:
        raise HiThinkL3SourceError("concept catalog is empty")
    return rows


def _validated_member_codes(
    items: list[dict[str, Any]], board_code: str
) -> tuple[list[str], int, int, int, Counter[str]]:
    provider_codes: set[str] = set()
    for item in items:
        code = str(item.get("thscode") or "").strip()
        if not STOCK_CODE_RE.fullmatch(code):
            raise HiThinkL3SourceError(f"concept board {board_code} contains an invalid stock code")
        provider_codes.add(code)

    suffix_counts = Counter(code.rsplit(".", 1)[1] for code in provider_codes)
    out_of_a_share_count = sum(
        count for suffix, count in suffix_counts.items() if suffix not in _A_SHARE_SUFFIXES
    )
    main_board_codes = sorted(code for code in provider_codes if is_a_share_main_board(code))
    excluded_non_main_board_count = len(provider_codes) - len(main_board_codes)
    return (
        main_board_codes,
        len(provider_codes),
        excluded_non_main_board_count,
        out_of_a_share_count,
        suffix_counts,
    )


def catalog_digest(board_codes: set[str]) -> str:
    canonical = "\n".join(sorted(board_codes)).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def fetch_complete_concept_graph(
    api_key: str | None = None,
    *,
    requester: JsonRequester | None = None,
    max_workers: int = 8,
    max_attempts: int = 3,
    min_catalog_board_count: int = MIN_CONCEPT_CATALOG_BOARD_COUNT,
    expected_catalog_codes: set[str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> HiThinkL3Graph:
    """Fetch and validate every board in the current HiThink concept catalog.

    The returned graph is all-or-nothing.  A board is accepted as empty only
    when the provider has returned ``code == 0`` and an explicit empty list.
    Provider members outside the A-share main-board universe are counted in the
    receipt but never enter scoring/snapshot membership.
    """
    if max_workers < 1:
        raise ValueError("max_workers must be >= 1")
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    if min_catalog_board_count < 1:
        raise ValueError("min_catalog_board_count must be >= 1")

    key = _require_api_key(api_key)
    request_json = requester or _default_requester
    headers = {"X-api-key": key}

    catalog_payload = _request_with_retry(
        request_json,
        API_BASE_URL + CONCEPT_CATALOG_PATH,
        headers,
        "concept catalog",
        max_attempts=max_attempts,
        sleep=sleep,
    )
    catalog = _catalog_rows(_response_items(catalog_payload, "concept catalog"))
    catalog_codes = {row["code"] for row in catalog}
    if len(catalog_codes) < min_catalog_board_count:
        raise HiThinkL3SourceError(
            "concept catalog count is below the accepted completeness floor "
            f"({len(catalog_codes)} < {min_catalog_board_count})"
        )
    expected_codes = set(expected_catalog_codes or ())
    missing_expected_codes = expected_codes - catalog_codes
    if missing_expected_codes:
        raise HiThinkL3SourceError(
            "concept catalog dropped previously accepted boards "
            f"(missing_count={len(missing_expected_codes)})"
        )

    def fetch_board(row: dict[str, str]) -> tuple[str, list[dict[str, Any]]]:
        board_code = row["code"]
        payload = _request_with_retry(
            request_json,
            API_BASE_URL + CONSTITUENTS_PATH + quote(board_code, safe=""),
            headers,
            f"concept board {board_code}",
            max_attempts=max_attempts,
            sleep=sleep,
        )
        return board_code, _response_items(payload, f"concept board {board_code}")

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            fetched = list(pool.map(fetch_board, catalog))
    except HiThinkL3SourceError:
        raise
    except Exception as exc:  # defensive boundary: never return a partial graph
        raise HiThinkL3SourceError(f"concept-board fetch failed ({type(exc).__name__})") from None

    concept_members: dict[str, list[str]] = {}
    explicit_empty_count = 0
    scope_filtered_empty_count = 0
    raw_member_rows = 0
    unique_member_pairs = 0
    main_board_member_pairs = 0
    excluded_non_main_board_members = 0
    out_of_a_share_members = 0
    market_suffix_counts: Counter[str] = Counter()
    for board_code, items in fetched:
        raw_member_rows += len(items)
        (
            members,
            provider_unique_count,
            excluded_count,
            external_count,
            suffix_counts,
        ) = _validated_member_codes(items, board_code)
        if not items:
            explicit_empty_count += 1
        elif not members:
            scope_filtered_empty_count += 1
        concept_members[board_code] = members
        unique_member_pairs += provider_unique_count
        main_board_member_pairs += len(members)
        excluded_non_main_board_members += excluded_count
        out_of_a_share_members += external_count
        market_suffix_counts.update(suffix_counts)

    expected_board_codes = {row["code"] for row in catalog}
    if set(concept_members) != expected_board_codes:
        raise HiThinkL3SourceError("concept-board coverage does not exactly match the catalog")

    inverted: dict[str, list[str]] = defaultdict(list)
    for board_code in sorted(concept_members):
        for stock_code in concept_members[board_code]:
            inverted[stock_code].append(board_code)
    stock_concepts = {}
    for stock_code, board_codes in sorted(inverted.items()):
        stock_concepts[stock_code] = sorted(board_codes)
    coverage = {
        "source": SOURCE_ID,
        "catalog_tag": "cn_concept",
        "catalog_digest": catalog_digest(catalog_codes),
        "catalog_board_count": len(catalog),
        "received_board_count": len(concept_members),
        "verified_empty_board_count": explicit_empty_count,
        "scope_filtered_empty_board_count": scope_filtered_empty_count,
        "raw_member_row_count": raw_member_rows,
        "unique_member_pair_count": unique_member_pairs,
        "main_board_member_pair_count": main_board_member_pairs,
        "excluded_non_main_board_member_count": excluded_non_main_board_members,
        "out_of_a_share_member_count": out_of_a_share_members,
        "market_suffix_counts": dict(sorted(market_suffix_counts.items())),
        "scoring_universe": "a_share_main_board",
        "complete": True,
    }
    concepts_df = pd.DataFrame(catalog, columns=["code", "name"])
    return HiThinkL3Graph(concepts_df, stock_concepts, concept_members, coverage)
