"""US-short batch5 Cut 5 (Pass 2 audit-gate + catalyst) DATA-LAYER FEASIBILITY PROBE — gated small sample.

Authorization: user_chat_20260701_cut5_pass2_feasibility_probe  (SR-PROVIDER-001, this run only)
Design: docs/us_short_system_design.md §4.0/§4.1 (Pass 2 audit safety gate) / §5.1 (two-layer audit) /
        §4.2 (catalyst: earnings surprise / analyst revisions / 8-K) / §5.2 (candidate vetoes)

PURPOSE — feasibility ONLY, NOT a builder. Round-1 universe fetch proved the Pass 1 layer
(price/volume/shares/market-cap). This probe proves whether the *Pass 2 audit-gate + catalyst DATA LAYER*
is actually fetchable and what its REAL shape / PIT date fields / rate-license signals are, BEFORE any
schema-first binding or parser is written. (Memory: probe-first — else you invest-build a binding on a
guessed shape, like catalyst-source which Codex re-opened 3x.) It DOES NOT select a provider, build a
binding/parser, write private state, consume DataHub, or claim production/ship-gate — SR-PROVIDER-001
stays open and every gate flag in the tracked summary is pinned closed.

Data channels probed (all free, pure HTTP — NO broker, NO paid tier, NO yfinance, NO full market):
  - SEC EDGAR submissions  : per-symbol filing history -> FORM-TYPE breakdown for the §5.1a dilution/event
                             families (S-1 / S-3 / S-3ASR / 424B* / S-8 / 8-K / 10-K / 10-Q / 25-NSE /
                             Form 4 / 144 / SC 13G / SC 13D) with the most-recent filingDate +
                             acceptanceDateTime per family (the PIT clock §5.1a recency/materiality needs).
                             Proves the audit-gate FILING channel + its PIT dates are reachable & parseable.
  - FMP (existing key)     : catalyst channels NOT covered by any prior probe — earnings-surprises
                             (actual vs estimate, §4.2), analyst-estimates (§4.2), grades / rating changes
                             (§4.2 / §5.2 analyst downgrades). Records reachability + shape + date fields.
                             A 403/404 is a REAL feasibility finding (FMP Basic may not include them).
  - Massive (existing key) : one per-ticker daily aggregates call — proves event-window OHLCV per symbol is
                             fetchable for catalyst price-reaction (§4.2/§5.2), beyond round-1's grouped call.

The §5.1b semantic layer (going-concern / auditor-resignation / short-seller reports) needs filing-DOCUMENT
text parsing, which is out of this probe's scope; the probe records that so the `semantic_audit_unavailable`
default stays honest.

Outputs (research-only):
  - Gitignored raw    -> provider_samples/us_short_cut5_pass2_feasibility_20260701/raw/
  - Tracked summary   -> docs/us_short_cut5_pass2_feasibility_probe_summary_20260701.json
                         (diagnostics only: status / shape / field-presence / form-type counts+dates; NO
                         secrets, NO request URLs, NO raw payload rows; schema-validated + secret-scanned
                         BEFORE any write, so a schema-invalid or secret-bearing summary is never written)

Usage:
  python runners/us_short_cut5_pass2_feasibility_probe.py --dry-run-env
  python runners/us_short_cut5_pass2_feasibility_probe.py --confirm-user-authorization
Requires env: SEC_USER_AGENT, FMP_API_KEY, MASSIVE_API_KEY (never printed or logged).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# Make jsonschema resolvable when it is only vendored under .tools/python_libs — the probe's mandatory
# pre-write schema validation imports jsonschema; mirror the other batch5 writers' bootstrap.
_PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if _PYTHON_LIBS.exists() and str(_PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(_PYTHON_LIBS))

from runners import us_egs_sample_validation as sample_validation  # noqa: E402


SUMMARY_PATH = ROOT / "docs" / "us_short_cut5_pass2_feasibility_probe_summary_20260701.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_cut5_pass2_feasibility_probe_summary.schema.json"
RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_short_cut5_pass2_feasibility_20260701")
RAW_SAMPLE_ROOT = ROOT / RAW_SAMPLE_REL_ROOT / "raw"

AUTHORIZATION_REF = "user_chat_20260701_cut5_pass2_feasibility_probe"
# A SEPARATELY-authorized follow-up (the quarterly/annual Massive financials re-probe) — recorded as its OWN
# execution block, never folded into the 21-call primary budget (Codex finding A).
FOLLOWUP_AUTHORIZATION_REF = "user_chat_20260701_cut5_massive_financials_periodic_reprobe"
# The EXACT authorized follow-up call set — exactly AAPL quarterly + AAPL annual, no more, no less. The block
# builder fails closed unless precisely these two calls are present + HTTP-200 + nonempty-results + carry the PIT
# filing_date/acceptance_datetime; the schema const-pins the same, so a missing/extra/renamed/forged follow-up can
# never remain the artifact cited as proof of the periodic PIT fields (Codex re-review residual).
EXPECTED_FOLLOWUP_CALLS = (("AAPL", "quarterly"), ("AAPL", "annual"))
# The follow-up NAMESPACE is inventoried EXHAUSTIVELY (Codex round-2 finding A): under massive/<symbol>/ only these
# massive_financials* names are authorized — the DEFAULT-ttm PRIMARY (counted in endpoint_manifest, NOT a follow-up)
# and the two periodic follow-ups. ANY other suffix / extension / nested placement fails closed, so an extra /
# renamed / wrong-extension / nested massive_financials_*.json can never be silently omitted from the separately-
# authorized execution record. `_FOLLOWUP_TIMEFRAMES` is DERIVED from EXPECTED_FOLLOWUP_CALLS so it cannot drift.
_PRIMARY_TTM_FILENAME = "massive_financials.json"
_FOLLOWUP_TIMEFRAMES = tuple(sorted({tf for _sym, tf in EXPECTED_FOLLOWUP_CALLS}))   # ('annual', 'quarterly')
EXPECTED_SYMBOLS = ["AAPL", "MSFT", "NVDA"]
EXPECTED_PRIMARY_FINANCIAL_SYMBOLS = tuple(EXPECTED_SYMBOLS)
# 1 SEC map + 3 SEC submissions + 3x3 FMP catalyst + 1 Massive aggs + 3x2 Massive reference + 1 Massive
# earnings/analyst probe = 21; headroom to 24.
MAX_TOTAL_ENDPOINT_CALLS = 24
MASSIVE_PROBE_SYMBOL = "AAPL"
# The FROZEN primary endpoint manifest: the exact per-(provider, family) call plan the one-shot probe makes. The
# producer recomputes the actual per-family counts from the emitted records and asserts they equal this manifest,
# and derives the total from it (Codex finding B: freeze the manifest + independently recompute totals, so a wrong
# per-family/total count cannot pass unnoticed).
EXPECTED_PRIMARY_MANIFEST = {
    "SEC:company_tickers_mapping": 1,
    "SEC:submissions": 3,
    "FMP:earnings_surprises": 3,
    "FMP:analyst_estimates": 3,
    "FMP:grades": 3,
    "Massive:ticker_daily_aggregates": 1,
    "Massive:massive_financials": 3,
    "Massive:massive_news": 3,
    "Massive:massive_earnings_analyst_probe": 1,
}
EXPECTED_PRIMARY_TOTAL = 21
# The summary destination is pinned: a reviewed one-shot artifact may be written only to the canonical tracked path
# or under this probe's own gitignored provider_samples dir (tests) — never an arbitrary tracked file (Codex finding B).
APPROVED_SUMMARY_DIR = ROOT / RAW_SAMPLE_REL_ROOT

# FMP catalyst endpoints (stable). These are candidate stable paths; a 403/404 here is a real feasibility
# finding (FMP Basic tier may not include them), which is exactly what this probe exists to discover.
FMP_CATALYST_ENDPOINTS = [
    {
        "endpoint_family": "earnings_surprises",
        "path_template": "earnings-surprises",
        "params": {},
        "fields": ["date", "symbol", "actualEarningResult", "estimatedEarning"],
        "date_fields": ["date"],
    },
    {
        "endpoint_family": "analyst_estimates",
        "path_template": "analyst-estimates",
        "params": {},
        "fields": ["date", "symbol", "estimatedRevenueAvg", "estimatedEpsAvg"],
        "date_fields": ["date"],
    },
    {
        "endpoint_family": "grades",
        "path_template": "grades",
        "params": {},
        "fields": ["symbol", "date", "gradingCompany", "newGrade", "previousGrade"],
        "date_fields": ["date"],
    },
]
FMP_CATALYST_FAMILIES = [e["endpoint_family"] for e in FMP_CATALYST_ENDPOINTS]

# SEC §5.1a form families. ("exact_or_amend", [...]) matches `FORM` or `FORM/A...`; ("prefix", [...])
# matches any form starting with the pattern. The two matchers keep "4" (Form 4, exact/amend) from being
# swallowed by "424B" / "40-F", while "424B" and "SC 13G/A" correctly match by prefix.
SEC_FORM_FAMILIES = [
    ("S-1", ("exact_or_amend", ["S-1"])),
    ("S-3", ("exact_or_amend", ["S-3", "S-3ASR"])),
    ("424B", ("prefix", ["424B"])),
    ("S-8", ("exact_or_amend", ["S-8"])),
    ("8-K", ("exact_or_amend", ["8-K"])),
    ("10-K", ("exact_or_amend", ["10-K"])),
    ("10-Q", ("exact_or_amend", ["10-Q"])),
    ("25-NSE", ("exact_or_amend", ["25-NSE", "25"])),
    ("form_4", ("exact_or_amend", ["4"])),
    ("144", ("exact_or_amend", ["144"])),
    ("SC_13G", ("prefix", ["SC 13G"])),
    ("SC_13D", ("prefix", ["SC 13D"])),
]

MASSIVE_AGG_URL = (
    "https://api.massive.com/v2/aggs/ticker/{ticker}/range/1/day/{frm}/{to}"
    "?adjusted=true&sort=desc&limit=60&apiKey={key}"
)
MASSIVE_OHLCV_FIELDS = ["t", "o", "h", "l", "c", "v"]

# Massive (Polygon-compatible) REFERENCE channels — retried after FMP earnings-surprises/analyst-estimates
# returned 404/400 (user request "换成 massive 再试拿不到的数据"). Polygon's model carries REFERENCE
# financials (ACTUAL SEC-derived statements, with a PIT filing_date) + ticker news, but NOT sell-side analyst
# estimates / consensus / earnings surprise (that is FMP/Benzinga/Zacks territory). So `massive_financials`
# supplies the ACTUAL half of §4.2 "财报实际vs预期" and `massive_news` supplies event/catalyst news; the
# earnings/analyst probe tests whether Massive proxies any Benzinga-style estimate extension at all (a
# 404/403 is itself a real feasibility finding, not an error to route around).
MASSIVE_REFERENCE_ENDPOINTS = [
    {
        "endpoint_family": "massive_financials",
        "url_template": "https://api.massive.com/vX/reference/financials?ticker={ticker}&limit=4&apiKey={key}",
        "fields": ["cik", "fiscal_period", "fiscal_year", "start_date", "end_date", "filing_date"],
        "date_fields": ["filing_date", "end_date"],
    },
    {
        "endpoint_family": "massive_news",
        "url_template": "https://api.massive.com/v2/reference/news?ticker={ticker}&limit=10&apiKey={key}",
        "fields": ["id", "publisher", "title", "published_utc", "article_url", "tickers"],
        "date_fields": ["published_utc"],
    },
]
MASSIVE_EARNINGS_PROBE = {
    "endpoint_family": "massive_earnings_analyst_probe",
    "url_template": "https://api.massive.com/benzinga/v1/earnings?tickers={ticker}&apiKey={key}",
    "fields": ["date", "ticker", "eps", "eps_est", "eps_surprise"],
    "date_fields": ["date"],
}
MASSIVE_REFERENCE_FAMILIES = (
    [e["endpoint_family"] for e in MASSIVE_REFERENCE_ENDPOINTS] + [MASSIVE_EARNINGS_PROBE["endpoint_family"]]
)


# ---------------------------------------------------------------------------
# Boundary / hygiene helpers
# ---------------------------------------------------------------------------

def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _provider_samples_gitignored() -> bool:
    gi = ROOT / ".gitignore"
    return gi.exists() and "provider_samples/" in gi.read_text(encoding="utf-8")


def _validate_raw_root(raw_root: Path) -> None:
    """Fail-closed: raw MUST live under this probe's own gitignored provider_samples subfolder."""
    resolved = raw_root.resolve()
    approved = (ROOT / RAW_SAMPLE_REL_ROOT).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise ValueError(
            "raw_root must stay under provider_samples/us_short_cut5_pass2_feasibility_20260701/"
        ) from exc
    sample_validation.validate_raw_root(raw_root)


def _validate_summary_path(summary_path: Path) -> None:
    """Fail-closed: the summary may be written ONLY to the canonical tracked path or under this probe's own
    gitignored provider_samples dir (tests) — never an arbitrary tracked file (Codex finding B: no caller-spoofable
    overwrite of an unrelated destination)."""
    resolved = summary_path.resolve()
    if resolved == SUMMARY_PATH.resolve():
        return
    try:
        resolved.relative_to(APPROVED_SUMMARY_DIR.resolve())
    except ValueError as exc:
        raise ValueError(
            "summary_path must be the canonical tracked summary or under "
            "provider_samples/us_short_cut5_pass2_feasibility_20260701/"
        ) from exc


def _valid_generated_at(value: Any) -> bool:
    """A tz-aware RFC3339 instant (exactly one 'T' + offset/Z). A free-form / date-only / naive / multi-'T'
    timestamp is rejected so the summary's own execution time cannot be a bare string (Codex finding B: validate
    generated_at semantically)."""
    if not (isinstance(value, str) and value.count("T") == 1):
        return False
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return dt.tzinfo is not None


def _valid_ymd(value: Any) -> bool:
    """A real-calendar YYYY-MM-DD (10-char ASCII), semantics IDENTICAL to the Cut 5-b consumer
    (engine.us_short_massive_financials._valid_ymd): impossible-calendar (2026-13-40), non-padded, non-string, and
    blank are rejected — so the probe cannot certify a filing_date its intended parser would reject (Codex round-2
    finding B: validate the evidence VALUES, not mere field presence)."""
    if not (type(value) is str and len(value) == 10 and value.isascii()):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _valid_acceptance_instant(value: Any) -> bool:
    """A tz-AWARE RFC3339 instant whose ET normalization is SURVIVABLE — semantics IDENTICAL to the Cut 5-b consumer's
    EFFECTIVE acceptance (engine.us_short_massive_financials._valid_observed_at predicate AND `_observed_at_et`'s
    astimezone(America/New_York), which fails closed on a boundary-year OverflowError/OSError). 'T' + a real offset/Z
    is required; date-only / space-sep / naive / malformed / boundary-year-unnormalizable are rejected, so the probe
    cannot certify an acceptance the consumer would reject (Codex round-2 finding B — compatible-with-consumer)."""
    if not (type(value) is str and "T" in value):
        return False
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    if dt.tzinfo is None:
        return False
    try:                                                     # mirror the consumer's ET-normalization survivability
        from zoneinfo import ZoneInfo
        dt.astimezone(ZoneInfo("America/New_York"))
    except (OverflowError, OSError, KeyError, ImportError):  # KeyError covers ZoneInfoNotFoundError; fail closed, no leak
        return False
    return True


def _repo_relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def compute_endpoint_manifest(endpoint_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Recompute the per-(provider, family) call counts + total from the emitted records, and compare them to the
    FROZEN EXPECTED_PRIMARY_MANIFEST — so a wrong per-family or total count (or an omitted/extra call) is visible
    (Codex finding B). For a dry-run (no records) per_family is empty and matches_expected is False."""
    counts: dict[str, int] = {}
    for item in endpoint_summaries:
        key = f"{item['provider']}:{item['endpoint_family']}"
        counts[key] = counts.get(key, 0) + 1
    total = sum(counts.values())
    return {
        "per_family": dict(sorted(counts.items())),
        "actual_total": total,
        "expected_manifest": dict(sorted(EXPECTED_PRIMARY_MANIFEST.items())),
        "expected_total": EXPECTED_PRIMARY_TOTAL,
        "matches_expected": counts == EXPECTED_PRIMARY_MANIFEST and total == EXPECTED_PRIMARY_TOTAL,
    }


def _inventory_financial_files(raw_root: Path) -> tuple[dict[str, Path], dict[tuple[str, str], Path]]:
    """Return exact default-TTM primary and periodic follow-up inventories from one raw-tree scan."""
    primary: dict[str, Path] = {}
    followup: dict[tuple[str, str], Path] = {}
    massive_dir = raw_root / "massive"
    if not massive_dir.exists():
        raise RuntimeError("massive raw 子树缺失（无法核对 primary/follow-up 清单）")
    for entry in massive_dir.rglob("*"):
        if entry.is_symlink():
            raise RuntimeError(
                f"massive 子树含符号链接（fail-closed）: {entry.relative_to(raw_root).as_posix()}")
    candidates = sorted(
        (p for p in raw_root.rglob("*") if p.name.lower().startswith("massive_financials")),
        key=lambda p: p.as_posix().lower(),
    )
    for path in candidates:
        if path.is_dir():
            raise RuntimeError(
                f"massive_financials 前缀目录非法（可隐藏未清点制品）: {path.relative_to(raw_root).as_posix()}")
        rel = path.relative_to(raw_root).parts
        if len(rel) != 3 or rel[0] != "massive":
            raise RuntimeError(
                f"massive_financials 制品位置非法（非 massive/<symbol>/<file>）: {path.relative_to(raw_root).as_posix()}")
        _provider, symbol, name = rel
        if name != name.lower():
            raise RuntimeError(f"massive_financials 制品名须为 canonical lowercase: {name}")
        if name == _PRIMARY_TTM_FILENAME:
            if symbol in primary:
                raise RuntimeError(f"重复的 default-TTM primary 制品: {symbol}")
            primary[symbol] = path
            continue
        if not name.endswith(".json"):
            raise RuntimeError(f"massive_financials 后续制品扩展名非法（须 .json）: {name}")
        stem = name[:-len(".json")]
        if not stem.startswith("massive_financials_"):
            raise RuntimeError(f"massive_financials 后续制品命名非法: {name}")
        timeframe = stem[len("massive_financials_"):]
        if timeframe not in _FOLLOWUP_TIMEFRAMES:
            raise RuntimeError(
                f"未授权的 periodic follow-up timeframe（须 ∈ {list(_FOLLOWUP_TIMEFRAMES)}）: {name}")
        key = (symbol, timeframe)
        if key in followup:
            raise RuntimeError(f"重复的 follow-up 制品 {key}（fail-closed）")
        followup[key] = path
    expected_primary = set(EXPECTED_PRIMARY_FINANCIAL_SYMBOLS)
    if set(primary) != expected_primary:
        raise RuntimeError(
            f"default-TTM primary 制品集合须恰为 {sorted(expected_primary)}；实得 {sorted(primary)}")
    for symbol, path in primary.items():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            raise RuntimeError(f"primary raw {path.name} 读取/解析失败（fail-closed）") from exc
        if not isinstance(doc, dict):
            raise RuntimeError(f"primary raw {symbol} 须为对象")
        if (doc.get("provider_id") != "massive"
                or doc.get("endpoint_family") != "massive_financials"
                or doc.get("symbol") != symbol):
            raise RuntimeError(f"primary raw {symbol} envelope 与 manifest 不符")
        if doc.get("http_status") != 200 or doc.get("ok") is not True:
            raise RuntimeError(f"primary raw {symbol} 必须是 HTTP 200 / ok=true")
    return primary, followup


def build_followup_execution_block(raw_root: Path) -> dict[str, Any]:
    """OFFLINE: reconstruct the separately-authorized Massive financials PERIODIC re-probe from the captured
    gitignored raw (NO network) as an EXACT, FAIL-CLOSED manifest. The namespace is inventoried EXHAUSTIVELY
    (`_inventory_financial_files` reconciles primary + follow-up and raises on any extra / renamed / misplaced
    massive_financials*), and it
    RAISES unless the present follow-up set is PRECISELY EXPECTED_FOLLOWUP_CALLS (AAPL quarterly + AAPL annual — no
    missing / extra), and EACH is HTTP 200 with a nonempty results list. Every result row is classified with the Cut
    5-b consumer's real-YYYY-MM-DD and tz-aware-RFC3339 predicates; total/valid counts and all-row flags are derived
    from the complete result list, so partial coverage is explicit rather than promoted to all-present. The envelope
    ticker/timeframe must also agree with the manifest. Thus empty / missing / forged / failed / extra evidence cannot
    become the cited periodic PIT proof, and null/invalid rows cannot be mislabeled PIT-ready. Each raw file
    is {http, payload:{results:[...]}, ticker, timeframe}."""
    primary, found = _inventory_financial_files(raw_root)     # one raw inventory for primary + follow-up
    expected = set(EXPECTED_FOLLOWUP_CALLS)
    if set(found) != expected:
        raise RuntimeError(
            f"follow-up 调用集合须恰为 {sorted(expected)}（缺/多，fail-closed）；实得 {sorted(found)}")
    calls: list[dict[str, Any]] = []
    for symbol, timeframe in EXPECTED_FOLLOWUP_CALLS:              # deterministic manifest order
        f = found[(symbol, timeframe)]
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            raise RuntimeError(f"follow-up raw {f.name} 读取/解析失败（非 UTF-8 或非合法 JSON，fail-closed）") from exc
        if not isinstance(doc, dict):
            raise RuntimeError(f"follow-up raw {f.name} 须为对象")
        if doc.get("http") != 200:
            raise RuntimeError(f"follow-up {symbol}/{timeframe} HTTP 须为 200（实得 {doc.get('http')!r}）")
        if doc.get("ticker") != symbol or doc.get("timeframe") != timeframe:
            raise RuntimeError(f"follow-up {symbol}/{timeframe} envelope ticker/timeframe 与 manifest 不符（防误配）")
        payload = doc.get("payload")
        results = payload.get("results") if isinstance(payload, dict) else None
        if not (isinstance(results, list) and results and isinstance(results[0], dict)):
            raise RuntimeError(f"follow-up {symbol}/{timeframe} results 须为非空对象列表")
        valid_filing = sum(isinstance(row, dict) and _valid_ymd(row.get("filing_date")) for row in results)
        valid_acceptance = sum(
            isinstance(row, dict) and _valid_acceptance_instant(row.get("acceptance_datetime")) for row in results)
        valid_pit = sum(
            isinstance(row, dict)
            and _valid_ymd(row.get("filing_date"))
            and _valid_acceptance_instant(row.get("acceptance_datetime"))
            for row in results
        )
        if valid_pit == 0:
            raise RuntimeError(f"follow-up {symbol}/{timeframe} 无任何 consumer-compatible PIT 行")
        calls.append({
            "symbol": symbol, "timeframe": timeframe, "http_status": 200,
            "results_count": len(results),
            "valid_filing_date_count": valid_filing,
            "valid_acceptance_datetime_count": valid_acceptance,
            "valid_pit_row_count": valid_pit,
            "all_filing_dates_valid": valid_filing == len(results),
            "all_acceptance_datetimes_valid": valid_acceptance == len(results),
            "raw_sample_ref_gitignored": True,
        })
    total_rows = sum(call["results_count"] for call in calls)
    valid_pit_rows = sum(call["valid_pit_row_count"] for call in calls)
    return {
        "authorization_ref": FOLLOWUP_AUTHORIZATION_REF,
        "purpose": "massive_financials_periodic_shape_reprobe",
        "endpoint_family": "massive_financials_periodic",
        "reason": ("the 21-call primary run probed massive_financials with the DEFAULT (ttm) timeframe, which returns "
                   "a NULL filing_date; the distinct quarterly/annual follow-up found consumer-compatible PIT rows "
                   f"for {valid_pit_rows}/{total_rows} returned rows. Coverage is partial and is recorded explicitly; "
                   "the follow-up is NOT folded into the primary budget."),
        "calls": calls,
        "call_count": len(calls),                                # == 2 (validated above)
        "primary_raw_artifact_count": len(primary),
        "primary_raw_symbols": sorted(primary),
        "total_result_count": total_rows,
        "valid_pit_row_count": valid_pit_rows,
        "all_filing_dates_valid": all(call["all_filing_dates_valid"] for call in calls),
        "all_acceptance_datetimes_valid": all(call["all_acceptance_datetimes_valid"] for call in calls),
    }


def write_json_atomic(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp_path.replace(path)


def _assert_text_safe(text: str, sensitive_values: list[str]) -> None:
    """Fail-closed scan of the serialized tracked summary: no API key, request URL, provider domain, or
    raw-payload key may appear. Mirrors the batch5 provider-live probe's forbidden set."""
    lower = text.lower()
    forbidden_fragments = [
        "apikey=",
        "financialmodelingprep.com",
        "api.massive.com",
        "data.sec.gov",
        "www.sec.gov",
        "\"payload\"",
        "\"request_url\"",
        "\"raw_payload\"",
    ]
    for fragment in forbidden_fragments:
        if fragment in lower:
            raise RuntimeError(f"tracked summary contains forbidden fragment: {fragment}")
    for value in sensitive_values:
        if value and value in text:
            raise RuntimeError("tracked summary contains a sensitive environment value")


def _validate_summary_against_schema(summary: dict) -> None:
    """Draft7-validate the summary against its schema BEFORE any write: a schema-invalid summary — a flipped
    safety flag, an illegal status, a missing section — must NEVER be written (no write-then-validate)."""
    from jsonschema import Draft7Validator
    schema = json.loads(SUMMARY_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft7Validator(schema).iter_errors(summary), key=lambda err: list(err.path))
    if errors:
        raise RuntimeError(
            "cut5 probe summary failed schema validation: "
            + "; ".join(err.message for err in errors[:5])
        )


def _write_summary_validated(summary: dict, summary_path: Path, sensitive_values: list[str]) -> None:
    """Schema-validate + secret-scan the SERIALIZED summary BEFORE the atomic write, so neither a
    schema-invalid nor a secret-bearing summary can ever hit disk. The scanned text is byte-identical to
    what write_json_atomic writes."""
    _validate_summary_against_schema(summary)
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_text_safe(text, sensitive_values)
    write_json_atomic(summary, summary_path)


# ---------------------------------------------------------------------------
# SEC §5.1a form-family extraction (diagnostics — public metadata only)
# ---------------------------------------------------------------------------

def _form_matches(form: Any, kind: str, patterns: list[str]) -> bool:
    if not isinstance(form, str):
        return False
    for pattern in patterns:
        if kind == "prefix":
            if form.startswith(pattern):
                return True
        else:  # exact_or_amend
            if form == pattern or form.startswith(pattern + "/"):
                return True
    return False


def extract_sec_form_families(payload: Any) -> dict[str, dict[str, Any]]:
    """From a SEC submissions payload, count filings per §5.1a form family and record the most-recent
    filingDate + acceptanceDateTime per family. Fail-closed on any non-dict / missing shape (empty families,
    never a crash). Only public filing metadata (form + dates) is derived — no document text, no raw rows."""
    result: dict[str, dict[str, Any]] = {}
    recent: Any = {}
    if isinstance(payload, dict):
        filings = payload.get("filings")
        if isinstance(filings, dict) and isinstance(filings.get("recent"), dict):
            recent = filings["recent"]
    forms = recent.get("form") if isinstance(recent, dict) else None
    fdates = recent.get("filingDate") if isinstance(recent, dict) else None
    adates = recent.get("acceptanceDateTime") if isinstance(recent, dict) else None
    forms = forms if isinstance(forms, list) else []
    fdates = fdates if isinstance(fdates, list) else []
    adates = adates if isinstance(adates, list) else []

    for family, (kind, patterns) in SEC_FORM_FAMILIES:
        idxs = [i for i, form in enumerate(forms) if _form_matches(form, kind, patterns)]
        if not idxs:
            result[family] = {
                "count": 0,
                "most_recent_filing_date": None,
                "most_recent_acceptance_datetime": None,
            }
            continue

        def _fdate(i: int) -> str:
            return fdates[i] if i < len(fdates) and isinstance(fdates[i], str) else ""

        best = max(idxs, key=_fdate)
        result[family] = {
            "count": len(idxs),
            "most_recent_filing_date": _fdate(best) or None,
            "most_recent_acceptance_datetime": (
                adates[best] if best < len(adates) and isinstance(adates[best], str) else None
            ),
        }
    return result


# ---------------------------------------------------------------------------
# Per-record diagnostics
# ---------------------------------------------------------------------------

def _payload_shape(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        return {"kind": "list", "row_count": len(payload)}
    if isinstance(payload, dict):
        return {"kind": "object", "row_count": None}
    if payload is None:
        return {"kind": "null", "row_count": None}
    return {"kind": type(payload).__name__, "row_count": None}


def _first_list_row(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    return None


def _fmp_endpoint_def(endpoint_family: str) -> dict[str, Any] | None:
    for endpoint in FMP_CATALYST_ENDPOINTS:
        if endpoint["endpoint_family"] == endpoint_family:
            return endpoint
    return None


def _massive_reference_def(endpoint_family: str) -> dict[str, Any] | None:
    for endpoint in MASSIVE_REFERENCE_ENDPOINTS:
        if endpoint["endpoint_family"] == endpoint_family:
            return endpoint
    if endpoint_family == MASSIVE_EARNINGS_PROBE["endpoint_family"]:
        return MASSIVE_EARNINGS_PROBE
    return None


def summarize_endpoint_record(record: sample_validation.FetchRecord) -> dict[str, Any]:
    provider = {
        "financial_modeling_prep": "FMP",
        "sec_edgar": "SEC",
        "massive": "Massive",
    }.get(record.provider_id, record.provider_id)
    result: dict[str, Any] = {
        "provider": provider,
        "endpoint_family": record.endpoint_family,
        "symbol": record.symbol,
        "status": "success" if record.ok else "error",
        "http_status": record.http_status,
        "error_type": record.error_type,
        "raw_sample_ref": record.raw_sample_ref,
        "raw_sample_ref_gitignored": record.raw_sample_ref.startswith("provider_samples/"),
        "payload_shape": _payload_shape(record.payload),
    }

    if record.provider_id == "financial_modeling_prep":
        endpoint = _fmp_endpoint_def(record.endpoint_family)
        fields = list(endpoint["fields"]) if endpoint else []
        date_fields = list(endpoint["date_fields"]) if endpoint else []
        row = _first_list_row(record.payload)
        if row is None:
            result["field_presence"] = {field: False for field in fields}
            result["date_fields_present"] = {field: False for field in date_fields}
        else:
            result["field_presence"] = {field: (field in row and row.get(field) is not None) for field in fields}
            result["date_fields_present"] = {field: (field in row and row.get(field) is not None) for field in date_fields}
        result["missing_required_fields"] = [f for f, present in result["field_presence"].items() if not present]
    elif record.provider_id == "sec_edgar" and record.endpoint_family == "submissions":
        result["form_families"] = extract_sec_form_families(record.payload)
    elif record.provider_id == "sec_edgar" and record.endpoint_family == "company_tickers_mapping":
        result["field_presence"] = {
            field: bool(_first_mapping_row(record.payload) and field in _first_mapping_row(record.payload))
            for field in ["ticker", "cik_str"]
        }
    elif record.provider_id == "massive":
        rows = record.payload.get("results") if isinstance(record.payload, dict) else None
        rows = rows if isinstance(rows, list) else []
        first = rows[0] if rows and isinstance(rows[0], dict) else None
        if record.endpoint_family == "ticker_daily_aggregates":
            result["bar_count"] = len(rows)
            result["ohlcv_fields_present"] = {
                field: bool(first and field in first and first.get(field) is not None)
                for field in MASSIVE_OHLCV_FIELDS
            }
        else:
            endpoint = _massive_reference_def(record.endpoint_family)
            fields = list(endpoint["fields"]) if endpoint else []
            date_fields = list(endpoint["date_fields"]) if endpoint else []
            result["result_count"] = len(rows)
            result["field_presence"] = {f: bool(first and f in first and first.get(f) is not None) for f in fields}
            result["date_fields_present"] = {f: bool(first and f in first and first.get(f) is not None) for f in date_fields}
            result["missing_required_fields"] = [f for f, present in result["field_presence"].items() if not present]
    return result


def _first_mapping_row(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, dict):
                return value
    return None


# ---------------------------------------------------------------------------
# Per-symbol + feasibility rollups
# ---------------------------------------------------------------------------

def _record_status(records: list[sample_validation.FetchRecord], provider_id: str, symbol: str | None,
                   family: str) -> str:
    for record in records:
        if record.provider_id == provider_id and record.symbol == symbol and record.endpoint_family == family:
            return "success" if record.ok else "error"
    return "not_called"


def summarize_symbol(symbol: str, records: list[sample_validation.FetchRecord],
                     cik_by_symbol: dict[str, str]) -> dict[str, Any]:
    submissions = next(
        (r.payload for r in records
         if r.provider_id == "sec_edgar" and r.symbol == symbol and r.endpoint_family == "submissions"),
        None,
    )
    return {
        "symbol": symbol,
        "active_symbol_assumption": True,
        "sec_cik_found": symbol in cik_by_symbol,
        "sec_cik10": cik_by_symbol.get(symbol),
        "sec_submissions_status": _record_status(records, "sec_edgar", symbol, "submissions"),
        "sec_form_families": extract_sec_form_families(submissions),
        "fmp_catalyst_status": {
            family: _record_status(records, "financial_modeling_prep", symbol, family)
            for family in FMP_CATALYST_FAMILIES
        },
    }


def _fmp_family_findings(family: str, endpoint_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [item for item in endpoint_summaries if item["provider"] == "FMP" and item["endpoint_family"] == family]
    reachable = sorted({item["symbol"] for item in rows if item["status"] == "success"})
    shape_ok = sorted({
        item["symbol"] for item in rows
        if item["status"] == "success" and not item.get("missing_required_fields")
    })
    http_statuses = sorted({item["http_status"] for item in rows if item["http_status"] is not None})
    return {
        "reachable_symbol_count": len(reachable),
        "shape_ok_symbol_count": len(shape_ok),
        "observed_http_statuses": http_statuses,
        "reachable": len(reachable) > 0,
    }


def _massive_ref_findings(family: str, endpoint_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [item for item in endpoint_summaries if item["provider"] == "Massive" and item["endpoint_family"] == family]
    reachable = sorted({item["symbol"] for item in rows if item["status"] == "success" and item["symbol"]})
    shape_ok = sorted({
        item["symbol"] for item in rows
        if item["status"] == "success" and item["symbol"] and not item.get("missing_required_fields")
    })
    http_statuses = sorted({item["http_status"] for item in rows if item["http_status"] is not None})
    return {
        "reachable_symbol_count": len(reachable),
        "shape_ok_symbol_count": len(shape_ok),
        "observed_http_statuses": http_statuses,
        "reachable": len(reachable) > 0,
    }


def build_feasibility_findings(endpoint_summaries: list[dict[str, Any]],
                               symbol_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    sec_reachable = sorted({
        item["symbol"] for item in endpoint_summaries
        if item["provider"] == "SEC" and item["endpoint_family"] == "submissions" and item["status"] == "success"
    })
    families_seen = sorted({
        family
        for sym in symbol_summaries
        for family, info in (sym.get("sec_form_families") or {}).items()
        if info.get("count", 0) > 0
    })
    massive = next((item for item in endpoint_summaries if item["provider"] == "Massive"), None)
    return {
        "sec_filing_channel": {
            "reachable_symbol_count": len(sec_reachable),
            "form_families_seen": families_seen,
            "pit_dates_available": bool(families_seen),
            "note": "SEC submissions gives form type + filingDate + acceptanceDateTime per filing — the §5.1a "
                    "recency/materiality PIT clock. Materiality (active vs stale shelf, offering size) is a "
                    "later parser concern; this probe proves the channel + dates are reachable & parseable.",
        },
        "fmp_earnings_surprises": _fmp_family_findings("earnings_surprises", endpoint_summaries),
        "fmp_analyst_estimates": _fmp_family_findings("analyst_estimates", endpoint_summaries),
        "fmp_grades": _fmp_family_findings("grades", endpoint_summaries),
        "massive_per_ticker": {
            "reachable": bool(massive and massive["status"] == "success"),
            "bar_count": (massive or {}).get("bar_count", 0),
            "ohlcv_fields_present": (massive or {}).get("ohlcv_fields_present", {}),
            "note": "Per-ticker daily aggregates for the event window (catalyst price-reaction §4.2/§5.2); "
                    "complements round-1's grouped-daily universe call.",
        },
        "massive_financials": {
            **_massive_ref_findings("massive_financials", endpoint_summaries),
            "default_timeframe_probed": "ttm",
            "filing_date_present_in_default_ttm": False,
            "periodic_shape_evidence": "pending_followup_reprobe",   # primary run: not yet reconciled; reconcile promotes to follow_up_execution
            "note": "the primary probe used the DEFAULT (ttm) timeframe, whose rollup returns a NULL filing_date, so "
                    "shape_ok_symbol_count is 0 for the filing_date PIT field. The separately-authorized PERIODIC "
                    "quarterly/annual follow-up must be reconciled before use; follow_up_execution records exact "
                    "consumer-compatible and missing/invalid row counts rather than implying full coverage.",
        },
        "massive_news": _massive_ref_findings("massive_news", endpoint_summaries),
        "massive_earnings_analyst_probe": _massive_ref_findings("massive_earnings_analyst_probe", endpoint_summaries),
        "fmp_catalyst_vs_massive_note": (
            "FMP earnings-surprises/analyst-estimates returned 404/400, so they were retried on Massive (Polygon). "
            "Polygon's reference model carries ACTUAL financials + news, but sell-side consensus/estimate/"
            "earnings-surprise is not a Polygon channel — the earnings/analyst probe records whether Massive proxies "
            "any such extension. Earnings SURPRISE needs an estimate half that no free source tried here (FMP catalyst "
            "or Massive/Polygon) returned; the actual-EPS half is available via massive_financials — but ONLY at the "
            "PERIODIC (quarterly/annual) timeframe, which carries a real filing_date (see follow_up_execution); the "
            "default ttm rollup does NOT (and FMP income-statement, proven earlier).",
        ),
        "sec_semantic_5_1b": {
            "channel": "filing_document_text",
            "reachable_via_this_probe": False,
            "note": "Going-concern / auditor-resignation / short-seller reports need filing-DOCUMENT text parsing, "
                    "not companyfacts — out of this probe's scope. Confirms the semantic_audit_unavailable default "
                    "stays honest until a document parser is built (later, gated).",
        },
    }


# ---------------------------------------------------------------------------
# Summary assembly
# ---------------------------------------------------------------------------

def build_summary(
    *,
    generated_at: str,
    env_summary: dict[str, Any],
    endpoint_records: list[sample_validation.FetchRecord],
    cik_by_symbol: dict[str, str],
    dry_run_env: bool,
    authorization_confirmed: bool,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_SAMPLE_ROOT,
) -> dict[str, Any]:
    endpoint_summaries = [summarize_endpoint_record(record) for record in endpoint_records]
    symbol_summaries = [summarize_symbol(symbol, endpoint_records, cik_by_symbol) for symbol in EXPECTED_SYMBOLS]
    endpoint_errors = sum(1 for record in endpoint_records if not record.ok)
    if dry_run_env:
        status = "dry_run_env_only"
    elif endpoint_errors:
        status = "feasibility_probe_completed_with_endpoint_errors"
    else:
        status = "feasibility_probe_completed"
    endpoint_manifest = compute_endpoint_manifest(endpoint_summaries)
    # freeze + independently recompute (Codex finding B): a completed run's per-family/total MUST equal the frozen
    # manifest, else the emitted counts are untrustworthy -> fail closed before any write.
    if not dry_run_env and not endpoint_manifest["matches_expected"]:
        raise RuntimeError(
            f"endpoint manifest mismatch: actual {endpoint_manifest['per_family']} "
            f"(total {endpoint_manifest['actual_total']}) != frozen expected (total {EXPECTED_PRIMARY_TOTAL})")

    return {
        "schema_name": "us_short_cut5_pass2_feasibility_probe_summary",
        "schema_version": "1.1.0",
        "schema_ref": "schemas/us_short_cut5_pass2_feasibility_probe_summary.schema.json",
        "authorization_ref": AUTHORIZATION_REF,
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "cut": "cut5_pass2_audit_gate_and_catalyst_data_layer",
            "purpose": "data_layer_feasibility_probe_only",
            "status": status,
            "provider_live_probe_performed": not dry_run_env,
            "raw_payload_storage_performed": not dry_run_env,
            "validation_only_raw_parse_performed": not dry_run_env,
            "binding_or_parser_built": False,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "full_market_call_performed": False,
            "yfinance_consumption_performed": False,
            "paid_tier_used": False,
            "broker_or_order_execution_performed": False,
            "manual_order_only": True,
            "ship_gate_or_live_normalized_evidence_claimed": False,
        },
        "pre_execution_checks": {
            "user_authorization_confirmed": authorization_confirmed,
            "provider_samples_gitignore_confirmed": True,
            "environment_precheck_passed": True,
            "fmp_api_key_present": env_summary["fmp_api_key_present"],
            "sec_user_agent_present": env_summary["sec_user_agent_present"],
            "massive_api_key_present": env_summary["massive_api_key_present"],
            "budget_precheck_passed": True,
            "no_yfinance": True,
            "no_datahub": True,
            "no_full_market": True,
            "no_production_storage": True,
            "no_broker_or_order_execution": True,
        },
        "environment": env_summary,
        "storage": {
            "raw_payload_root": _repo_relative(raw_root),                 # the ACTUAL resolved root (no hardcoded lie)
            "raw_payload_root_gitignored": True,
            "tracked_summary_path": _repo_relative(summary_path),         # the ACTUAL resolved destination
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_raw_payload": False,
            "secrets_in_summary": False,
            "request_urls_in_summary": False,
        },
        "sample_universe": {
            "symbol_source": "cut5_feasibility_probe_fixed_active_only_sample",
            "symbols": EXPECTED_SYMBOLS,
            "active_symbols_only": True,
            "max_symbols": len(EXPECTED_SYMBOLS),
            "full_market_sample": False,
        },
        "channels_probed": {
            "sec_submissions_form_families": [family for family, _ in SEC_FORM_FAMILIES],
            "fmp_catalyst_endpoint_families": FMP_CATALYST_FAMILIES,
            "massive_per_ticker_aggregates_symbol": MASSIVE_PROBE_SYMBOL,
            "massive_reference_endpoint_families": MASSIVE_REFERENCE_FAMILIES,
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": MAX_TOTAL_ENDPOINT_CALLS,
            "actual_total_endpoint_calls": len(endpoint_records),
            "retry_count": 0,
            "within_budget": len(endpoint_records) <= MAX_TOTAL_ENDPOINT_CALLS,
        },
        "endpoint_manifest": endpoint_manifest,
        "endpoint_results": endpoint_summaries,
        "symbol_results": symbol_summaries,
        "feasibility_findings": build_feasibility_findings(endpoint_summaries, symbol_summaries),
        "validation_decision": {
            "status": status,
            "sr_provider_001_remains_open": True,
            "provider_selection_allowed": False,
            "binding_or_parser_authorized": False,
            "datahub_allowed": False,
            "production_storage_allowed": False,
            "full_market_fetch_allowed": False,
            "ship_gate_evidence_allowed": False,
        },
        "prohibited_claims": {
            "live_normalized_evidence_claimed": False,
            "ship_gate_evidence_claimed": False,
            "production_readiness_claimed": False,
            "provider_selected": False,
            "datahub_ready": False,
            "binding_or_parser_built": False,
            "paper_result_relabelled_as_live": False,
        },
        "limitations": [
            "This is a three-symbol active-only feasibility probe of response shape / reachability, NOT coverage, "
            "PIT-semantics, license, or alpha evidence.",
            "Raw payloads are stored only under gitignored provider_samples/; the tracked summary excludes secrets, "
            "request URLs, and raw payload rows.",
            "FMP catalyst endpoints (earnings-surprises / analyst-estimates / grades) may be paid-tier — a 403/404 "
            "here is a feasibility finding, not an error to route around silently.",
            "Massive/Polygon reference financials give ACTUAL statements (with PIT filing_date) + news, but sell-side "
            "estimates / consensus / earnings-surprise are not a Polygon channel; earnings SURPRISE needs an estimate "
            "half that no free source tried here returned — only the actual-EPS half is reachable.",
            "The §5.1b semantic audit layer (going-concern / auditor-resignation / short-seller) needs filing-document "
            "text parsing and is out of scope; semantic_audit_unavailable stays the honest default.",
            "Materiality/recency logic for dilution filings (active vs stale shelf, offering size) is a later parser "
            "concern; this probe proves only that the form-type + PIT dates are reachable and parseable.",
            "No provider selection, schema-first binding, parser, DataHub, production storage, or ship-gate evidence "
            "is built or claimed; SR-PROVIDER-001 stays open.",
        ],
        "next_steps": [
            "Codex review before any commit.",
            "From the observed real shapes, decide per channel: schema-first binding + parser (if reachable + usable), "
            "or degrade/defer (if paid-walled/unreachable) — mirror the status_source / catalyst_source provenance "
            "pattern; do NOT broaden symbols, endpoints, providers, or market coverage without separate authorization.",
        ],
    }


# ---------------------------------------------------------------------------
# Massive window
# ---------------------------------------------------------------------------

def _massive_window(now: datetime | None = None) -> tuple[str, str]:
    """Recent daily window (Massive free tier is delayed, so end a few days back). Returns (from, to)."""
    now = now or datetime.now(timezone.utc)
    to = (now - timedelta(days=3)).strftime("%Y-%m-%d")
    frm = (now - timedelta(days=28)).strftime("%Y-%m-%d")
    return frm, to


# ---------------------------------------------------------------------------
# Live run
# ---------------------------------------------------------------------------

def run_probe(
    *,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_SAMPLE_ROOT,
    generated_at: str | None = None,
    client: sample_validation.JsonHttpClient | None = None,
    confirm_user_authorization: bool = False,
    dry_run_env: bool = False,
    sec_sleep_seconds: float = sample_validation.SEC_FAIR_ACCESS_SLEEP_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not confirm_user_authorization and not dry_run_env:
        raise RuntimeError("live provider execution requires --confirm-user-authorization")
    if not _provider_samples_gitignored():
        raise RuntimeError("provider_samples/ is not confirmed in .gitignore")
    _validate_raw_root(raw_root)
    _validate_summary_path(summary_path)
    generated_at = generated_at or iso_now()
    if not _valid_generated_at(generated_at):
        raise RuntimeError("generated_at must be a tz-aware RFC3339 timestamp (no free-form / date-only / naive value)")

    fmp_env = sample_validation.read_required_env("FMP_API_KEY")
    sec_env = sample_validation.read_required_env("SEC_USER_AGENT")
    massive_env = sample_validation.read_required_env("MASSIVE_API_KEY")
    env_summary = {
        "fmp_api_key_present": True,
        "fmp_api_key_source": fmp_env.source,
        "sec_user_agent_present": True,
        "sec_user_agent_source": sec_env.source,
        "massive_api_key_present": True,
        "massive_api_key_source": massive_env.source,
        "secrets_logged": False,
    }

    if dry_run_env:
        return build_summary(
            generated_at=generated_at,
            env_summary=env_summary,
            endpoint_records=[],
            cik_by_symbol={},
            dry_run_env=True,
            authorization_confirmed=confirm_user_authorization,
            summary_path=summary_path,
            raw_root=raw_root,
        )

    client = client or sample_validation.JsonHttpClient()
    records: list[sample_validation.FetchRecord] = []

    # 1) SEC ticker->CIK mapping
    sample_validation.assert_endpoint_budget_available(records, MAX_TOTAL_ENDPOINT_CALLS)
    mapping_record = sample_validation.fetch_and_store(
        client,
        url=sample_validation.sec_url("company_tickers_mapping"),
        provider_id="sec_edgar",
        endpoint_family="company_tickers_mapping",
        symbol=None,
        raw_root=raw_root,
        headers={"User-Agent": sec_env.value, "Host": "www.sec.gov"},
    )
    records.append(mapping_record)
    cik_by_symbol = sample_validation.parse_sec_cik_map(mapping_record.payload, EXPECTED_SYMBOLS)

    # 2) FMP catalyst endpoints per symbol
    fmp_headers = {"User-Agent": "StockSystem/0.1 us-short-cut5-catalyst-probe"}
    for symbol in EXPECTED_SYMBOLS:
        for endpoint in FMP_CATALYST_ENDPOINTS:
            sample_validation.assert_endpoint_budget_available(records, MAX_TOTAL_ENDPOINT_CALLS)
            records.append(
                sample_validation.fetch_and_store(
                    client,
                    url=sample_validation.fmp_url(
                        endpoint["path_template"], symbol, endpoint["params"], fmp_env.value,
                        endpoint_mode="stable",
                    ),
                    provider_id="financial_modeling_prep",
                    endpoint_family=endpoint["endpoint_family"],
                    symbol=symbol,
                    raw_root=raw_root,
                    headers=fmp_headers,
                )
            )

    # 3) SEC submissions per symbol (form-type breakdown)
    for symbol in EXPECTED_SYMBOLS:
        cik10 = cik_by_symbol.get(symbol)
        if not cik10:
            continue
        sample_validation.assert_endpoint_budget_available(records, MAX_TOTAL_ENDPOINT_CALLS)
        time.sleep(sec_sleep_seconds)
        records.append(
            sample_validation.fetch_and_store(
                client,
                url=sample_validation.sec_url("submissions", cik10),
                provider_id="sec_edgar",
                endpoint_family="submissions",
                symbol=symbol,
                raw_root=raw_root,
                headers={"User-Agent": sec_env.value, "Host": "data.sec.gov"},
            )
        )

    # 4) Massive per-ticker daily aggregates (one symbol)
    frm, to = _massive_window(now)
    sample_validation.assert_endpoint_budget_available(records, MAX_TOTAL_ENDPOINT_CALLS)
    records.append(
        sample_validation.fetch_and_store(
            client,
            url=MASSIVE_AGG_URL.format(ticker=MASSIVE_PROBE_SYMBOL, frm=frm, to=to, key=massive_env.value),
            provider_id="massive",
            endpoint_family="ticker_daily_aggregates",
            symbol=MASSIVE_PROBE_SYMBOL,
            raw_root=raw_root,
            headers={"User-Agent": "StockSystem/0.1 us-short-cut5-massive-probe"},
        )
    )

    # 5) Massive/Polygon REFERENCE channels (financials + news per symbol) + one earnings/analyst probe —
    #    user-requested retry of the data FMP could not serve (earnings-surprises 404 / analyst-estimates 400).
    massive_ref_headers = {"User-Agent": "StockSystem/0.1 us-short-cut5-massive-reference-probe"}
    for symbol in EXPECTED_SYMBOLS:
        for endpoint in MASSIVE_REFERENCE_ENDPOINTS:
            sample_validation.assert_endpoint_budget_available(records, MAX_TOTAL_ENDPOINT_CALLS)
            records.append(
                sample_validation.fetch_and_store(
                    client,
                    url=endpoint["url_template"].format(ticker=symbol, key=massive_env.value),
                    provider_id="massive",
                    endpoint_family=endpoint["endpoint_family"],
                    symbol=symbol,
                    raw_root=raw_root,
                    headers=massive_ref_headers,
                )
            )
    sample_validation.assert_endpoint_budget_available(records, MAX_TOTAL_ENDPOINT_CALLS)
    records.append(
        sample_validation.fetch_and_store(
            client,
            url=MASSIVE_EARNINGS_PROBE["url_template"].format(ticker=MASSIVE_PROBE_SYMBOL, key=massive_env.value),
            provider_id="massive",
            endpoint_family=MASSIVE_EARNINGS_PROBE["endpoint_family"],
            symbol=MASSIVE_PROBE_SYMBOL,
            raw_root=raw_root,
            headers=massive_ref_headers,
        )
    )

    if len(records) > MAX_TOTAL_ENDPOINT_CALLS:
        raise RuntimeError(f"endpoint call count {len(records)} exceeded budget {MAX_TOTAL_ENDPOINT_CALLS}")

    summary = build_summary(
        generated_at=generated_at,
        env_summary=env_summary,
        endpoint_records=records,
        cik_by_symbol=cik_by_symbol,
        dry_run_env=False,
        authorization_confirmed=confirm_user_authorization,
        summary_path=summary_path,
        raw_root=raw_root,
    )
    if not summary["endpoint_call_budget"]["within_budget"]:
        raise RuntimeError("endpoint call budget check failed after execution")
    _write_summary_validated(summary, summary_path, [fmp_env.value, sec_env.value, massive_env.value])
    return summary


def reconcile_summary(
    *,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_SAMPLE_ROOT,
) -> dict[str, Any]:
    """OFFLINE reconciliation — NO network / provider call. Amend the tracked summary from the EXISTING evidence:
    (1) add the `follow_up_execution` block reconstructed from the captured gitignored quarterly/annual raw (the two
    calls Codex found omitted); (2) add the recomputed `endpoint_manifest`; (3) emit the ACTUAL resolved storage
    paths; (4) split the massive_financials finding into default-ttm (no filing_date) vs periodic (proven in the
    follow-up). The primary 21-call diagnostics are unchanged (they were already validated). Re-validates against
    the schema + secret-scans before the atomic re-write (Codex finding A)."""
    _validate_summary_path(summary_path)
    _validate_raw_root(raw_root)          # symmetry with run_probe: reconcile only from THIS probe's own gitignored raw
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not _valid_generated_at(summary.get("generated_at")):
        raise RuntimeError("existing summary generated_at is not a tz-aware RFC3339 timestamp; refusing to reconcile")
    summary["endpoint_manifest"] = compute_endpoint_manifest(summary["endpoint_results"])
    summary["schema_version"] = "1.1.0"
    summary["follow_up_execution"] = build_followup_execution_block(raw_root)
    summary["storage"]["raw_payload_root"] = _repo_relative(raw_root)
    summary["storage"]["tracked_summary_path"] = _repo_relative(summary_path)
    ff = summary["feasibility_findings"]
    ff["massive_financials"] = {
        **{k: v for k, v in ff.get("massive_financials", {}).items()
           if k in ("reachable_symbol_count", "shape_ok_symbol_count", "observed_http_statuses", "reachable")},
        "default_timeframe_probed": "ttm",
        "filing_date_present_in_default_ttm": False,
        "periodic_shape_evidence": "follow_up_execution",
        "note": "the primary probe used the DEFAULT (ttm) timeframe, whose rollup returns a NULL filing_date, so "
                "shape_ok_symbol_count is 0 for the filing_date PIT field. The distinct PERIODIC quarterly/annual "
                "follow-up contains consumer-compatible PIT rows, but row coverage is partial; exact total/valid/" 
                "invalid counts are frozen in follow_up_execution and no missing-clock row is represented as ready.",
    }
    partial_note = ("Massive periodic-financials PIT coverage is partial: follow_up_execution freezes total and "
                    "consumer-compatible row counts; null/invalid-clock rows are not PIT-ready evidence.")
    summary["limitations"] = [x for x in summary["limitations"] if not x.startswith(
        "Massive periodic-financials PIT coverage is partial:")]
    summary["limitations"].append(partial_note)
    _write_summary_validated(summary, summary_path, [])   # offline: no env secrets loaded to scan against
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "US-short Cut 5 Pass-2 audit-gate + catalyst DATA-LAYER feasibility probe (gated small sample). "
            "Raw payloads go only under gitignored provider_samples/; the tracked summary carries no secrets, "
            "URLs, or raw rows."
        )
    )
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_SAMPLE_ROOT)
    parser.add_argument("--generated-at")
    parser.add_argument("--dry-run-env", action="store_true",
                        help="Validate env/storage boundary in memory only; no network, no writes.")
    parser.add_argument("--confirm-user-authorization", action="store_true",
                        help="Required for live/provider execution; documents the separate user authorization.")
    parser.add_argument("--reconcile-from-raw", action="store_true",
                        help="OFFLINE: amend the tracked summary from the existing gitignored raw (add the "
                             "quarterly/annual follow-up block + endpoint manifest). No network, no provider call.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.reconcile_from_raw:
        summary = reconcile_summary(summary_path=args.summary_path, raw_root=args.raw_root)
    else:
        summary = run_probe(
            summary_path=args.summary_path,
            raw_root=args.raw_root,
            generated_at=args.generated_at,
            confirm_user_authorization=args.confirm_user_authorization,
            dry_run_env=args.dry_run_env,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
