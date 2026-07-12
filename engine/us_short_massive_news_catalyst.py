"""US-short Massive news -> catalyst projection seam.

Pure offline glue. It consumes the already-resolved Massive news fact/tally
output, validates the source shape, maps the source's own per-ticker
net_sentiment/news_count tally into the existing low-weight catalyst
semantic_advisory channel, calls catalyst_block, and projects the result onto
the target row set for the score composer.

No provider call, no LLM call, no DataHub write, no production runner wiring.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from engine.us_short_catalyst import catalyst_block
from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_massive_news import (
    ENDPOINT as MASSIVE_NEWS_ENDPOINT,
    PROVIDER_ID as MASSIVE_PROVIDER_ID,
    _CHECKED_EMPTY_DISPOSITION,
    _COVERAGE_EMIT as MASSIVE_NEWS_COVERAGE_EMIT,
    _LINEAGE_REF_FORMAT,
    _PARSER_EMIT as MASSIVE_NEWS_PARSER_EMIT,
    _PROVENANCE_FIELDS as MASSIVE_NEWS_PROVENANCE_FIELDS,
    _RECENCY_WINDOW_DAYS,
)
from engine.us_short_seam_catalyst import (
    COVERAGE_DISPOSITIONS,
    DISPOSITION_NEUTRAL_MISSING_SOURCE,
    DISPOSITION_NEUTRAL_NO_REALIZED,
    DISPOSITION_NEUTRAL_SOURCE_EXCLUDED,
    DISPOSITION_SCORED_REALIZED,
    OUTPUT_KEYS,
)


BINDING_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "us_short_massive_news_catalyst_binding_20260704.json"
)
PRODUCER_REFS = (
    "engine/us_short_massive_news.py::resolve_news_events",
    "engine/us_short_catalyst.py::catalyst_block",
)
PROJECTION_POLICY = "massive_news_sentiment_tally_then_bounded_catalyst_projection"

SOURCE_RESULT_KEYS = frozenset({"signals", "records", "provenance", "excluded", "checked"})
SIGNAL_ROW_KEYS = frozenset({"news_recent"})
SUMMARY_KEY = "news_recent"
SUMMARY_FIELDS = (
    "news_count",
    "distinct_publishers",
    "positive",
    "negative",
    "neutral",
    "unknown",
    "net_sentiment",
    "window_days",
)
SUMMARY_FIELD_SET = frozenset(SUMMARY_FIELDS)
RECORD_KEYS = frozenset({
    "id",
    "published_utc",
    "publisher_name",
    "title",
    "article_url",
    "sentiment",
    "sentiment_reasoning",
})
CHECKED_ROW_KEYS = frozenset({
    "disposition",
    "coverage_status",
    "parser_status",
    "total_record_count",
    "out_of_window_count",
    "future_excluded_count",
})
PROVENANCE_COUNT_KEYS = ("total_record_count", "out_of_window_count", "future_excluded_count")
PROVENANCE_ROW_KEYS = frozenset(MASSIVE_NEWS_PROVENANCE_FIELDS) | frozenset(PROVENANCE_COUNT_KEYS)
CATALYST_SIGNAL_KEY = "semantic_advisory_score"
CATALYST_DATE_KEY = "semantic_advisory_date"
NEWS_SCORE_FORMULA = "net_sentiment / news_count"
SOURCE_AS_OF_POLICY = "must_equal_catalyst_as_of_date"
EMISSION_FITNESS = "coverage_status=full AND parser_status=ok"
LINEAGE_REF_FORMAT = _LINEAGE_REF_FORMAT
_BLOCK_MIN, _BLOCK_MAX = 0.0, 100.0


class MassiveNewsCatalystSeamError(ValueError):
    """Malformed Massive news result, catalyst result, or target identity."""


def load_binding():
    return json.loads(BINDING_PATH.read_text(encoding="utf-8"))


def _require_exact_dict(value, *, name):
    if type(value) is not dict:
        raise MassiveNewsCatalystSeamError(f"{name} must be an exact dict: {type(value).__name__}")
    return value


def _require_exact_list(value, *, name):
    if type(value) is not list:
        raise MassiveNewsCatalystSeamError(f"{name} must be an exact list: {type(value).__name__}")
    return value


def _require_exact_str(value, *, name):
    if type(value) is not str:
        raise MassiveNewsCatalystSeamError(f"{name} must be exact str: {type(value).__name__}")
    return value


def _source_date_for_catalyst_as_of(as_of):
    _require_exact_str(as_of, name="as_of")
    try:
        dt = datetime.strptime(as_of, "%Y%m%d")
    except ValueError as exc:
        raise MassiveNewsCatalystSeamError("as_of must be real YYYYMMDD") from exc
    return dt.strftime("%Y-%m-%d")


def _valid_rfc3339(value):
    if type(value) is not str or "T" not in value:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _valid_lineage_ref(value, *, source_as_of):
    if type(value) is not str or not value.isascii():
        return False
    prefix, sep, record_id = value.rpartition("#")
    if sep != "#" or not record_id or any(ch.isspace() for ch in record_id):
        return False
    if ":" in record_id or "#" in record_id:
        return False
    return prefix == f"{MASSIVE_PROVIDER_ID}:{MASSIVE_NEWS_ENDPOINT}:{source_as_of}"


def _key_set(value, *, name):
    _require_exact_dict(value, name=name)
    out = set()
    for key in value:
        out.add(_require_exact_str(key, name=f"{name} key"))
    return out


def _canonical_ticker(raw, *, where):
    _require_exact_str(raw, name=f"{where} ticker")
    ticker = canonical_us_ticker(raw)
    if ticker is None:
        raise MassiveNewsCatalystSeamError(f"{where} ticker must be a canonicalizable US ticker")
    return ticker


def _canonical_targets(target_tickers):
    if type(target_tickers) is not list and type(target_tickers) is not tuple:
        raise MassiveNewsCatalystSeamError(
            f"target_tickers must be exact list/tuple: {type(target_tickers).__name__}"
        )
    out = []
    seen = set()
    for raw in target_tickers:
        ticker = _canonical_ticker(raw, where="target")
        if ticker in seen:
            raise MassiveNewsCatalystSeamError(f"target_tickers contains duplicate canonical ticker: {ticker}")
        seen.add(ticker)
        out.append(ticker)
    return out


def _non_negative_int(value, *, name):
    if type(value) is not int or value < 0:
        raise MassiveNewsCatalystSeamError(f"{name} must be an exact non-negative int")
    return value


def _signed_int(value, *, name):
    if type(value) is not int:
        raise MassiveNewsCatalystSeamError(f"{name} must be an exact int")
    return value


def _validate_summary(raw, *, ticker):
    _require_exact_dict(raw, name=f"signals[{ticker}].{SUMMARY_KEY}")
    if _key_set(raw, name=f"signals[{ticker}].{SUMMARY_KEY}") != SUMMARY_FIELD_SET:
        raise MassiveNewsCatalystSeamError("news_recent summary keys drifted from Massive news contract")
    news_count = _non_negative_int(raw["news_count"], name=f"signals[{ticker}].news_count")
    if news_count <= 0:
        raise MassiveNewsCatalystSeamError("signals row must represent at least one in-window news item")
    distinct_publishers = _non_negative_int(raw["distinct_publishers"], name=f"signals[{ticker}].distinct_publishers")
    positive = _non_negative_int(raw["positive"], name=f"signals[{ticker}].positive")
    negative = _non_negative_int(raw["negative"], name=f"signals[{ticker}].negative")
    neutral = _non_negative_int(raw["neutral"], name=f"signals[{ticker}].neutral")
    unknown = _non_negative_int(raw["unknown"], name=f"signals[{ticker}].unknown")
    net = _signed_int(raw["net_sentiment"], name=f"signals[{ticker}].net_sentiment")
    window_days = _non_negative_int(raw["window_days"], name=f"signals[{ticker}].window_days")
    if window_days != _RECENCY_WINDOW_DAYS:
        raise MassiveNewsCatalystSeamError("news_recent window_days drifted from Massive news binding")
    if positive + negative + neutral + unknown != news_count:
        raise MassiveNewsCatalystSeamError("news_recent tally counts must sum to news_count")
    if net != positive - negative:
        raise MassiveNewsCatalystSeamError("news_recent tally net_sentiment must equal positive - negative")
    if distinct_publishers == 0 or distinct_publishers > news_count:
        raise MassiveNewsCatalystSeamError("news_recent distinct_publishers must be within 1..news_count")
    return {
        "news_count": news_count,
        "distinct_publishers": distinct_publishers,
        "positive": positive,
        "negative": negative,
        "neutral": neutral,
        "unknown": unknown,
        "net_sentiment": net,
        "window_days": window_days,
    }


def _validate_signals(raw_signals):
    _require_exact_dict(raw_signals, name="news_events.signals")
    signals = {}
    for raw_ticker, raw_row in raw_signals.items():
        ticker = _canonical_ticker(raw_ticker, where="signals")
        if ticker in signals:
            raise MassiveNewsCatalystSeamError(f"signals contains duplicate canonical ticker: {ticker}")
        _require_exact_dict(raw_row, name=f"signals[{ticker}]")
        if _key_set(raw_row, name=f"signals[{ticker}]") != SIGNAL_ROW_KEYS:
            raise MassiveNewsCatalystSeamError("signals row keys drifted from Massive news source contract")
        signals[ticker] = _validate_summary(raw_row[SUMMARY_KEY], ticker=ticker)
    return signals


def _parse_record_date_yyyymmdd(ts, *, ticker):
    dt = _parse_rfc3339_instant(ts, name=f"records[{ticker}].published_utc")
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    except ImportError as exc:
        raise MassiveNewsCatalystSeamError("zoneinfo unavailable for news record date normalization") from exc
    try:
        et = dt.astimezone(ZoneInfo("America/New_York"))
    except (ZoneInfoNotFoundError, OverflowError, OSError) as exc:
        raise MassiveNewsCatalystSeamError("cannot normalize news record date to America/New_York") from exc
    return et.strftime("%Y%m%d")


def _parse_rfc3339_instant(ts, *, name):
    _require_exact_str(ts, name=name)
    try:
        dt = datetime.fromisoformat(ts[:-1] + "+00:00" if ts.endswith("Z") else ts)
    except ValueError as exc:
        raise MassiveNewsCatalystSeamError(f"{name} must be RFC3339") from exc
    if dt.tzinfo is None:
        raise MassiveNewsCatalystSeamError(f"{name} must be tz-aware")
    return dt


def _validate_records(raw_records, signals, provenance):
    _require_exact_dict(raw_records, name="news_events.records")
    records = {}
    for raw_ticker, raw_rows in raw_records.items():
        ticker = _canonical_ticker(raw_ticker, where="records")
        if ticker in records:
            raise MassiveNewsCatalystSeamError(f"records contains duplicate canonical ticker: {ticker}")
        rows = _require_exact_list(raw_rows, name=f"records[{ticker}]")
        if not rows:
            raise MassiveNewsCatalystSeamError("records row must be non-empty for emitted news signal")
        latest_date = None
        seen_ids = set()
        sentiments = {"positive": 0, "negative": 0, "neutral": 0, "unknown": 0}
        publishers = set()
        source_row = provenance[ticker]
        observed_at = _parse_rfc3339_instant(source_row["observed_at"], name=f"provenance[{ticker}].observed_at")
        source_date = datetime.strptime(source_row["source_as_of"], "%Y-%m-%d").date()
        last_sort_key = None
        for raw_row in rows:
            _require_exact_dict(raw_row, name=f"records[{ticker}] row")
            if _key_set(raw_row, name=f"records[{ticker}] row") != RECORD_KEYS:
                raise MassiveNewsCatalystSeamError("records row keys drifted from Massive news source contract")
            record_id = _require_exact_str(raw_row["id"], name=f"records[{ticker}].id")
            if not record_id:
                raise MassiveNewsCatalystSeamError("records id must be non-empty")
            if record_id in seen_ids:
                raise MassiveNewsCatalystSeamError("records contains duplicate source-row id")
            seen_ids.add(record_id)
            if not _require_exact_str(raw_row["publisher_name"], name=f"records[{ticker}].publisher_name").strip():
                raise MassiveNewsCatalystSeamError("records publisher_name must be non-empty")
            if not _require_exact_str(raw_row["title"], name=f"records[{ticker}].title"):
                raise MassiveNewsCatalystSeamError("records title must be non-empty")
            if raw_row["article_url"] is not None:
                _require_exact_str(raw_row["article_url"], name=f"records[{ticker}].article_url")
            sentiment = _require_exact_str(raw_row["sentiment"], name=f"records[{ticker}].sentiment")
            if sentiment not in {"positive", "negative", "neutral", "unknown"}:
                raise MassiveNewsCatalystSeamError("records sentiment drifted from Massive news source contract")
            if raw_row["sentiment_reasoning"] is not None:
                _require_exact_str(raw_row["sentiment_reasoning"], name=f"records[{ticker}].sentiment_reasoning")
            published_at = _parse_rfc3339_instant(raw_row["published_utc"], name=f"records[{ticker}].published_utc")
            if published_at > observed_at:
                raise MassiveNewsCatalystSeamError("records article was published after source observation")
            date_key = _parse_record_date_yyyymmdd(raw_row["published_utc"], ticker=ticker)
            if (source_date - datetime.strptime(date_key, "%Y%m%d").date()).days > _RECENCY_WINDOW_DAYS:
                raise MassiveNewsCatalystSeamError("records article is outside the source recency window")
            sort_key = (raw_row["published_utc"], record_id)
            if last_sort_key is not None and sort_key < last_sort_key:
                raise MassiveNewsCatalystSeamError("records must stay in canonical published-time order")
            last_sort_key = sort_key
            latest_date = date_key if latest_date is None or date_key > latest_date else latest_date
            sentiments[sentiment] += 1
            publishers.add(raw_row["publisher_name"].casefold())
        expected_summary = {
            "news_count": len(rows),
            "distinct_publishers": len(publishers),
            **sentiments,
            "net_sentiment": sentiments["positive"] - sentiments["negative"],
            "window_days": _RECENCY_WINDOW_DAYS,
        }
        if signals[ticker] != expected_summary:
            raise MassiveNewsCatalystSeamError("news_recent summary must be bound to emitted records")
        counts = {key: source_row[key] for key in PROVENANCE_COUNT_KEYS}
        if counts["total_record_count"] != len(rows) + counts["out_of_window_count"] + counts["future_excluded_count"]:
            raise MassiveNewsCatalystSeamError("provenance counts must reconcile to emitted records")
        records[ticker] = latest_date
    if set(records) != set(signals):
        raise MassiveNewsCatalystSeamError("records identities must exactly equal signal identities")
    return records


def _validate_excluded(raw_excluded):
    _require_exact_dict(raw_excluded, name="news_events.excluded")
    excluded = {}
    for raw_ticker, raw_reason in raw_excluded.items():
        ticker = _canonical_ticker(raw_ticker, where="excluded")
        if ticker in excluded:
            raise MassiveNewsCatalystSeamError(f"excluded contains duplicate canonical ticker: {ticker}")
        reason = _require_exact_str(raw_reason, name=f"excluded[{ticker}]")
        if not reason.strip():
            raise MassiveNewsCatalystSeamError("excluded reason must be non-empty")
        excluded[ticker] = reason
    return excluded


def _validate_checked(raw_checked):
    _require_exact_dict(raw_checked, name="news_events.checked")
    checked = {}
    for raw_ticker, raw_row in raw_checked.items():
        ticker = _canonical_ticker(raw_ticker, where="checked")
        if ticker in checked:
            raise MassiveNewsCatalystSeamError(f"checked contains duplicate canonical ticker: {ticker}")
        _require_exact_dict(raw_row, name=f"checked[{ticker}]")
        if _key_set(raw_row, name=f"checked[{ticker}]") != CHECKED_ROW_KEYS:
            raise MassiveNewsCatalystSeamError("checked row keys drifted from Massive news source contract")
        if raw_row["disposition"] != _CHECKED_EMPTY_DISPOSITION:
            raise MassiveNewsCatalystSeamError("checked disposition drifted from Massive news source contract")
        if raw_row["coverage_status"] != "full" or raw_row["parser_status"] != "ok":
            raise MassiveNewsCatalystSeamError("checked row must be full/ok")
        for field in ("total_record_count", "out_of_window_count", "future_excluded_count"):
            _non_negative_int(raw_row[field], name=f"checked[{ticker}].{field}")
        checked[ticker] = dict(raw_row)
    return checked


def _validate_provenance(raw_provenance, signal_tickers, checked_tickers, *, expected_source_as_of):
    _require_exact_dict(raw_provenance, name="news_events.provenance")
    provenance = {}
    for raw_ticker, raw_row in raw_provenance.items():
        ticker = _canonical_ticker(raw_ticker, where="provenance")
        if ticker in provenance:
            raise MassiveNewsCatalystSeamError(f"provenance contains duplicate canonical ticker: {ticker}")
        _require_exact_dict(raw_row, name=f"provenance[{ticker}]")
        if _key_set(raw_row, name=f"provenance[{ticker}]") != PROVENANCE_ROW_KEYS:
            raise MassiveNewsCatalystSeamError("provenance row keys drifted from Massive news contract")
        provider = _require_exact_str(raw_row.get("provider_id"), name=f"provenance[{ticker}].provider_id")
        endpoint = _require_exact_str(
            raw_row.get("endpoint_or_filing_type"),
            name=f"provenance[{ticker}].endpoint_or_filing_type",
        )
        if provider != MASSIVE_PROVIDER_ID or endpoint != MASSIVE_NEWS_ENDPOINT:
            raise MassiveNewsCatalystSeamError("provenance provider/endpoint drifted from Massive news contract")
        source_as_of = _require_exact_str(raw_row.get("source_as_of"), name=f"provenance[{ticker}].source_as_of")
        if source_as_of != expected_source_as_of:
            raise MassiveNewsCatalystSeamError("provenance source_as_of must equal catalyst as_of date")
        observed_at = raw_row.get("observed_at")
        if not _valid_rfc3339(observed_at):
            raise MassiveNewsCatalystSeamError("provenance observed_at must be tz-aware RFC3339")
        observed_et = _parse_rfc3339_instant(observed_at, name=f"provenance[{ticker}].observed_at")
        try:
            from zoneinfo import ZoneInfo

            observed_et = observed_et.astimezone(ZoneInfo("America/New_York"))
        except Exception as exc:
            raise MassiveNewsCatalystSeamError("cannot normalize provenance observed_at to America/New_York") from exc
        source_date = datetime.strptime(source_as_of, "%Y-%m-%d").date()
        if observed_et.date() > source_date or observed_et >= datetime(
            source_date.year, source_date.month, source_date.day, 9, 30, tzinfo=observed_et.tzinfo
        ):
            raise MassiveNewsCatalystSeamError("provenance observed_at violates the pre-open PIT cutoff")
        coverage = _require_exact_str(raw_row.get("coverage_status"), name=f"provenance[{ticker}].coverage_status")
        parser = _require_exact_str(raw_row.get("parser_status"), name=f"provenance[{ticker}].parser_status")
        if coverage != MASSIVE_NEWS_COVERAGE_EMIT or parser != MASSIVE_NEWS_PARSER_EMIT:
            raise MassiveNewsCatalystSeamError("provenance coverage/parser is not score-ready full/ok")
        if not _valid_lineage_ref(raw_row.get("lineage_ref"), source_as_of=source_as_of):
            raise MassiveNewsCatalystSeamError("provenance lineage_ref drifted from source-bound format")
        for key in PROVENANCE_COUNT_KEYS:
            _non_negative_int(raw_row[key], name=f"provenance[{ticker}].{key}")
        provenance[ticker] = raw_row
    expected = set(signal_tickers) | set(checked_tickers)
    if set(provenance) != expected:
        raise MassiveNewsCatalystSeamError("provenance identities must exactly equal signal+checked identities")
    return provenance


def _validate_news_events(news_events, *, expected_source_as_of):
    _require_exact_dict(news_events, name="news_events")
    if _key_set(news_events, name="news_events") != SOURCE_RESULT_KEYS:
        raise MassiveNewsCatalystSeamError("news_events keys drifted from the Massive news source contract")
    signals = _validate_signals(news_events["signals"])
    excluded = _validate_excluded(news_events["excluded"])
    checked = _validate_checked(news_events["checked"])
    provenance = _validate_provenance(
        news_events["provenance"],
        signals,
        checked,
        expected_source_as_of=expected_source_as_of,
    )
    records = _validate_records(news_events["records"], signals, provenance)
    overlap = (set(signals) & set(excluded)) | (set(signals) & set(checked)) | (set(checked) & set(excluded))
    if overlap:
        raise MassiveNewsCatalystSeamError("news_events signal/checked/excluded identities must be disjoint")
    for ticker, row in checked.items():
        if any(row[key] != provenance[ticker][key] for key in PROVENANCE_COUNT_KEYS):
            raise MassiveNewsCatalystSeamError("checked counts must reconcile to provenance")
        if row["total_record_count"] != row["out_of_window_count"] + row["future_excluded_count"]:
            raise MassiveNewsCatalystSeamError("checked counts must have no emitted records")
    return signals, records, checked, excluded


def validate_resolved_news_events(*, news_events, as_of):
    """Validate the complete resolved Massive-news envelope before any consumer uses its tally."""
    expected_source_as_of = _source_date_for_catalyst_as_of(as_of)
    return _validate_news_events(news_events, expected_source_as_of=expected_source_as_of)


def _finite_block_value(value, *, name):
    if type(value) is not int and type(value) is not float:
        raise MassiveNewsCatalystSeamError(f"{name} must be exact int/float in [0,100]")
    try:
        out = float(value)   # an over-large int → typed error (mirrors sibling seam_catalyst), not a bare OverflowError
    except OverflowError:
        raise MassiveNewsCatalystSeamError(f"{name} must be finite in [0,100]")
    if not math.isfinite(out) or out < _BLOCK_MIN or out > _BLOCK_MAX:
        raise MassiveNewsCatalystSeamError(f"{name} must be finite in [0,100]")
    return out


def _validate_catalyst_result(result, *, as_of):
    _require_exact_dict(result, name="catalyst_block result")
    if result.get("as_of") != as_of:
        raise MassiveNewsCatalystSeamError("catalyst_block result as_of drifted from input as_of")
    raw_block = _require_exact_dict(result.get("catalyst_block"), name="catalyst_block")
    raw_neutral = _require_exact_list(result.get("neutral_fallback"), name="neutral_fallback")
    block = {}
    for raw_ticker, raw_score in raw_block.items():
        ticker = _canonical_ticker(raw_ticker, where="catalyst_block")
        if ticker in block:
            raise MassiveNewsCatalystSeamError(f"catalyst_block contains duplicate canonical ticker: {ticker}")
        block[ticker] = _finite_block_value(raw_score, name=f"catalyst_block[{ticker}]")
    neutral = set()
    for raw_ticker in raw_neutral:
        ticker = _canonical_ticker(raw_ticker, where="neutral_fallback")
        if ticker in neutral:
            raise MassiveNewsCatalystSeamError(f"neutral_fallback contains duplicate canonical ticker: {ticker}")
        neutral.add(ticker)
    if not neutral <= set(block):
        raise MassiveNewsCatalystSeamError("neutral_fallback must be a subset of catalyst_block identities")
    return block, neutral


def _news_tally_to_catalyst_signals(signals, records):
    out = {}
    for ticker, summary in signals.items():
        score = float(summary["net_sentiment"]) / float(summary["news_count"])
        score = max(-1.0, min(1.0, score))
        out[ticker] = {
            CATALYST_SIGNAL_KEY: score,
            CATALYST_DATE_KEY: records[ticker],
        }
    return out


def project_massive_news_catalyst(*, news_events, governance, as_of, target_tickers):
    """Project resolved Massive news facts into the per-target catalyst block.

    The transform is deterministic and bounded: source net_sentiment/news_count
    becomes a [-1, 1] advisory score, then the existing catalyst governance cap
    controls its maximum point impact. Checked-empty, excluded, and missing
    targets are neutral-omitted for the score composer.
    """
    targets = _canonical_targets(target_tickers)
    signals, records, checked, excluded = validate_resolved_news_events(news_events=news_events, as_of=as_of)
    catalyst_inputs = _news_tally_to_catalyst_signals(signals, records)
    raw_result = catalyst_block(catalyst_inputs, governance, as_of=as_of)
    block, neutral = _validate_catalyst_result(raw_result, as_of=as_of)

    catalyst_by_ticker = {}
    neutral_fill = []
    coverage = {}
    for ticker in targets:
        if ticker in block and ticker not in neutral:
            catalyst_by_ticker[ticker] = block[ticker]
            coverage[ticker] = DISPOSITION_SCORED_REALIZED
        else:
            neutral_fill.append(ticker)
            if ticker in block and ticker in neutral:
                coverage[ticker] = DISPOSITION_NEUTRAL_NO_REALIZED
            elif ticker in checked:
                coverage[ticker] = DISPOSITION_NEUTRAL_NO_REALIZED
            elif ticker in excluded:
                coverage[ticker] = DISPOSITION_NEUTRAL_SOURCE_EXCLUDED
            else:
                coverage[ticker] = DISPOSITION_NEUTRAL_MISSING_SOURCE
    return {
        "catalyst_block_by_ticker": catalyst_by_ticker,
        "neutral_fill_tickers": neutral_fill,
        "coverage": coverage,
        "target_count": len(targets),
        "scored_count": len(catalyst_by_ticker),
    }
