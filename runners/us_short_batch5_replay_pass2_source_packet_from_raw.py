"""Offline, non-emittable replay of a bound Batch5 Pass2 raw capture.

Replay never calls a provider. It reuses an already-approved live-capture summary plus its exact raw-wrapper manifest
to exercise the same resolver/assembly code. The result is explicitly ``offline_replay``: it cannot write a
data-context, cannot satisfy a provider-fetch/research-live receipt, and retains the capture's original observation
clock instead of accepting a caller-selected one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.modules.setdefault("runners.us_short_batch5_replay_pass2_source_packet_from_raw", sys.modules[__name__])

from runners import us_egs_sample_validation as sample_validation  # noqa: E402
from runners import us_short_batch5_full_candidate_live_source_packet as live_source_packet  # noqa: E402


class ReplayError(live_source_packet.FullCandidateLiveSourcePacketError):
    """The persisted raw cannot prove a faithful, offline replay."""


_ALLOWED_FAMILIES = {
    ("sec_edgar", "company_tickers_mapping"),
    ("sec_edgar", "submissions"),
    ("financial_modeling_prep", "grades"),
    ("massive", "reference_news"),
    ("massive", "stock_splits"),
    ("massive", "dividends"),
}
_BATCH_FAMILIES = {"reference_news", "stock_splits", "dividends"}


def _query_param(url: str, name: str) -> str | None:
    values = parse_qs(urlparse(url).query).get(name)
    return values[0] if values else None


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_wrapper(
    wrapper: Any,
    *,
    wrapper_path: Path,
    source_raw_root: Path,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    if not isinstance(wrapper, dict):
        raise ReplayError("replay raw wrapper must be an object")
    required = {"provider_id", "endpoint_family", "symbol", "http_status", "ok", "error_type", "payload"}
    if not required.issubset(wrapper):
        raise ReplayError("replay raw wrapper is missing required fields")
    provider_id = wrapper["provider_id"]
    endpoint_family = wrapper["endpoint_family"]
    symbol = wrapper["symbol"]
    if type(provider_id) is not str or type(endpoint_family) is not str:
        raise ReplayError("replay raw wrapper provider/family must be exact strings")
    if (provider_id, endpoint_family) not in _ALLOWED_FAMILIES:
        raise ReplayError("replay raw wrapper contains an unapproved provider endpoint family")
    is_batch_page = endpoint_family in _BATCH_FAMILIES and "page_number" in wrapper
    if is_batch_page:
        if set(wrapper) != required | {"page_number", "query_window"}:
            raise ReplayError("replay batch-page wrapper keys drift from the captured endpoint contract")
        if provider_id != "massive" or symbol is not None:
            raise ReplayError("replay batch-page wrapper must use the market-level Massive identity")
        if type(wrapper["page_number"]) is not int or wrapper["page_number"] < 1:
            raise ReplayError("replay batch-page wrapper page_number is invalid")
        query_window = wrapper["query_window"]
        if not isinstance(query_window, dict) or any(
            not isinstance(query_window.get(field), str if field != "limit" else int)
            for field in ("date_field", "date_from", "date_to", "limit", "sort", "order")
        ):
            raise ReplayError("replay batch-page wrapper query_window is invalid")
        if query_window.get("limit", 0) < 1 or query_window.get("order") != "asc":
            raise ReplayError("replay batch-page wrapper query_window is invalid")
        canonical_path = (
            source_raw_root / "massive" / "_market"
            / f"{endpoint_family}_page_{wrapper['page_number']:04d}.json"
        ).resolve()
        key: tuple[Any, ...] = (provider_id, endpoint_family, "page", wrapper["page_number"])
    else:
        if set(wrapper) != required:
            raise ReplayError("replay raw wrapper keys drift from the captured endpoint contract")
        if endpoint_family == "company_tickers_mapping":
            if symbol is not None:
                raise ReplayError("replay SEC ticker mapping must use the market-level symbol identity")
        elif type(symbol) is not str or not symbol:
            raise ReplayError("replay per-ticker wrapper must carry an exact ticker identity")
        key = (provider_id, endpoint_family, symbol)
        canonical_path = sample_validation.raw_sample_ref(source_raw_root, provider_id, endpoint_family, symbol).resolve()
    if wrapper["http_status"] is not None and (type(wrapper["http_status"]) is not int or wrapper["http_status"] < 100):
        raise ReplayError("replay raw wrapper http_status must be an HTTP integer or null")
    if type(wrapper["ok"]) is not bool:
        raise ReplayError("replay raw wrapper ok must be an exact bool")
    if wrapper["error_type"] is not None and type(wrapper["error_type"]) is not str:
        raise ReplayError("replay raw wrapper error_type must be string or null")
    if wrapper_path.resolve() != canonical_path:
        raise ReplayError("replay raw wrapper path is not canonical for its asserted identity")
    return key, wrapper


class ReplayClient:
    """A strict, no-network client backed by one exact approved raw capture."""

    def __init__(
        self,
        source_raw_root: Path,
        *,
        expected_records: dict[tuple[Any, ...], tuple[Path, str]] | None = None,
        bound_capture: dict[str, Any] | None = None,
    ) -> None:
        self._source_raw_root = Path(source_raw_root).resolve()
        self._by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._batch_pages: dict[str, list[tuple[tuple[Any, ...], dict[str, Any]]]] = {}
        self._batch_cursors: dict[str, int] = {}
        self._expected_records = dict(expected_records) if expected_records is not None else None
        self._bound_capture = bound_capture
        self._unused: set[tuple[Any, ...]] = set()
        self._cik_to_symbol: dict[str, str] = {}
        if not self._source_raw_root.is_dir():
            raise ReplayError("replay source raw root must be an existing directory")
        for wrapper_path in self._source_raw_root.rglob("*.json"):
            if wrapper_path.name.endswith(".tmp"):
                continue
            try:
                wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ReplayError("replay source raw contains an unreadable JSON wrapper") from exc
            key, wrapper = _canonical_wrapper(
                wrapper,
                wrapper_path=wrapper_path,
                source_raw_root=self._source_raw_root,
            )
            if key in self._by_key:
                raise ReplayError("replay source raw contains duplicate endpoint identity")
            if self._expected_records is not None:
                expected = self._expected_records.get(key)
                if expected is None:
                    raise ReplayError("replay source raw endpoint does not match the bound capture manifest")
                expected_path, expected_sha256 = expected
                if wrapper_path.resolve() != expected_path.resolve() or _sha256_file(wrapper_path) != expected_sha256:
                    raise ReplayError("replay source raw wrapper bytes do not match the bound capture manifest")
            self._by_key[key] = wrapper
            self._unused.add(key)
            if len(key) == 4 and key[2] == "page":
                self._batch_pages.setdefault(key[1], []).append((key, wrapper))
            elif key[:2] == ("sec_edgar", "submissions"):
                payload = wrapper["payload"]
                cik = payload.get("cik") if isinstance(payload, dict) else None
                if type(cik) is not str or not cik.strip():
                    raise ReplayError("replay SEC submissions wrapper lacks a usable CIK")
                cik10 = cik.strip().zfill(10)
                prior = self._cik_to_symbol.get(cik10)
                if prior is not None and prior != key[2]:
                    raise ReplayError("replay SEC submissions wrappers map one CIK to multiple symbols")
                self._cik_to_symbol[cik10] = key[2]
        if not self._by_key:
            raise ReplayError("no persisted raw wrappers found under source_raw_root")
        if self._expected_records is not None and set(self._by_key) != set(self._expected_records):
            raise ReplayError("replay source raw is missing or adds endpoint identities versus the bound capture manifest")
        for family, pages in self._batch_pages.items():
            pages.sort(key=lambda item: item[0][3])
            page_numbers = [key[3] for key, _ in pages]
            if page_numbers != list(range(1, len(page_numbers) + 1)):
                raise ReplayError("replay batch-page sequence has a missing or extra page")

    def is_bound_to_capture(self, capture: dict[str, Any] | None) -> bool:
        """True only for the capture object verified by ``_load_bound_source_capture`` in this process."""
        return self._expected_records is not None and self._bound_capture is capture

    def _url_to_key(self, url: str) -> tuple[Any, ...]:
        if "company_tickers.json" in url:
            return ("sec_edgar", "company_tickers_mapping", None)
        submissions = re.search(r"/submissions/CIK(\d{10})\.json", url)
        if submissions:
            symbol = self._cik_to_symbol.get(submissions.group(1))
            return ("sec_edgar", "submissions", symbol)
        if "financialmodelingprep.com" in url:
            return ("financial_modeling_prep", "grades", _query_param(url, "symbol"))
        if "api.massive.com" in url:
            ticker = _query_param(url, "ticker")
            if "/reference/news" in url:
                family = "reference_news"
            elif "/splits" in url:
                family = "stock_splits"
            elif "/dividends" in url:
                family = "dividends"
            else:
                raise ReplayError("replay received an unknown Massive endpoint")
            if ticker is None:
                return ("batch", family)
            return ("massive", family, ticker)
        raise ReplayError("replay received an endpoint outside the bound source-capture contract")

    def get_json(self, url: str, *, headers: dict | None = None, timeout_seconds: int | None = None):
        route = self._url_to_key(url)
        if len(route) == 2 and route[0] == "batch":
            family = route[1]
            pages = self._batch_pages.get(family, [])
            cursor = self._batch_cursors.get(family, 0)
            if cursor >= len(pages):
                raise ReplayError("replay source raw is missing a required batch page")
            key, wrapper = pages[cursor]
            self._batch_cursors[family] = cursor + 1
        else:
            key = route
            wrapper = self._by_key.get(key)
        if wrapper is None:
            raise ReplayError("replay source raw is missing a required endpoint wrapper")
        self._unused.discard(key)
        return wrapper["payload"], wrapper["http_status"], wrapper["ok"], wrapper["error_type"]

    def assert_all_loaded_consumed(self) -> None:
        if self._unused:
            raise ReplayError("replay source raw has unconsumed endpoint wrappers")


def _load_bound_source_capture(
    *,
    source_summary_path: Path,
    source_raw_root: Path,
    expected_total_call_budget: int,
) -> tuple[dict[tuple[Any, ...], tuple[Path, str]], dict[str, Any], str]:
    summary_path = Path(source_summary_path).resolve()
    raw_root = Path(source_raw_root).resolve()
    if not summary_path.is_file() or not raw_root.is_dir():
        raise ReplayError("replay source summary and raw root must exist")
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError("replay source summary is not readable JSON") from exc
    if not isinstance(summary, dict):
        raise ReplayError("replay source summary must be an object")
    scope = summary.get("scope")
    clock = summary.get("decision_clock")
    storage = summary.get("storage")
    budget = summary.get("endpoint_call_budget")
    records = summary.get("endpoint_results")
    if not isinstance(scope, dict) or scope.get("network_access_performed") is not True \
            or scope.get("provider_calls_performed") is not True:
        raise ReplayError("replay source summary must attest an original provider fetch")
    if not isinstance(clock, dict):
        raise ReplayError("replay source summary lacks a decision clock")
    observed_at = clock.get("observed_at")
    source_decision_date = clock.get("expected_decision_date")
    source_as_of = clock.get("source_as_of")
    if not isinstance(observed_at, str) or not live_source_packet._valid_observed_at(observed_at) \
            or not isinstance(source_decision_date, str) or not isinstance(source_as_of, str):
        raise ReplayError("replay source summary has an invalid capture decision clock")
    try:
        if live_source_packet._date8_to_ymd(source_decision_date) != source_as_of:
            raise ReplayError("replay source summary source_as_of does not bind its decision date")
    except live_source_packet.FullCandidateLiveSourcePacketError as exc:
        raise ReplayError("replay source summary has an invalid capture decision date") from exc
    if not isinstance(storage, dict) or not isinstance(storage.get("raw_payload_root"), str):
        raise ReplayError("replay source summary lacks its raw payload root")
    try:
        recorded_raw_root = (ROOT / storage["raw_payload_root"]).resolve()
    except (TypeError, ValueError) as exc:
        raise ReplayError("replay source summary raw root is invalid") from exc
    if recorded_raw_root != raw_root or not live_source_packet._git_ignored(raw_root):
        raise ReplayError("replay source raw root must exactly match the gitignored capture summary reference")
    if not isinstance(records, list):
        raise ReplayError("replay source summary must list every captured endpoint record")
    if not isinstance(budget, dict) or budget.get("max_total_endpoint_calls") != expected_total_call_budget \
            or budget.get("actual_total_endpoint_calls") != len(records):
        raise ReplayError("replay source summary endpoint budget/record count is not bound to this replay")
    if not records:
        raise ReplayError("replay source summary must list every captured endpoint record")
    coverage = summary.get("massive_batch_coverage")
    if not isinstance(coverage, dict) or set(coverage) != set(live_source_packet._MASSIVE_BATCH_FAMILIES):
        raise ReplayError("replay source summary lacks complete Massive batch coverage")
    manifest = summary.get("raw_capture_manifest")
    if not isinstance(manifest, dict) or set(manifest) != {"endpoint_wrapper_sha256", "manifest_sha256"}:
        raise ReplayError("replay source summary lacks the raw capture manifest")
    manifest_rows = manifest.get("endpoint_wrapper_sha256")
    manifest_sha256 = manifest.get("manifest_sha256")
    if not isinstance(manifest_rows, list) or not manifest_rows or type(manifest_sha256) is not str:
        raise ReplayError("replay source summary raw capture manifest is malformed")
    manifest_by_key: dict[tuple[str, str, str | None], str] = {}
    manifest_by_ref: dict[tuple[str, str, str], str] = {}
    manifest_uses_raw_ref = None
    for row in manifest_rows:
        if not isinstance(row, dict):
            raise ReplayError("replay source summary raw capture manifest row is malformed")
        row_keys = set(row)
        if row_keys == {"provider_id", "endpoint_family", "symbol", "sha256"}:
            uses_raw_ref = False
        elif row_keys == {"provider_id", "endpoint_family", "symbol", "raw_sample_ref", "sha256"}:
            uses_raw_ref = True
        else:
            raise ReplayError("replay source summary raw capture manifest row is malformed")
        if manifest_uses_raw_ref is None:
            manifest_uses_raw_ref = uses_raw_ref
        elif manifest_uses_raw_ref is not uses_raw_ref:
            raise ReplayError("replay source summary raw capture manifest mixes identity formats")
        provider_id = row["provider_id"]
        endpoint_family = row["endpoint_family"]
        symbol = row["symbol"]
        digest = row["sha256"]
        raw_ref = row.get("raw_sample_ref")
        if type(provider_id) is not str or type(endpoint_family) is not str \
                or (symbol is not None and type(symbol) is not str) \
                or (uses_raw_ref and (type(raw_ref) is not str or not raw_ref)) \
                or type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ReplayError("replay source summary raw capture manifest identity is malformed")
        if uses_raw_ref:
            ref_key = (provider_id, endpoint_family, raw_ref)
            if ref_key in manifest_by_ref:
                raise ReplayError("replay source summary raw capture manifest has duplicate identities")
            manifest_by_ref[ref_key] = digest
        else:
            key = (provider_id, endpoint_family, symbol)
            if key in manifest_by_key:
                raise ReplayError("replay source summary raw capture manifest has duplicate identities")
            manifest_by_key[key] = digest
    canonical_manifest_sha256 = hashlib.sha256(
        json.dumps(manifest_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if manifest_sha256 != canonical_manifest_sha256:
        raise ReplayError("replay source summary raw capture manifest digest is inconsistent")

    expected: dict[tuple[Any, ...], tuple[Path, str]] = {}
    record_refs: set[tuple[str, str, str]] = set()
    record_keys: set[tuple[str, str, str | None]] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ReplayError("replay source summary endpoint record must be an object")
        provider_id = record.get("provider_id")
        endpoint_family = record.get("endpoint_family")
        symbol = record.get("symbol")
        raw_ref = record.get("raw_sample_ref")
        if type(provider_id) is not str or type(endpoint_family) is not str \
                or (symbol is not None and type(symbol) is not str) or type(raw_ref) is not str:
            raise ReplayError("replay source summary endpoint identity is malformed")
        raw_path = (ROOT / raw_ref).resolve()
        try:
            raw_path.relative_to(raw_root)
        except ValueError as exc:
            raise ReplayError("replay source summary endpoint raw path escapes its raw root") from exc
        if manifest_uses_raw_ref:
            ref_key = (provider_id, endpoint_family, raw_ref)
            if ref_key in record_refs:
                raise ReplayError("replay source summary has duplicate raw wrapper references")
            record_refs.add(ref_key)
            digest = manifest_by_ref.get(ref_key)
        else:
            key3 = (provider_id, endpoint_family, symbol)
            if key3 in record_keys:
                raise ReplayError("replay source summary has duplicate endpoint identities")
            record_keys.add(key3)
            digest = manifest_by_key.get(key3)
        if digest is None:
            raise ReplayError("replay source summary endpoint is absent from its raw capture manifest")
        try:
            actual_digest = _sha256_file(raw_path)
        except OSError as exc:
            raise ReplayError("replay source raw wrapper cannot be read for manifest validation") from exc
        if actual_digest != digest:
            raise ReplayError("replay source raw wrapper bytes drift from the captured manifest")
        try:
            wrapper = json.loads(raw_path.read_text(encoding="utf-8"))
            key, _ = _canonical_wrapper(wrapper, wrapper_path=raw_path, source_raw_root=raw_root)
        except (OSError, json.JSONDecodeError) as exc:
            raise ReplayError("replay source raw wrapper cannot be read as JSON") from exc
        if key in expected:
            raise ReplayError("replay source summary maps multiple rows to one raw wrapper identity")
        expected[key] = (raw_path, digest)
    if manifest_uses_raw_ref:
        if record_refs != set(manifest_by_ref):
            raise ReplayError("replay source raw capture manifest identities drift from endpoint records")
    elif record_keys != set(manifest_by_key):
        raise ReplayError("replay source raw capture manifest identities drift from endpoint records")
    for family in live_source_packet._MASSIVE_BATCH_FAMILIES:
        family_coverage = coverage.get(family)
        page_count = family_coverage.get("page_count") if isinstance(family_coverage, dict) else None
        if type(page_count) is not int or page_count < 0:
            raise ReplayError("replay Massive batch coverage page count is invalid")
        page_keys = sorted(
            key for key in expected
            if len(key) == 4 and key[:3] == ("massive", family, "page")
        )
        if page_count != len(page_keys) or page_keys != [
            ("massive", family, "page", number) for number in range(1, page_count + 1)
        ]:
            raise ReplayError("replay Massive batch page count does not match the captured summary")
    if sum(
        coverage[family]["page_count"] for family in live_source_packet._MASSIVE_BATCH_FAMILIES
    ) > live_source_packet.MASSIVE_BATCH_LOGICAL_CALL_CAP:
        raise ReplayError("replay Massive batch page cap exceeded")
    source_packet_ref = (summary.get("source_packet") or {}).get("path")
    source_artifacts = summary.get("source_artifacts")
    if not isinstance(source_artifacts, dict) or source_artifacts.get("active_analyst_source") not in {"yfinance", "fmp"}:
        raise ReplayError("replay source summary lacks active analyst-source binding")
    if not isinstance(source_packet_ref, str):
        raise ReplayError("replay source summary lacks its source packet path")
    source_packet_path = (ROOT / source_packet_ref).resolve()
    if not source_packet_path.is_file():
        raise ReplayError("replay source packet does not exist")
    try:
        source_packet = json.loads(source_packet_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError("replay source packet is not readable JSON") from exc
    if not isinstance(source_packet, dict) \
            or source_packet.get("active_analyst_source") != source_artifacts["active_analyst_source"]:
        raise ReplayError("replay source packet active analyst source drifted from its summary")
    packet_paths = source_packet.get("paths")
    active_path = source_artifacts.get("analyst_grade_actions_path")
    if not isinstance(packet_paths, dict) or packet_paths.get("analyst_grade_actions_path") != active_path:
        raise ReplayError("replay source packet analyst artifact path drifted from its summary")
    active_digest = (source_packet.get("source_artifact_sha256") or {}).get("analyst_grade_actions_path")
    if type(active_path) is not str or type(active_digest) is not str:
        raise ReplayError("replay source packet lacks the active analyst artifact digest")
    active_artifact_path = (ROOT / active_path).resolve()
    if not active_artifact_path.is_file() or _sha256_file(active_artifact_path) != active_digest:
        raise ReplayError("replay active analyst artifact drifted from the original source packet")
    summary_ref = storage.get("tracked_summary_path")
    if type(summary_ref) is not str or (ROOT / summary_ref).resolve() != summary_path:
        raise ReplayError("replay source summary does not self-bind its summary path")
    capture = {
        "source_summary_path": summary_ref,
        "source_summary_sha256": _sha256_file(summary_path),
        "source_raw_root": storage["raw_payload_root"],
        "source_observed_at": observed_at,
        "source_expected_decision_date": source_decision_date,
        "source_as_of": source_as_of,
        "raw_wrapper_count": len(expected),
        "source_capture_manifest_sha256": manifest_sha256,
        "active_analyst_source": source_artifacts["active_analyst_source"],
        "analyst_grade_actions_path": active_path,
        "analyst_grade_actions_sha256": active_digest,
        "non_emittable": True,
    }
    return expected, capture, observed_at


def run_replay(
    *,
    source_raw_root: Path,
    source_summary_path: Path,
    preflight_summary_path: Path,
    expected_total_call_budget: int,
    output_prefix: Path,
    summary_path: Path,
    replay_raw_root: Path,
    observed_at: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    source_root = Path(source_raw_root).resolve()
    replay_root = Path(replay_raw_root).resolve()
    if source_root == replay_root:
        raise ReplayError("replay_raw_root must differ from source_raw_root")
    expected, capture, capture_observed_at = _load_bound_source_capture(
        source_summary_path=source_summary_path,
        source_raw_root=source_root,
        expected_total_call_budget=expected_total_call_budget,
    )
    source_decision_date = capture["source_expected_decision_date"]
    for field, path in (("replay_raw_root", replay_root), ("summary_path", Path(summary_path).resolve())):
        try:
            relative = path.relative_to((ROOT / live_source_packet.RAW_SAMPLE_REL_ROOT).resolve())
        except ValueError as exc:
            raise ReplayError(
                f"{field} must stay under the decision-date Pass2 provider_samples root"
            ) from exc
        if len(relative.parts) < 2 or relative.parts[0] != source_decision_date:
            raise ReplayError(
                f"{field} must use the source capture decision-date provider_samples root"
            )
    if Path(summary_path).suffix != ".json":
        raise ReplayError("summary_path must be a JSON file")
    if observed_at is not None and observed_at != capture_observed_at:
        raise ReplayError("offline replay must retain the source capture observation clock")
    try:
        preflight = live_source_packet._load_ready_preflight(
            live_source_packet._validate_preflight_path(preflight_summary_path),
            expected_total_call_budget,
        )
    except live_source_packet.FullCandidateLiveSourcePacketError as exc:
        raise ReplayError("replay preflight is not a ready bound input") from exc
    if preflight["decision_clock"]["expected_decision_date"] != capture["source_expected_decision_date"]:
        raise ReplayError("offline replay preflight decision date must match the source capture")
    if preflight.get("active_analyst_source") != capture["active_analyst_source"]:
        raise ReplayError("offline replay preflight analyst source must match the source capture")
    client = ReplayClient(source_root, expected_records=expected, bound_capture=capture)
    saved_environment = {name: os.environ.get(name) for name in ("FMP_API_KEY", "SEC_USER_AGENT", "MASSIVE_API_KEY")}
    try:
        for name in saved_environment:
            os.environ[name] = "REPLAY_NO_NETWORK_NOT_A_SECRET"
        return live_source_packet.run_full_candidate_live_source_packet(
            preflight_summary_path=preflight_summary_path,
            expected_total_call_budget=expected_total_call_budget,
            output_data_context_path=output_prefix.with_name(output_prefix.name + "_data_context.json"),
            context_components_output_path=output_prefix.with_name(output_prefix.name + "_context_components.json"),
            source_artifact_prefix=output_prefix,
            summary_path=summary_path,
            raw_root=replay_root,
            client=client,
            confirm_user_authorization=False,
            run_data_context=False,
            generated_at=generated_at,
            observed_at=capture_observed_at,
            sec_sleep_seconds=0,
            max_total_http_attempts=expected_total_call_budget,
            execution_mode="offline_replay",
            replay_source_capture=capture,
            yfinance_grade_actions_path=(
                (ROOT / capture["analyst_grade_actions_path"]).resolve()
                if capture["active_analyst_source"] == "yfinance" else None
            ),
            theme_soft_boost_enabled=False,
        )
    finally:
        for name, prior in saved_environment.items():
            if prior is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = prior


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-raw-root", required=True, type=Path)
    parser.add_argument("--source-summary-path", required=True, type=Path)
    parser.add_argument("--preflight-summary-path", required=True, type=Path)
    parser.add_argument("--expected-total-call-budget", required=True, type=int)
    parser.add_argument("--output-prefix", required=True, type=Path)
    parser.add_argument("--summary-path", required=True, type=Path)
    parser.add_argument("--replay-raw-root", required=True, type=Path)
    parser.add_argument("--observed-at", help="optional equality check against the original capture clock")
    parser.add_argument("--generated-at", default=None)
    args = parser.parse_args(argv)
    try:
        summary = run_replay(
            source_raw_root=args.source_raw_root,
            source_summary_path=args.source_summary_path,
            preflight_summary_path=args.preflight_summary_path,
            expected_total_call_budget=args.expected_total_call_budget,
            output_prefix=args.output_prefix,
            summary_path=args.summary_path,
            replay_raw_root=args.replay_raw_root,
            observed_at=args.observed_at,
            generated_at=args.generated_at,
        )
    except ReplayError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": summary["scope"]["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
