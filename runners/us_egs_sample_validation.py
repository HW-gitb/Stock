from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
APPROVAL_PATH = ROOT / "docs" / "provider_evidence_p1_us_sample_validation_access_approval_20260602.json"
SUMMARY_PATH = ROOT / "docs" / "provider_evidence_p1_us_sample_validation_summary_20260602.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "provider_p1_us_egs_sample_validation_summary.schema.json"
RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_egs_sample_validation_20260602")
RAW_SAMPLE_ROOT = ROOT / RAW_SAMPLE_REL_ROOT / "raw"

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
SEC_FILES_BASE_URL = "https://www.sec.gov/files"
SEC_DATA_BASE_URL = "https://data.sec.gov"
DEFAULT_TIMEOUT_SECONDS = 30
SEC_FAIR_ACCESS_SLEEP_SECONDS = 0.12

FMP_ENDPOINTS = [
    {
        "endpoint_family": "profile_or_company_metadata",
        "path_template": "profile/{symbol}",
        "params": {},
        "fields": ["symbol", "companyName", "sector", "industry", "mktCap", "price", "volAvg"],
    },
    {
        "endpoint_family": "income_statement",
        "path_template": "income-statement/{symbol}",
        "params": {"limit": "4"},
        "fields": ["date", "fillingDate", "acceptedDate", "period", "revenue", "netIncome"],
    },
    {
        "endpoint_family": "balance_sheet_statement",
        "path_template": "balance-sheet-statement/{symbol}",
        "params": {"limit": "4"},
        "fields": ["date", "fillingDate", "acceptedDate", "totalAssets", "totalDebt"],
    },
    {
        "endpoint_family": "cash_flow_statement",
        "path_template": "cash-flow-statement/{symbol}",
        "params": {"limit": "4"},
        "fields": ["date", "fillingDate", "acceptedDate", "operatingCashFlow", "freeCashFlow"],
    },
    {
        "endpoint_family": "financial_ratios_or_key_metrics",
        "path_template": "key-metrics/{symbol}",
        "params": {"limit": "4"},
        "fields": ["date", "marketCap", "peRatio", "revenuePerShare", "netIncomePerShare"],
    },
    {
        "endpoint_family": "historical_eod_price_volume",
        "path_template": "historical-price-full/{symbol}",
        "params": {"timeseries": "5"},
        "fields": ["date", "open", "close", "adjClose", "volume"],
    },
]

SEC_COMPANYFACTS_TAGS = {
    "revenue": [
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ("us-gaap", "Revenues"),
    ],
    "net_income": [("us-gaap", "NetIncomeLoss")],
    "assets": [("us-gaap", "Assets")],
    "shares_outstanding": [
        ("dei", "EntityCommonStockSharesOutstanding"),
        ("us-gaap", "CommonStocksIncludingAdditionalPaidInCapital"),
    ],
}


@dataclass
class EnvValue:
    value: str
    source: str


@dataclass
class FetchRecord:
    provider_id: str
    endpoint_family: str
    symbol: str | None
    raw_sample_ref: str
    ok: bool
    http_status: int | None
    error_type: str | None
    payload: Any


class JsonHttpClient:
    def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> tuple[Any, int | None, bool, str | None]:
        request = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read()
                return _parse_json_bytes(body), int(response.status), True, None
        except urllib.error.HTTPError as exc:
            body = exc.read()
            payload = _parse_json_bytes(body)
            return payload, int(exc.code), False, "http_error"
        except urllib.error.URLError as exc:
            return {"error": str(exc.reason)}, None, False, "url_error"
        except TimeoutError as exc:
            return {"error": str(exc)}, None, False, "timeout"


def _parse_json_bytes(body: bytes) -> Any:
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return {"non_json_response_bytes": len(body)}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the approved US EGS AAPL/MSFT FMP + SEC EDGAR small-sample "
            "validation packet. Raw provider/public API rows are written only "
            "under gitignored provider_samples/; tracked summary contains no secrets "
            "or full raw rows."
        )
    )
    parser.add_argument("--approval-path", type=Path, default=APPROVAL_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_SAMPLE_ROOT)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.add_argument(
        "--dry-run-env",
        action="store_true",
        help="Validate approval and environment boundary without fetching provider data.",
    )
    return parser.parse_args(argv)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json_atomic(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp_path.replace(path)


def load_and_validate_approval(path: Path) -> dict[str, Any]:
    approval = read_json(path)
    boundary = approval.get("approval_boundary") or {}
    universe = approval.get("sample_universe") or {}
    storage = approval.get("storage_and_secret_boundary") or {}
    scope = approval.get("scope") or {}
    provider_roles = {
        item.get("provider_id"): item.get("allowed_in_sample_validation")
        for item in approval.get("provider_roles", [])
        if isinstance(item, dict)
    }

    expected_false_boundary = [
        "fmp_new_token_request_allowed",
        "fmp_trial_request_allowed",
        "paid_access_allowed",
        "yfinance_allowed",
        "full_market_download_allowed",
        "provider_selection_allowed",
        "provider_adapter_allowed",
        "datahub_table_implementation_allowed",
        "runner_change_allowed",
    ]
    for field in expected_false_boundary:
        if boundary.get(field) is not False:
            raise ValueError(f"approval boundary must keep {field}=false")
    if boundary.get("approved_spend_usd") != 0:
        raise ValueError("approval boundary must keep approved_spend_usd=0")
    if boundary.get("fmp_existing_api_key_use_allowed") is not True:
        raise ValueError("approval boundary must allow only existing FMP API key use")
    if boundary.get("sec_edgar_public_api_allowed") is not True:
        raise ValueError("approval boundary must allow SEC EDGAR public API")
    if scope.get("phase7c_authorized_by_this_artifact") is not False:
        raise ValueError("approval artifact must not authorize Phase 7c")
    if scope.get("production_ready_claim_allowed") is not False:
        raise ValueError("approval artifact must not authorize production-ready claims")
    if provider_roles != {
        "financial_modeling_prep": True,
        "sec_edgar": True,
        "yfinance": False,
    }:
        raise ValueError("approval provider roles must allow only FMP and SEC EDGAR")
    if universe.get("allowed_symbols") != ["AAPL", "MSFT"]:
        raise ValueError("approval universe must be exactly AAPL / MSFT")
    if universe.get("max_symbols") != 2:
        raise ValueError("approval universe must keep max_symbols=2")
    if int(universe.get("max_total_endpoint_calls", 0)) > 40:
        raise ValueError("approval endpoint-call budget must be <= 40")
    if storage.get("raw_sample_storage_path") != "provider_samples/us_egs_sample_validation_20260602/":
        raise ValueError("raw sample storage path must stay under the approved provider_samples folder")
    if storage.get("raw_sample_storage_must_be_gitignored") is not True:
        raise ValueError("raw sample storage must be gitignored")
    if storage.get("secrets_in_repo_allowed") is not False:
        raise ValueError("secrets_in_repo_allowed must be false")
    if storage.get("api_key_logging_allowed") is not False:
        raise ValueError("api_key_logging_allowed must be false")
    return approval


def read_required_env(name: str) -> EnvValue:
    process_value = os.environ.get(name, "").strip()
    if process_value:
        return EnvValue(process_value, "process")
    windows_value = _read_windows_environment_value(name)
    if windows_value:
        return EnvValue(windows_value, "windows_environment")
    raise RuntimeError(f"{name} is required but was not found; value was not printed")


def _read_windows_environment_value(name: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError:
        return None
    locations = [
        (winreg.HKEY_CURRENT_USER, "Environment"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
    ]
    for root_key, subkey in locations:
        try:
            with winreg.OpenKey(root_key, subkey) as key:
                value, _ = winreg.QueryValueEx(key, name)
        except OSError:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def fmp_url(path_template: str, symbol: str, params: dict[str, str], api_key: str) -> str:
    params_with_key = dict(params)
    params_with_key["apikey"] = api_key
    encoded = urllib.parse.urlencode(params_with_key)
    return f"{FMP_BASE_URL}/{path_template.format(symbol=symbol)}?{encoded}"


def sec_url(endpoint_family: str, cik10: str | None = None) -> str:
    if endpoint_family == "company_tickers_mapping":
        return f"{SEC_FILES_BASE_URL}/company_tickers.json"
    if not cik10:
        raise ValueError(f"CIK is required for SEC endpoint {endpoint_family}")
    if endpoint_family == "submissions":
        return f"{SEC_DATA_BASE_URL}/submissions/CIK{cik10}.json"
    if endpoint_family == "companyfacts":
        return f"{SEC_DATA_BASE_URL}/api/xbrl/companyfacts/CIK{cik10}.json"
    raise ValueError(f"unknown SEC endpoint family: {endpoint_family}")


def raw_sample_ref(raw_root: Path, provider_id: str, endpoint_family: str, symbol: str | None) -> Path:
    safe_symbol = symbol or "_market"
    return raw_root / provider_id / safe_symbol / f"{endpoint_family}.json"


def as_repo_relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def validate_raw_root(raw_root: Path) -> None:
    resolved_root = raw_root.resolve()
    approved_root = (ROOT / "provider_samples").resolve()
    try:
        resolved_root.relative_to(approved_root)
    except ValueError as exc:
        raise ValueError("raw samples must be written under gitignored provider_samples/") from exc


def fetch_and_store(
    client: JsonHttpClient,
    *,
    url: str,
    provider_id: str,
    endpoint_family: str,
    symbol: str | None,
    raw_root: Path,
    headers: dict[str, str] | None = None,
) -> FetchRecord:
    payload, http_status, ok, error_type = client.get_json(url, headers=headers)
    raw_path = raw_sample_ref(raw_root, provider_id, endpoint_family, symbol)
    write_json_atomic(
        {
            "provider_id": provider_id,
            "endpoint_family": endpoint_family,
            "symbol": symbol,
            "http_status": http_status,
            "ok": ok,
            "error_type": error_type,
            "payload": payload,
        },
        raw_path,
    )
    return FetchRecord(
        provider_id=provider_id,
        endpoint_family=endpoint_family,
        symbol=symbol,
        raw_sample_ref=as_repo_relative(raw_path),
        ok=ok,
        http_status=http_status,
        error_type=error_type,
        payload=payload,
    )


def parse_sec_cik_map(company_tickers_payload: Any, symbols: list[str]) -> dict[str, str]:
    wanted = {symbol.upper() for symbol in symbols}
    cik_by_symbol: dict[str, str] = {}
    if not isinstance(company_tickers_payload, dict):
        return cik_by_symbol
    for item in company_tickers_payload.values():
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker", "")).upper()
        if ticker not in wanted:
            continue
        cik_value = item.get("cik_str")
        try:
            cik_by_symbol[ticker] = f"{int(cik_value):010d}"
        except (TypeError, ValueError):
            continue
    return cik_by_symbol


def run_sample_validation(
    *,
    approval_path: Path = APPROVAL_PATH,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_SAMPLE_ROOT,
    generated_at: str | None = None,
    client: JsonHttpClient | None = None,
    dry_run_env: bool = False,
) -> dict[str, Any]:
    approval = load_and_validate_approval(approval_path)
    validate_raw_root(raw_root)
    generated_at = generated_at or iso_now()
    symbols = approval["sample_universe"]["allowed_symbols"]
    max_total_endpoint_calls = int(approval["sample_universe"]["max_total_endpoint_calls"])
    fmp_env = read_required_env("FMP_API_KEY")
    sec_user_agent_env = read_required_env("SEC_USER_AGENT")
    env_summary = {
        "fmp_api_key_present": True,
        "fmp_api_key_source": fmp_env.source,
        "sec_user_agent_present": True,
        "sec_user_agent_source": sec_user_agent_env.source,
        "secrets_logged": False,
    }

    if dry_run_env:
        summary = build_summary(
            approval=approval,
            generated_at=generated_at,
            env_summary=env_summary,
            endpoint_records=[],
            cik_by_symbol={},
            max_total_endpoint_calls=max_total_endpoint_calls,
            dry_run_env=True,
        )
        write_json_atomic(summary, summary_path)
        return summary

    client = client or JsonHttpClient()
    endpoint_records: list[FetchRecord] = []

    sec_headers = {
        "User-Agent": sec_user_agent_env.value,
        "Host": "www.sec.gov",
    }
    endpoint_records.append(
        fetch_and_store(
            client,
            url=sec_url("company_tickers_mapping"),
            provider_id="sec_edgar",
            endpoint_family="company_tickers_mapping",
            symbol=None,
            raw_root=raw_root,
            headers=sec_headers,
        )
    )
    cik_by_symbol = parse_sec_cik_map(endpoint_records[-1].payload, symbols)

    fmp_headers = {"User-Agent": "StockSystem/0.1 sample-validation"}
    for symbol in symbols:
        for endpoint in FMP_ENDPOINTS:
            endpoint_records.append(
                fetch_and_store(
                    client,
                    url=fmp_url(
                        endpoint["path_template"],
                        symbol,
                        endpoint["params"],
                        fmp_env.value,
                    ),
                    provider_id="financial_modeling_prep",
                    endpoint_family=endpoint["endpoint_family"],
                    symbol=symbol,
                    raw_root=raw_root,
                    headers=fmp_headers,
                )
            )
        cik10 = cik_by_symbol.get(symbol)
        for endpoint_family in ["submissions", "companyfacts"]:
            if cik10:
                time.sleep(SEC_FAIR_ACCESS_SLEEP_SECONDS)
                endpoint_records.append(
                    fetch_and_store(
                        client,
                        url=sec_url(endpoint_family, cik10),
                        provider_id="sec_edgar",
                        endpoint_family=endpoint_family,
                        symbol=symbol,
                        raw_root=raw_root,
                        headers={
                            "User-Agent": sec_user_agent_env.value,
                            "Host": "data.sec.gov",
                        },
                    )
                )

    if len(endpoint_records) > max_total_endpoint_calls:
        raise RuntimeError(
            f"endpoint call count {len(endpoint_records)} exceeded approval budget "
            f"{max_total_endpoint_calls}"
        )

    summary = build_summary(
        approval=approval,
        generated_at=generated_at,
        env_summary=env_summary,
        endpoint_records=endpoint_records,
        cik_by_symbol=cik_by_symbol,
        max_total_endpoint_calls=max_total_endpoint_calls,
        dry_run_env=False,
    )
    write_json_atomic(summary, summary_path)
    return summary


def build_summary(
    *,
    approval: dict[str, Any],
    generated_at: str,
    env_summary: dict[str, Any],
    endpoint_records: list[FetchRecord],
    cik_by_symbol: dict[str, str],
    max_total_endpoint_calls: int,
    dry_run_env: bool,
) -> dict[str, Any]:
    symbols = approval["sample_universe"]["allowed_symbols"]
    endpoint_summaries = [summarize_endpoint_record(record) for record in endpoint_records]
    symbol_summaries = [
        summarize_symbol(symbol, endpoint_records, cik_by_symbol.get(symbol))
        for symbol in symbols
    ]
    endpoint_errors = sum(1 for record in endpoint_records if not record.ok)
    if dry_run_env:
        validation_status = "dry_run_env_only"
    elif endpoint_errors:
        validation_status = "completed_with_endpoint_errors"
    else:
        validation_status = "completed"
    limitations = [
        "This is a two-symbol active-name small sample, not a coverage proof.",
        "FMP endpoint success does not prove PIT semantics, license sufficiency, fallback behavior, or provider stability.",
        "SEC EDGAR checks are filing-grounded anomaly checks and do not make EDGAR a price or strict free-float source.",
        "No provider selection, DataHub implementation, runner consumption, Phase 7c authorization, or ship-gate evidence is claimed.",
    ]
    next_steps = [
        "Review endpoint availability, field presence, observed-date fields, SEC tag availability, and endpoint errors before deciding any follow-up.",
        "Do not broaden symbols, endpoints, providers, yfinance checks, full-market fetches, or DataHub work without separate explicit approval and review.",
    ]
    if any(
        record.provider_id == "financial_modeling_prep"
        and record.http_status == 403
        and record.error_type == "http_error"
        for record in endpoint_records
    ):
        limitations.append(
            "FMP v3 endpoint families returned 403 errors in this run; FMP is not sample-validated by this packet."
        )
        next_steps.insert(
            0,
            "Review current FMP endpoint mapping and plan a separate reviewed retry before treating FMP as a viable EGS source.",
        )

    return {
        "schema_name": "provider_p1_us_egs_sample_validation_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "approval_ref": "docs/provider_evidence_p1_us_sample_validation_access_approval_20260602.json",
        "schema_ref": "schemas/provider_p1_us_egs_sample_validation_summary.schema.json",
        "scope": {
            "phase": "7b-2",
            "purpose": "us_egs_small_sample_validation_summary",
            "validation_status": validation_status,
            "manual_order_only": True,
            "ship_gate_relaxed": False,
            "provider_selection_allowed": False,
            "datahub_table_implementation_allowed": False,
            "runner_change_allowed": False,
            "phase7c_authorized_by_this_summary": False,
            "production_ready_claim_allowed": False,
        },
        "environment": env_summary,
        "storage": {
            "raw_sample_storage_path": RAW_SAMPLE_REL_ROOT.as_posix() + "/",
            "raw_samples_gitignored": True,
            "tracked_summary_contains_raw_rows": False,
            "secrets_in_summary": False,
        },
        "sample_universe": {
            "symbols": symbols,
            "max_symbols": approval["sample_universe"]["max_symbols"],
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": max_total_endpoint_calls,
            "actual_total_endpoint_calls": len(endpoint_records),
            "within_budget": len(endpoint_records) <= max_total_endpoint_calls,
        },
        "endpoint_results": endpoint_summaries,
        "symbol_results": symbol_summaries,
        "prohibited_claims": {
            "provider_selected": False,
            "full_market_download_performed": False,
            "yfinance_used": False,
            "paid_access_used": False,
            "phase7c_authorized": False,
            "ship_gate_evidence_claimed": False,
        },
        "limitations": limitations,
        "next_steps": next_steps,
    }


def summarize_endpoint_record(record: FetchRecord) -> dict[str, Any]:
    payload = record.payload
    rows = payload_rows(record.endpoint_family, payload)
    return {
        "provider_id": record.provider_id,
        "endpoint_family": record.endpoint_family,
        "symbol": record.symbol,
        "status": "ok" if record.ok else "error",
        "http_status": record.http_status,
        "error_type": record.error_type,
        "raw_sample_ref": record.raw_sample_ref,
        "raw_sample_ref_gitignored": record.raw_sample_ref.startswith("provider_samples/"),
        "payload_shape": {
            "payload_type": type(payload).__name__,
            "top_level_key_count": len(payload) if isinstance(payload, dict) else None,
            "row_count": len(rows) if rows is not None else None,
        },
        "field_presence": endpoint_field_presence(record.endpoint_family, payload),
    }


def payload_rows(endpoint_family: str, payload: Any) -> list[Any] | None:
    if isinstance(payload, list):
        return payload
    if endpoint_family == "historical_eod_price_volume" and isinstance(payload, dict):
        rows = payload.get("historical")
        return rows if isinstance(rows, list) else None
    return None


def endpoint_field_presence(endpoint_family: str, payload: Any) -> dict[str, bool]:
    fields = fields_for_endpoint(endpoint_family)
    if not fields:
        return {}
    row = first_row(endpoint_family, payload)
    if not isinstance(row, dict):
        return {field: False for field in fields}
    return {field: field in row for field in fields}


def fields_for_endpoint(endpoint_family: str) -> list[str]:
    for endpoint in FMP_ENDPOINTS:
        if endpoint["endpoint_family"] == endpoint_family:
            return list(endpoint["fields"])
    if endpoint_family == "submissions":
        return ["filings", "recent", "filingDate", "acceptanceDateTime", "accessionNumber", "form"]
    if endpoint_family == "companyfacts":
        return ["facts"]
    if endpoint_family == "company_tickers_mapping":
        return ["ticker", "cik_str"]
    return []


def first_row(endpoint_family: str, payload: Any) -> dict[str, Any] | None:
    rows = payload_rows(endpoint_family, payload)
    if rows and isinstance(rows[0], dict):
        return rows[0]
    if endpoint_family == "profile_or_company_metadata" and isinstance(payload, list) and payload:
        return payload[0] if isinstance(payload[0], dict) else None
    if endpoint_family == "submissions" and isinstance(payload, dict):
        recent = ((payload.get("filings") or {}).get("recent") or {})
        if isinstance(recent, dict):
            return {
                "filings": payload.get("filings"),
                "recent": recent,
                "filingDate": recent.get("filingDate"),
                "acceptanceDateTime": recent.get("acceptanceDateTime"),
                "accessionNumber": recent.get("accessionNumber"),
                "form": recent.get("form"),
            }
    if endpoint_family == "companyfacts" and isinstance(payload, dict):
        return {"facts": payload.get("facts")}
    if endpoint_family == "company_tickers_mapping" and isinstance(payload, dict):
        first_value = next(iter(payload.values()), None)
        return first_value if isinstance(first_value, dict) else None
    if isinstance(payload, dict):
        return payload
    return None


def summarize_symbol(
    symbol: str,
    endpoint_records: list[FetchRecord],
    cik10: str | None,
) -> dict[str, Any]:
    symbol_records = [record for record in endpoint_records if record.symbol == symbol]
    fmp_records = [record for record in symbol_records if record.provider_id == "financial_modeling_prep"]
    sec_records = [record for record in symbol_records if record.provider_id == "sec_edgar"]
    companyfacts = next((record.payload for record in sec_records if record.endpoint_family == "companyfacts"), None)
    submissions = next((record.payload for record in sec_records if record.endpoint_family == "submissions"), None)
    fmp_statement_records = [
        record for record in fmp_records
        if record.endpoint_family in {"income_statement", "balance_sheet_statement", "cash_flow_statement"}
    ]
    return {
        "symbol": symbol,
        "cik": cik10,
        "fmp": {
            "endpoints_ok": sum(1 for record in fmp_records if record.ok),
            "endpoints_error": sum(1 for record in fmp_records if not record.ok),
            "statement_observed_date_fields_present": all(
                observed_date_fields_present(record.payload) for record in fmp_statement_records
            )
            if fmp_statement_records
            else False,
            "price_volume_fields_present": any(
                record.endpoint_family == "historical_eod_price_volume"
                and all(endpoint_field_presence(record.endpoint_family, record.payload).values())
                for record in fmp_records
            ),
        },
        "sec_edgar": {
            "cik_found": cik10 is not None,
            "endpoints_ok": sum(1 for record in sec_records if record.ok),
            "endpoints_error": sum(1 for record in sec_records if not record.ok),
            "submissions_observed_date_fields_present": sec_submissions_observed_date_fields_present(submissions),
            "companyfacts_core_tags_present": sec_companyfacts_core_tags_present(companyfacts),
        },
        "validation_observations": symbol_observations(symbol, fmp_records, sec_records, cik10),
    }


def observed_date_fields_present(payload: Any) -> bool:
    row = first_row("income_statement", payload)
    if not isinstance(row, dict):
        return False
    return all(field in row for field in ["date", "fillingDate", "acceptedDate"])


def sec_submissions_observed_date_fields_present(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    recent = ((payload.get("filings") or {}).get("recent") or {})
    if not isinstance(recent, dict):
        return False
    return all(field in recent for field in ["filingDate", "acceptanceDateTime", "accessionNumber"])


def sec_companyfacts_core_tags_present(payload: Any) -> dict[str, bool]:
    if not isinstance(payload, dict):
        return {name: False for name in SEC_COMPANYFACTS_TAGS}
    facts = payload.get("facts") or {}
    result: dict[str, bool] = {}
    for logical_name, candidates in SEC_COMPANYFACTS_TAGS.items():
        result[logical_name] = any(
            isinstance((facts.get(namespace) or {}), dict)
            and tag in (facts.get(namespace) or {})
            for namespace, tag in candidates
        )
    return result


def symbol_observations(
    symbol: str,
    fmp_records: list[FetchRecord],
    sec_records: list[FetchRecord],
    cik10: str | None,
) -> list[str]:
    observations: list[str] = []
    if cik10:
        observations.append(f"{symbol}: SEC ticker mapping found CIK.")
    else:
        observations.append(f"{symbol}: SEC ticker mapping missing CIK.")
    if fmp_records and all(record.ok for record in fmp_records):
        observations.append(f"{symbol}: all approved FMP endpoint families returned HTTP success.")
    elif fmp_records:
        observations.append(f"{symbol}: one or more approved FMP endpoint families returned an error.")
    if sec_records and all(record.ok for record in sec_records):
        observations.append(f"{symbol}: SEC submissions and companyfacts returned HTTP success.")
    elif sec_records:
        observations.append(f"{symbol}: one or more SEC endpoints returned an error.")
    observations.append(f"{symbol}: no provider selection, production readiness, or alpha evidence is claimed.")
    return observations


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_sample_validation(
        approval_path=args.approval_path,
        summary_path=args.summary_path,
        raw_root=args.raw_root,
        generated_at=args.generated_at,
        dry_run_env=args.dry_run_env,
    )
    print(
        json.dumps(
            {
                "summary_path": str(args.summary_path),
                "validation_status": summary["scope"]["validation_status"],
                "actual_total_endpoint_calls": summary["endpoint_call_budget"]["actual_total_endpoint_calls"],
                "secrets_logged": summary["environment"]["secrets_logged"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
