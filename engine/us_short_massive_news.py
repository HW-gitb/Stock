# -*- coding: utf-8 -*-
"""US-short MASSIVE news source — batch5 Cut 5, slice 5-d (offline half).

Design authority: docs/us_short_system_design.md §4.2 (catalyst: 新闻事件 — 8-K/订单/产品/监管/LLM 语义) /
§5.1b (news 类: 正式做空报告/欺诈指控 = advisory-first) / §3.1 (provenance) / §3.5 (发布时刻与 as_of 是不同 PIT
事实; 不用 look-ahead) / §18.2 (跨模块契约先 schema-first 冻结再消费). Frozen contract:
docs/us_short_cut5_massive_news_binding_20260701.json (+ its schema; module consts below are triangulated ==
that binding by a conformance test).

WHAT THIS IS — the OFFLINE half of the (SR-PROVIDER-001-gated) Massive news data layer. Reachability + real shape
were PROVEN 2026-07-01 (docs/us_short_cut5_pass2_feasibility_probe_summary_20260701.json + captured gitignored
raw): Massive/Polygon /v2/reference/news returns a list of items each {id, published_utc, publisher{name,...},
title, article_url, tickers[], insights[{ticker, sentiment, sentiment_reasoning}], ...}; `insights` carries
PER-TICKER sentiment ∈ {positive, negative, neutral}. This layer takes INJECTED per-ticker Massive news (the gated
live half fetches it), applies the repo's SINGLE US-ticker identity policy (`canonical_us_ticker`), validates the
pull's §3.1 provenance + coverage/parser fitness, PIT-cuts each item to its `published_utc` ET date (<= as_of)
within a recency window, extracts the TICKER-SPECIFIC sentiment from Massive's own insights (no LLM), and
summarizes the recent items into a §4.2 news-catalyst fact + sentiment tally + the §5.1b advisory basis.

A news article covers MULTIPLE tickers; the per-ticker sentiment is the `insights` entry whose ticker == this
canonical ticker (a missing / out-of-enum sentiment yields `unknown`, NEVER a fabricated positive/negative). The
item's `tickers` list must include this ticker (else it was mis-attributed -> fail closed).

WHAT THIS IS NOT — no fetch (no network/provider; SR-PROVIDER-001 gates the live half + the runner wiring), does
NOT SCORE (this is the fact+tally layer; the catalyst news-component / §5.1b advisory-escalation wiring is a later
seam), does NOT perform LLM SEMANTIC judgment (§5.1b reasoning stays gated/advisory — only Massive's own insights
sentiment is tallied; title/url/reasoning are carried for a later read), and does NOT cross A-share. Only the
offline contract SHAPE is frozen here.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from engine.us_short_eligibility_gate import canonical_us_ticker  # the repo's single US ticker identity policy

BINDING_PATH = (Path(__file__).resolve().parents[1]
                / "docs" / "us_short_cut5_massive_news_binding_20260701.json")

PROVIDER_ID = "massive"
ENDPOINT = "reference_news"
_DECISION_TZ_NAME = "America/New_York"
_RECENCY_WINDOW_DAYS = 30                                # news is time-sensitive -> tighter than the 90-day siblings
_SENTIMENT_ALLOWED = frozenset({"positive", "negative", "neutral"})
_SENTIMENT_UNKNOWN = "unknown"                           # no ticker-specific insight / out-of-enum -> unknown (not fabricated)
_RECORD_REQUIRED = ("id", "published_utc", "publisher", "title", "tickers", "insights")
_PROVENANCE_FIELDS = frozenset({"provider_id", "endpoint_or_filing_type", "source_as_of",
                                "observed_at", "coverage_status", "parser_status", "lineage_ref"})
_COVERAGE_ALLOWED = frozenset({"full", "partial", "missing"})
_PARSER_ALLOWED = frozenset({"ok", "degraded", "failed"})
_COVERAGE_EMIT = "full"
_PARSER_EMIT = "ok"
_RECORD_KEYS = frozenset({"records", "provenance"})
_DECISION_CUTOFF_HHMM = (9, 30)                          # decision-session open (§2.1); observed_at must be strictly before
# Machine-readable PIT / identity / publisher-normalization / checked-empty / authorization POLICY consts —
# triangulated == the binding's frozen fields (a conformance test asserts equality), so the offline shared contract
# §18.2 requires cannot drift (Codex Cut5 finding D: freeze the POLICIES, not just the vocabularies).
_CUTOFF_OPERATOR = "strictly_before"                     # observed_at < decision_open (half-open, matches resolve_canonical_asof)
_CUTOFF_REFERENCE = "decision_session_open"              # the 09:30 ET open on as_of
_CHRONOLOGY_ORDER = ("published_utc", "observed_at", "source_as_of", "as_of")   # each <= the next (non-decreasing)
_LINEAGE_REF_FORMAT = "provider_id:endpoint_or_filing_type:source_as_of#record_id"
_DUPLICATE_IDENTITY = "id"                               # Massive news item id is the source-row identity
_DUPLICATE_POLICY = "reject"                             # a repeated id fails closed (never double-counted into count/net)
_PUBLISHER_NORMALIZATION = "strip_and_casefold"          # `Pub`/` pub `/`PUB` are ONE publisher for distinct_publishers
_CHECKED_EMPTY_DISPOSITION = "checked_no_recent_news"    # full/ok + zero in-window news -> retained coverage proof
_AUTHORIZATION_BOUNDARY = {
    "live_fetch": False, "network": False, "raw_capture": False, "runner_wired": False,
    "datahub": False, "production": False, "ship_gate": False,
}


class MassiveNewsError(ValueError):
    """An injected Massive news payload is malformed / mis-provenanced / PIT-inconsistent / mis-attributed, or a
    source's ticker keys alias to the same canonical US ticker (fail-closed; never fabricates news sentiment)."""


def _valid_ymd(s: Any) -> bool:
    if not (type(s) is str and len(s) == 10 and s.isascii()):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _valid_rfc3339(s: Any) -> bool:
    """Strict RFC3339-like tz-AWARE date-time ('T' + offset/Z). Used for both provenance observed_at and each
    item's published_utc (mirrors the sibling sources' single convention)."""
    if not (type(s) is str and "T" in s):
        return False
    try:
        dt = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        return False
    return dt.tzinfo is not None


def _et_tz():
    """The canonical decision timezone (America/New_York, DST-aware), or fail-closed (raise) if no tz database."""
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    except ImportError as exc:
        raise MassiveNewsError("无 zoneinfo，无法归一化决策时区，拒绝降级") from exc
    try:
        return ZoneInfo(_DECISION_TZ_NAME)
    except ZoneInfoNotFoundError as exc:
        raise MassiveNewsError(f"无 {_DECISION_TZ_NAME} 时区库(tzdata)，无法归一化决策时区，拒绝降级") from exc


def _et_instant(ts: str) -> datetime:
    """A tz-aware RFC3339 instant as an ET-normalized aware datetime (DST-aware), so a caller's offset cannot shift
    the PIT instant/date. Fail-closed (raise MassiveNewsError) on an out-of-range boundary-year timestamp whose tz
    conversion would otherwise leak a raw OverflowError. Assumes `ts` passed `_valid_rfc3339` (exact str). Shared by
    the observation instant, the decision cutoff comparison, and each item's published_utc."""
    tz = _et_tz()
    inst = datetime.fromisoformat(ts[:-1] + "+00:00" if ts.endswith("Z") else ts)
    try:
        return inst.astimezone(tz)
    except (OverflowError, OSError) as exc:            # absurd boundary-year clock -> MassiveNewsError, not raw OverflowError
        raise MassiveNewsError(f"时间戳超出可归一化时区范围（非真实 provider 时钟）: {ts!r}") from exc


def _et_date(ts: str):
    """The tz-aware instant's ET calendar date (DST-aware). Assumes `ts` passed `_valid_rfc3339`."""
    return _et_instant(ts).date()


def _decision_cutoff(as_of: str) -> datetime:
    """The canonical decision cutoff = the decision-session 09:30 ET open on `as_of` (§2.1). `observed_at` must be
    STRICTLY before this instant (half-open window; 09:30 itself is out-of-window, matching resolve_canonical_asof).
    Assumes `as_of` already passed `_valid_ymd` (YYYY-MM-DD)."""
    return datetime(int(as_of[:4]), int(as_of[5:7]), int(as_of[8:10]),
                    _DECISION_CUTOFF_HHMM[0], _DECISION_CUTOFF_HHMM[1], tzinfo=_et_tz())


def _valid_lineage_ref(ref: Any, *, source_as_of: str) -> bool:
    if not (type(ref) is str and ref.isascii()):
        return False
    prefix, sep, rid = ref.rpartition("#")
    if sep != "#" or not rid or any(c.isspace() for c in rid) or ":" in rid or "#" in rid:
        return False
    return prefix == f"{PROVIDER_ID}:{ENDPOINT}:{source_as_of}"


def _validate_provenance(prov: Any, *, ticker: str, as_of: str) -> datetime:
    """Fail-closed §3.1/§3.5 provenance check for ONE ticker's news pull (mirrors the sibling sources). The
    observed_at is a tz-aware INSTANT STRICTLY before the 09:30 ET decision open on as_of (half-open); chronology
    `observed_at ET date <= source_as_of <= as_of`. Returns the ET-normalized observation instant (so each item's
    published_utc can be bound to the observation: published <= observed)."""
    if not (isinstance(prov, dict) and all(type(pk) is str for pk in prov) and set(prov) == _PROVENANCE_FIELDS):
        raise MassiveNewsError(f"[{ticker}].provenance 键须恰为精确 str 的 {sorted(_PROVENANCE_FIELDS)}（§3.1，fail-closed）")
    if (type(prov["provider_id"]) is not str or type(prov["endpoint_or_filing_type"]) is not str
            or prov["provider_id"] != PROVIDER_ID or prov["endpoint_or_filing_type"] != ENDPOINT):
        raise MassiveNewsError(f"[{ticker}].provenance provider/endpoint 与冻结 binding 不符（须 {PROVIDER_ID}/{ENDPOINT}）")
    src_as_of = prov["source_as_of"]
    if not _valid_ymd(src_as_of):
        raise MassiveNewsError(f"[{ticker}].provenance source_as_of 须为真实 YYYY-MM-DD")
    if not _valid_rfc3339(prov["observed_at"]):
        raise MassiveNewsError(f"[{ticker}].provenance observed_at 须为 tz-aware RFC3339 时间戳（§3.5 决策截止需瞬时精度，非日期）")
    # A-clock (HALF-OPEN [prior_close, decision_open), §2.1/§3.5): observation INSTANT STRICTLY before the 09:30 ET
    # decision open on as_of — exactly 09:30 is OUT-OF-WINDOW (matching resolve_canonical_asof).
    obs_dt = _et_instant(prov["observed_at"])
    if obs_dt >= _decision_cutoff(as_of):
        raise MassiveNewsError(
            f"[{ticker}].provenance observed_at 不早于决策开盘（{as_of} 09:30 ET 半开边界；09:30 及之后 out-of-window/look-ahead，§2.1/§3.5）")
    obs_date = obs_dt.strftime("%Y-%m-%d")
    if not (obs_date <= src_as_of):
        raise MassiveNewsError(f"[{ticker}].provenance source_as_of 早于观测日期（源快照不能早于它含的证据；§3.5）")
    if not (src_as_of <= as_of):
        raise MassiveNewsError(f"[{ticker}].provenance source_as_of 晚于决策 as_of={as_of}（look-ahead；§3.5）")
    if type(prov["coverage_status"]) is not str or prov["coverage_status"] not in _COVERAGE_ALLOWED:
        raise MassiveNewsError(f"[{ticker}].provenance coverage_status 非法（须 ∈ {sorted(_COVERAGE_ALLOWED)}）")
    if type(prov["parser_status"]) is not str or prov["parser_status"] not in _PARSER_ALLOWED:
        raise MassiveNewsError(f"[{ticker}].provenance parser_status 非法（须 ∈ {sorted(_PARSER_ALLOWED)}）")
    if not _valid_lineage_ref(prov["lineage_ref"], source_as_of=src_as_of):
        raise MassiveNewsError(
            f"[{ticker}].provenance lineage_ref 须为结构化 source-bound 引用 "
            f"'{PROVIDER_ID}:{ENDPOINT}:{src_as_of}#<record_id>'（非自由文本）")
    return obs_dt


def _canonical_keyed(news_by_ticker: Any) -> dict:
    """Re-key {ticker: {records, provenance}} by canonical US ticker (mirrors the sibling hostile-key hardening)."""
    if news_by_ticker is None:
        return {}
    if not isinstance(news_by_ticker, dict):
        raise MassiveNewsError(f"news_by_ticker 须为 dict 或 None: {type(news_by_ticker).__name__}")
    out: dict[str, dict] = {}
    for k, v in news_by_ticker.items():
        if type(k) is not str:
            continue
        ck = canonical_us_ticker(k)
        if ck is None:
            continue
        if not isinstance(v, dict):
            raise MassiveNewsError(f"[{ck}] 记录须为 dict: {type(v).__name__}")
        if not all(type(rk) is str for rk in v):
            raise MassiveNewsError(f"[{ck}] 记录键须为精确 str（拒 str 子类/非串，fail-closed，不回显敌意键）")
        if set(v) != _RECORD_KEYS:
            raise MassiveNewsError(f"[{ck}] 记录键须恰为 {sorted(_RECORD_KEYS)}（fail-closed，不回显实际键）")
        if ck in out:
            raise MassiveNewsError(f"规范化后重复 ticker {ck!r}（别名歧义，fail-closed；不静默去重）")
        out[ck] = v
    return out


def _ticker_sentiment(insights: list, *, ticker: str) -> tuple[str, str | None]:
    """Return (sentiment, reasoning) for THIS ticker from Massive's per-ticker `insights`. The first insight whose
    canonical ticker == this ticker drives it: an in-enum sentiment -> that sentiment; an out-of-enum/malformed
    sentiment -> unknown (conservative, never fabricated). No matching ticker-specific insight -> (unknown, None).
    Non-dict insight elements are tolerated (skipped) — an external provider list may vary."""
    for ins in insights:
        if not isinstance(ins, dict):
            continue
        t = ins.get("ticker")
        if type(t) is str and canonical_us_ticker(t) == ticker:   # EXACT str before canonical (hostile subclass .isascii/.strip/.upper)
            sentiment = ins.get("sentiment")
            reasoning = ins.get("sentiment_reasoning") if isinstance(ins.get("sentiment_reasoning"), str) else None
            # isinstance-guard BEFORE the enum membership test: an UNHASHABLE (list/dict) sentiment from a hostile
            # payload would otherwise raise a raw `TypeError` past the MassiveNewsError contract (mirror-safety
            # divergence — the sibling fmp_analyst_grades string-validates `action` before its enum lookup). A
            # non-str / out-of-enum sentiment folds to unknown per contract, never fabricated positive/negative.
            return (sentiment if type(sentiment) is str and sentiment in _SENTIMENT_ALLOWED
                    else _SENTIMENT_UNKNOWN), reasoning
    return _SENTIMENT_UNKNOWN, None


def _classify_news_record(record: Any, *, ticker: str, as_of: str, observed_at_et: datetime,
                          window: int) -> tuple[str, dict | None]:
    """Validate ONE injected Massive news item -> ("fit", record) | ("future", None) | ("stale", None). A
    structurally malformed item (non-dict, missing a required key, bad-SHAPE published_utc, non-str/empty
    id/title, publisher without a non-blank str name, non-list tickers/insights, or a `tickers` list NOT covering
    this ticker) FAILS CLOSED (raise). An item published AFTER the observation instant (`published_utc > observed`)
    is excluded — event-after-observation look-ahead (§3.5); older than `window` (from as_of) is out-of-window. The
    publisher name is normalized (whitespace-collapsed, case preserved) so distinct_publishers can casefold. Extra
    Massive keys (author/description/keywords/image_url) are tolerated."""
    if not isinstance(record, dict):
        raise MassiveNewsError(f"[{ticker}] news item 须为 dict: {type(record).__name__}")
    for field in _RECORD_REQUIRED:
        if field not in record:
            raise MassiveNewsError(f"[{ticker}] news item 缺必需字段 {field!r}（fail-closed）")
    item_id = record["id"]
    if not (type(item_id) is str and item_id):   # EXACT str: id is hashed into seen_ids + echoed on dup (hostile subclass hash/repr)
        raise MassiveNewsError(f"[{ticker}] news item id 须为非空字符串")
    published = record["published_utc"]
    if not _valid_rfc3339(published):
        raise MassiveNewsError(f"[{ticker}] news item published_utc 须为 tz-aware RFC3339 时间戳（坏形状不静默丢；不回显敌意值，仅类型 {type(published).__name__}）")
    publisher = record["publisher"]
    if not isinstance(publisher, dict):
        raise MassiveNewsError(f"[{ticker}] news item publisher 须为 dict")
    publisher_name = publisher.get("name")
    if not (type(publisher_name) is str and publisher_name.strip()):   # EXACT str before .split()/.casefold() (hostile subclass)
        raise MassiveNewsError(f"[{ticker}] news item publisher.name 须为非空、非纯空白字符串")
    publisher_name = " ".join(publisher_name.split())   # collapse interior/edge whitespace (case preserved)
    title = record["title"]
    if not (isinstance(title, str) and title):
        raise MassiveNewsError(f"[{ticker}] news item title 须为非空字符串")
    tickers = record["tickers"]
    if not isinstance(tickers, list):
        raise MassiveNewsError(f"[{ticker}] news item tickers 须为 list")
    if ticker not in {canonical_us_ticker(t) for t in tickers if type(t) is str}:   # EXACT str before canonical (hostile subclass)
        raise MassiveNewsError(f"[{ticker}] news item 的 tickers 未覆盖本票（误 attribution，fail-closed）")
    insights = record["insights"]
    if not isinstance(insights, list):
        raise MassiveNewsError(f"[{ticker}] news item insights 须为 list")
    article_url = record.get("article_url")
    if article_url is not None and not isinstance(article_url, str):
        raise MassiveNewsError(f"[{ticker}] news item article_url 若存在须为字符串")

    # PIT cut (event <= observed): a news item published AFTER the observation instant (observed is already STRICTLY
    # before the 09:30 decision open) is look-ahead -> excluded (§3.5). published_utc is an instant; compare instants.
    if _et_instant(published) > observed_at_et:
        return ("future", None)
    published_et = _et_date(published)
    if (datetime.strptime(as_of, "%Y-%m-%d").date() - published_et).days > window:
        return ("stale", None)                             # older than the recency window (from as_of) -> out-of-window
    sentiment, reasoning = _ticker_sentiment(insights, ticker=ticker)
    return ("fit", {"id": item_id, "published_utc": published, "publisher_name": publisher_name, "title": title,
                    "article_url": article_url, "sentiment": sentiment, "sentiment_reasoning": reasoning})


def resolve_news_events(*, as_of: str, news_by_ticker: Any) -> dict[str, Any]:
    """Resolve injected Massive news -> per-ticker recent-window news facts + a sentiment tally, keyed by canonical
    US ticker, with validated §3.1/§3.5 provenance + PIT + coverage/parser fitness.

    `as_of` = the reviewed decision clock (YYYY-MM-DD). Each ticker record = {"records": [ <Massive news item:
    id, published_utc, publisher{name}, title, tickers[], insights[{ticker, sentiment, sentiment_reasoning}], ...>
    ], "provenance": {...7 §3.1 fields}}. Provenance is validated BEFORE emit; a ticker is EMITTED only when
    coverage=='full' AND parser=='ok', else EXCLUDED. Each item is PIT-cut to its published_utc INSTANT bound to the
    observation (published_utc <= observed, observed strictly before the 09:30 ET decision open); an item published
    after the observation is excluded (look-ahead), an out-of-window (older than window from as_of) item
    counted-not-scored. A duplicate item `id` fails closed (no inflated count/net). Per-ticker sentiment comes from
    Massive's own insights (unknown when absent/out-of-enum). A full/ok ticker with ZERO in-window items emits an
    explicit CHECKED coverage record (disposition `checked_no_recent_news`) retaining its provenance — DISTINCT from
    a never-queried ticker (§3.3).

    Returns {signals: {ticker: {news_recent: {news_count, distinct_publishers, positive, negative, neutral,
    unknown, net_sentiment, window_days}}}, records: {ticker: [ {id, published_utc, publisher_name, title,
    article_url, sentiment, sentiment_reasoning} ... sorted by published_utc ]}, provenance: {ticker: {...7 §3.1
    fields, total_record_count, out_of_window_count, future_excluded_count}}, excluded: {ticker: reason}, checked:
    {ticker: {disposition, coverage_status, parser_status, total_record_count, out_of_window_count,
    future_excluded_count}}}. Raises MassiveNewsError on any malformed / PIT-inconsistent / mis-attributed input.
    """
    if not _valid_ymd(as_of):
        raise MassiveNewsError(f"as_of 须为真实 YYYY-MM-DD 决策时钟（不回显敌意值，仅类型 {type(as_of).__name__}）")
    canon = _canonical_keyed(news_by_ticker)
    signals: dict[str, dict] = {}
    records: dict[str, list] = {}
    provenance: dict[str, dict] = {}
    excluded: dict[str, str] = {}
    checked: dict[str, dict] = {}
    for ct, rec in canon.items():
        prov = rec["provenance"]
        obs_dt = _validate_provenance(prov, ticker=ct, as_of=as_of)     # fail-closed before any emit; returns ET instant
        if prov["coverage_status"] != _COVERAGE_EMIT or prov["parser_status"] != _PARSER_EMIT:
            excluded[ct] = f"coverage={prov['coverage_status']}/parser={prov['parser_status']}"
            continue
        raw_records = rec["records"]
        if not isinstance(raw_records, list):
            raise MassiveNewsError(f"[{ct}].records 须为 list: {type(raw_records).__name__}")
        fit: list[dict] = []
        seen_ids: set[str] = set()
        future_n = stale_n = 0
        for r in raw_records:
            disposition, parsed = _classify_news_record(
                r, ticker=ct, as_of=as_of, observed_at_et=obs_dt, window=_RECENCY_WINDOW_DAYS)
            if disposition == "fit":
                if parsed["id"] in seen_ids:                             # id is the source-row identity
                    raise MassiveNewsError(
                        f"[{ct}] news item id {parsed['id']!r} 重复（source-row 不唯一，fail-closed；不静默去重/双计）")
                seen_ids.add(parsed["id"])
                fit.append(parsed)
            elif disposition == "future":
                future_n += 1
            else:
                stale_n += 1
        base_prov = {k: prov[k] for k in _PROVENANCE_FIELDS}
        counts = {"total_record_count": len(raw_records), "out_of_window_count": stale_n,
                  "future_excluded_count": future_n}
        if not fit:
            # full/ok + no in-window news: emit a CHECKED coverage proof, retaining provenance so a consumer can
            # tell "checked, no recent news" from "never queried" (§3.3, finding C).
            checked[ct] = {"disposition": _CHECKED_EMPTY_DISPOSITION, "coverage_status": prov["coverage_status"],
                           "parser_status": prov["parser_status"], **counts}
            provenance[ct] = {**base_prov, **counts}
            continue
        fit.sort(key=lambda r: (r["published_utc"], r["id"]))
        positive = sum(1 for r in fit if r["sentiment"] == "positive")
        negative = sum(1 for r in fit if r["sentiment"] == "negative")
        neutral = sum(1 for r in fit if r["sentiment"] == "neutral")
        unknown = sum(1 for r in fit if r["sentiment"] == _SENTIMENT_UNKNOWN)
        distinct_publishers = len({r["publisher_name"].casefold() for r in fit})   # `Pub`/` pub `/`PUB` -> one
        signals[ct] = {"news_recent": {
            "news_count": len(fit), "distinct_publishers": distinct_publishers,
            "positive": positive, "negative": negative, "neutral": neutral, "unknown": unknown,
            "net_sentiment": positive - negative, "window_days": _RECENCY_WINDOW_DAYS}}
        records[ct] = fit
        provenance[ct] = {**base_prov, **counts}
    return {"signals": signals, "records": records, "provenance": provenance, "excluded": excluded, "checked": checked}


def load_binding() -> dict:
    """Load the frozen binding JSON (for the conformance test that triangulates module consts == binding)."""
    return json.loads(BINDING_PATH.read_text(encoding="utf-8"))
