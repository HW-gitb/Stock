# -*- coding: utf-8 -*-
"""Authorized market-wide Massive coverage fetch for A1 zero-event certificates.

The runner is deliberately narrow: two endpoint families, one batched union date window, at most
two pages per family, no retry and no per-ticker calls.  Raw payloads and ticker-bearing coverage
stay private.  The returned stage summary is counts/status/digests only.
"""
from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import re
import urllib.parse
from pathlib import Path
from typing import Any

from engine.us_short_forward_policy_corporate_action_evidence import (
    FIRST_ELIGIBLE_DECISION_DATE,
    ForwardPolicyCorporateActionEvidenceError,
    build_adjustment_evidence,
    canonical_sha256,
    derive_mature_h20_window,
    validate_coverage_packet,
)
from engine.us_short_forward_policy_source_capture import validate_forward_policy_source_capture
from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path
from runners import us_egs_sample_validation as sample_validation


ROOT = Path(__file__).resolve().parent.parent
AUTHORIZATION_REF = "user_chat_20260718_us_short_a1_zero_event_certificate"
SUMMARY_REL_ROOT = Path("research") / "results" / "us_short_forward_policy_corporate_action"
_CAPABILITY_ISSUER = object()
_ENDPOINTS = {
    "splits": ("/stocks/v1/splits", "execution_date"),
    "dividends": ("/stocks/v1/dividends", "ex_dividend_date"),
}
MAX_PAGES_PER_FAMILY = 2
MAX_HTTP_ATTEMPTS = 4
_TICKER = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
_EVENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class ForwardPolicyCorporateActionFetchError(RuntimeError):
    """The authorized comparison-only coverage fetch cannot safely complete."""


@dataclasses.dataclass(frozen=True)
class _WeeklyCapstoneCapability:
    issuer: object
    decision_date: str
    generated_at: str
    sample_root: Path
    private_root: Path


def _issue_weekly_capstone_capability(
    *, decision_date: str, generated_at: str, sample_root: Path, private_root: Path,
) -> _WeeklyCapstoneCapability:
    """Minted only by the real default weekly capstone immediately before this stage."""
    return _WeeklyCapstoneCapability(
        issuer=_CAPABILITY_ISSUER,
        decision_date=decision_date,
        generated_at=generated_at,
        sample_root=Path(sample_root).resolve(),
        private_root=Path(private_root).resolve(),
    )


def _require_capability(
    capability: object, *, decision_date: str, generated_at: str, sample_root: Path, private_root: Path,
) -> None:
    expected = (
        isinstance(capability, _WeeklyCapstoneCapability)
        and capability.issuer is _CAPABILITY_ISSUER
        and capability.decision_date == decision_date
        and capability.generated_at == generated_at
        and capability.sample_root == Path(sample_root).resolve()
        and capability.private_root == Path(private_root).resolve()
    )
    if not expected:
        raise ForwardPolicyCorporateActionFetchError("genuine weekly-capstone corporate-action capability is required")


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ForwardPolicyCorporateActionFetchError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ForwardPolicyCorporateActionFetchError(f"{label} must be an object")
    return value


def _private_path(path: Path) -> None:
    if not path.is_absolute():
        raise ForwardPolicyCorporateActionFetchError("private output path must be absolute")
    try:
        reject_nonprivate_output_path(path)
    except PrivatePathError as exc:
        raise ForwardPolicyCorporateActionFetchError(str(exc)) from exc


def _write_once(path: Path, payload: dict[str, Any], label: str) -> bool:
    _private_path(path)
    if path.exists():
        if _load_json(path, label) != payload:
            raise ForwardPolicyCorporateActionFetchError(f"refusing to overwrite drifted {label}")
        return False
    sample_validation.write_json_atomic(payload, path)
    return True


def _write_tracked_summary(
    *, summary: dict[str, Any], summary_path: Path, sample_root: Path, decision_date: str,
    sensitive_values: tuple[str, ...] = (),
) -> None:
    expected = (sample_root / SUMMARY_REL_ROOT / f"coverage_summary_{decision_date}.json").resolve()
    if Path(summary_path).resolve() != expected:
        raise ForwardPolicyCorporateActionFetchError("tracked summary must keep its canonical de-identified path")
    serialized = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    lowered = serialized.lower()
    forbidden = ("apikey=", "api.massive.com", "http://", "https://", '"ticker"', '"payload"')
    if any(fragment in lowered for fragment in forbidden) or any(value and value in serialized for value in sensitive_values):
        raise ForwardPolicyCorporateActionFetchError("de-identified tracked summary leaked forbidden provider data")
    path = Path(summary_path)
    sample_validation.write_json_atomic(summary, path)


def _iso_date(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        return datetime.date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _first_url(*, family: str, date_from: str, date_to: str, api_key: str) -> str:
    endpoint, date_field = _ENDPOINTS[family]
    query = urllib.parse.urlencode({
        f"{date_field}.gte": date_from,
        f"{date_field}.lte": date_to,
        "sort": date_field,
        "order": "asc",
        "limit": "5000",
        "apiKey": api_key,
    })
    return f"https://api.massive.com{endpoint}?{query}"


def _continuation_url(value: object, *, family: str, api_key: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ForwardPolicyCorporateActionFetchError("unsafe continuation")
    parsed = urllib.parse.urlsplit(value)
    endpoint, _ = _ENDPOINTS[family]
    try:
        port = parsed.port
    except ValueError:  # malformed / out-of-range port in a hostile continuation URL
        raise ForwardPolicyCorporateActionFetchError("unsafe continuation")
    if parsed.scheme != "https" or parsed.hostname != "api.massive.com" or parsed.path != endpoint \
            or parsed.username is not None or parsed.password is not None or port not in (None, 443):
        raise ForwardPolicyCorporateActionFetchError("unsafe continuation")
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if any(key.lower() in {"ticker", "tickers"} for key, _ in query):
        raise ForwardPolicyCorporateActionFetchError("unsafe continuation")
    query = [(key, val) for key, val in query if key.lower() != "apikey"]
    query.append(("apiKey", api_key))
    return urllib.parse.urlunsplit(("https", "api.massive.com", endpoint, urllib.parse.urlencode(query), ""))


def _normalized_events(
    rows: object, *, family: str, date_from: str, date_to: str, seen_provider_ids: set[str],
) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        raise ForwardPolicyCorporateActionFetchError("malformed payload")
    _, date_field = _ENDPOINTS[family]
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ForwardPolicyCorporateActionFetchError("malformed payload")
        provider_id, ticker, event_date = row.get("id"), row.get("ticker"), row.get(date_field)
        if not isinstance(provider_id, str) or not provider_id or provider_id in seen_provider_ids \
                or not isinstance(ticker, str) or _TICKER.fullmatch(ticker) is None \
                or not _iso_date(event_date) or not date_from <= event_date <= date_to:
            raise ForwardPolicyCorporateActionFetchError("malformed payload")
        seen_provider_ids.add(provider_id)
        event_id = f"massive_{family}_{hashlib.sha256(provider_id.encode('utf-8')).hexdigest()[:32]}"
        if _EVENT_ID.fullmatch(event_id) is None:  # pragma: no cover - construction invariant
            raise ForwardPolicyCorporateActionFetchError("malformed payload")
        out.append({"event_id": event_id, "ticker": ticker, "event_date": event_date})
    return out


def _redact_secret(value: Any, secret: str) -> Any:
    if isinstance(value, dict):
        return {key: _redact_secret(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_secret(item, secret) for item in value]
    if isinstance(value, str) and secret:
        return value.replace(secret, "[REDACTED]")
    return value


def _fetch_family(
    *, family: str, date_from: str, date_to: str, api_key: str,
    raw_root: Path, client: sample_validation.JsonHttpClient,
) -> dict[str, Any]:
    events: list[dict[str, str]] = []
    raw_digests: list[str] = []
    seen_provider_ids: set[str] = set()
    status, reason, exhausted = "complete", None, False
    url = _first_url(family=family, date_from=date_from, date_to=date_to, api_key=api_key)
    for page_number in range(1, MAX_PAGES_PER_FAMILY + 1):
        payload, http_status, ok, error_type = client.get_json(
            url, headers={"User-Agent": "StockSystem/0.1 us-short-forward-policy-zero-event"}
        )
        wrapper = {
            "provider_id": "massive", "endpoint_family": family, "page_number": page_number,
            "http_status": http_status, "ok": bool(ok), "error_type": error_type,
            "payload": _redact_secret(payload, api_key),
        }
        raw_path = raw_root / "massive" / f"{family}_page_{page_number}.json"
        try:
            page_digest = canonical_sha256(wrapper)
        except ForwardPolicyCorporateActionEvidenceError:  # non-finite (NaN/Infinity) payload — never persist the poisoning page
            status, reason = "incomplete", "malformed_payload"
            break
        _write_once(raw_path, wrapper, "raw corporate-action page")
        raw_digests.append(page_digest)
        if not ok:
            status, reason = "incomplete", "http_error"
            break
        if not isinstance(payload, dict):
            status, reason = "incomplete", "malformed_payload"
            break
        try:
            events.extend(_normalized_events(
                payload.get("results"), family=family, date_from=date_from, date_to=date_to,
                seen_provider_ids=seen_provider_ids,
            ))
            next_url = _continuation_url(payload.get("next_url"), family=family, api_key=api_key)
        except ForwardPolicyCorporateActionFetchError as exc:
            status = "incomplete"
            reason = "unsafe_continuation" if "continuation" in str(exc) else "malformed_payload"
            break
        if next_url is None:
            exhausted = True
            break
        if page_number == MAX_PAGES_PER_FAMILY:
            status, reason = "incomplete", "pagination_limit_exceeded"
            break
        url = next_url
    return {
        "status": status if exhausted else "incomplete",
        "date_field": _ENDPOINTS[family][1],
        "pages_fetched": len(raw_digests),
        "pagination_exhausted": exhausted,
        "result_count": len(events),
        "result_sha256": canonical_sha256(events),
        "raw_page_sha256": raw_digests,
        "events": events,
        "failure_reason": None if exhausted and status == "complete" else (reason or "http_error"),
    }


def _validate_raw_page_bindings(coverage: dict[str, Any], raw_root: Path) -> None:
    for family_name, family in coverage["families"].items():
        for page_number, expected_sha in enumerate(family["raw_page_sha256"], start=1):
            path = raw_root / "massive" / f"{family_name}_page_{page_number}.json"
            if canonical_sha256(_load_json(path, "raw corporate-action page")) != expected_sha:
                raise ForwardPolicyCorporateActionFetchError("raw corporate-action page digest drifted")


def _capture_bindings(windows: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{key: window[key] for key in (
        "decision_date", "common_selection_pool_sha256", "window_start", "h20_session_date"
    )} for window in windows]


def run_fetch(
    *, confirm_user_authorization: bool, capability: object, decision_date: str, generated_at: str,
    maturity_ohlcv_path: Path, sample_root: Path, private_root: Path,
    summary_path: Path | None = None,
    client: sample_validation.JsonHttpClient | None = None,
) -> dict[str, Any]:
    """Fetch one union window and emit immutable sidecars for newly mature eligible captures."""
    if confirm_user_authorization is not True:
        raise ForwardPolicyCorporateActionFetchError("explicit per-execution authorization is required")
    sample_root, private_root = Path(sample_root).resolve(), Path(private_root).resolve()
    summary_path = Path(summary_path or (
        sample_root / SUMMARY_REL_ROOT / f"coverage_summary_{decision_date}.json"
    ))
    _require_capability(
        capability, decision_date=decision_date, generated_at=generated_at,
        sample_root=sample_root, private_root=private_root,
    )
    try:
        maturity_bytes = Path(maturity_ohlcv_path).read_bytes()
        maturity_packet = json.loads(maturity_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise ForwardPolicyCorporateActionFetchError("maturity OHLCV packet is unreadable") from exc
    maturity_sha = hashlib.sha256(maturity_bytes).hexdigest()
    all_windows: list[dict[str, Any]] = []
    for path in sorted(private_root.glob("forward_policy_source_capture_????????.json")):
        source_capture = _load_json(path, "forward-policy source capture")
        try:
            validate_forward_policy_source_capture(source_capture)
            window = derive_mature_h20_window(
                source_capture=source_capture, maturity_ohlcv_packet=maturity_packet,
                maturity_ohlcv_sha256=maturity_sha, maturity_as_of=decision_date,
            )
        except (ForwardPolicyCorporateActionEvidenceError, ValueError) as exc:
            raise ForwardPolicyCorporateActionFetchError("eligible source capture cannot derive an exact H20 window") from exc
        if window is None:
            continue
        all_windows.append(window)
    coverage_path = private_root / f"forward_policy_corporate_action_coverage_{decision_date}.json"
    raw_root = sample_root / "provider_samples" / f"us_short_forward_policy_corporate_action_{decision_date}" / "raw"
    _private_path(coverage_path)
    new_windows = [window for window in all_windows if not (
        private_root / f"forward_policy_adjustment_evidence_{window['decision_date']}.json"
    ).exists()]
    if coverage_path.exists():
        existing_coverage = _load_json(coverage_path, "corporate-action coverage packet")
        bound_decisions = {item.get("decision_date") for item in existing_coverage.get("capture_bindings", [])}
        windows = [window for window in all_windows if window["decision_date"] in bound_decisions]
        if len(windows) != len(bound_decisions) or any(
            window["decision_date"] not in bound_decisions for window in new_windows
        ):
            raise ForwardPolicyCorporateActionFetchError("existing coverage packet cannot be expanded or backfilled")
    else:
        windows = new_windows
    if not windows:
        summary = {
            "status": "no_eligible_mature_capture", "eligible_capture_count": 0,
            "coverage_packet_sha256": None, "sidecars_written": 0, "http_attempt_count": 0,
            "family_status": {"splits": "not_run", "dividends": "not_run"},
        }
        _write_tracked_summary(
            summary=summary, summary_path=summary_path, sample_root=sample_root, decision_date=decision_date,
        )
        return summary
    bindings = _capture_bindings(windows)
    date_from = min(item["window_start"] for item in windows)
    date_to = max(item["h20_session_date"] for item in windows)
    sensitive_values: tuple[str, ...] = ()
    if coverage_path.exists():
        coverage = _load_json(coverage_path, "corporate-action coverage packet")
        try:
            validate_coverage_packet(coverage)
        except ForwardPolicyCorporateActionEvidenceError as exc:
            raise ForwardPolicyCorporateActionFetchError("existing coverage packet is invalid") from exc
        expected = (
            coverage["maturity_as_of"] == decision_date
            and coverage["maturity_ohlcv_sha256"] == maturity_sha
            and coverage["query_window"] == {"from": date_from, "to": date_to}
            and coverage["capture_bindings"] == bindings
            and all(item["status"] == "complete" for item in coverage["families"].values())
        )
        if not expected:
            raise ForwardPolicyCorporateActionFetchError("existing coverage packet cannot be reused for this exact run")
        _validate_raw_page_bindings(coverage, raw_root)
        http_attempts = 0
    else:
        try:
            api_key = sample_validation.read_required_env("MASSIVE_API_KEY").value
        except RuntimeError as exc:
            raise ForwardPolicyCorporateActionFetchError("MASSIVE_API_KEY is required but was not printed") from exc
        sensitive_values = (api_key,)
        _private_path(raw_root / "massive" / "probe.json")
        http_client = client or sample_validation.JsonHttpClient()
        families = {
            family: _fetch_family(
                family=family, date_from=date_from, date_to=date_to, api_key=api_key,
                raw_root=raw_root, client=http_client,
            ) for family in ("splits", "dividends")
        }
        coverage = {
            "schema_name": "us_short_forward_policy_corporate_action_coverage",
            "schema_version": "1.0.0",
            "authorization_ref": AUTHORIZATION_REF,
            "generated_at": generated_at,
            "maturity_as_of": decision_date,
            "maturity_ohlcv_sha256": maturity_sha,
            "query_window": {"from": date_from, "to": date_to},
            "capture_bindings": bindings,
            "families": families,
            "boundary": {
                "track": "comparison_non_production", "provider_id": "massive", "plan": "stocks_basic_free",
                "spend_usd": 0, "market_wide_queries_only": True,
                "event_week_reconciliation_performed": False, "ship_gate_or_production_authorized": False,
                "broker_or_order_automation_allowed": False,
            },
        }
        try:
            validate_coverage_packet(coverage)
        except ForwardPolicyCorporateActionEvidenceError as exc:
            raise ForwardPolicyCorporateActionFetchError("new coverage packet is invalid") from exc
        _write_once(coverage_path, coverage, "corporate-action coverage packet")
        http_attempts = sum(item["pages_fetched"] for item in families.values())
        if http_attempts > MAX_HTTP_ATTEMPTS:  # pragma: no cover - loop bound invariant
            raise ForwardPolicyCorporateActionFetchError("corporate-action HTTP attempt budget exceeded")
    coverage_sha = canonical_sha256(coverage)
    written = 0
    for window in windows:
        try:
            evidence = build_adjustment_evidence(
                window=window, coverage_packet=coverage, coverage_packet_sha256=coverage_sha,
            )
        except ForwardPolicyCorporateActionEvidenceError as exc:
            raise ForwardPolicyCorporateActionFetchError("zero-event evidence emission failed") from exc
        written += int(_write_once(
            private_root / f"forward_policy_adjustment_evidence_{window['decision_date']}.json",
            evidence, "forward-policy adjustment sidecar",
        ))
    family_status = {name: value["status"] for name, value in coverage["families"].items()}
    eventful_windows = sum(any(
        event["ticker"] in set(window["common_selection_pool"])
        and window["window_start"] <= event["event_date"] <= window["h20_session_date"]
        for family in coverage["families"].values() for event in family["events"]
    ) for window in windows)
    summary = {
        "status": "complete" if all(value == "complete" for value in family_status.values()) else "incomplete_no_count",
        "eligible_capture_count": len(windows),
        "coverage_packet_sha256": coverage_sha,
        "sidecars_written": written,
        "http_attempt_count": http_attempts,
        "eventful_window_count": eventful_windows,
        "family_status": family_status,
        "family_result_sha256": {name: value["result_sha256"] for name, value in coverage["families"].items()},
    }
    _write_tracked_summary(
        summary=summary, summary_path=summary_path, sample_root=sample_root,
        decision_date=decision_date, sensitive_values=sensitive_values,
    )
    return summary
