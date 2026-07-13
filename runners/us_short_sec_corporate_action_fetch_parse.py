"""One-document, default-dry-run SEC fetch plus strict simple corporate-action parsing.

The operator supplies one reviewed SEC Archives document reference.  A live call requires
``--run --confirm-user-authorization`` and a nonempty ``SEC_USER_AGENT``.  The document is
read in memory, reduced to a digest plus an unconfirmed candidate, and never persisted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from jsonschema import Draft7Validator

from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path
from engine.us_short_sec_simple_corporate_action_parser import (
    SecCorporateActionParserError,
    parse_simple_sec_corporate_action,
)
from engine.us_short_security_identity import SecurityIdentityError, validate_security_identity


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/us_short_sec_corporate_action_parse_candidate.schema.json"
REQUEST_SCHEMA_PATH = ROOT / "schemas/us_short_sec_corporate_action_fetch_request.schema.json"
DEFAULT_OUTPUT = (ROOT / "state/us_short/lifecycle/sec_corporate_action_parse_candidate.json").resolve()
_REQUEST_KEYS = frozenset((
    "schema_name", "schema_version", "provider_id", "document_url", "issuer_cik", "form_type",
    "accession_number", "filed_date", "accepted_at", "max_provider_calls",
    "raw_document_persist_allowed", "automatic_confirmation_allowed",
))
_ARCHIVE_PATH_RE = re.compile(
    r"^/Archives/edgar/data/([0-9]{1,10})/([0-9]{18})/([A-Za-z0-9][A-Za-z0-9._-]{0,255})$"
)
_ACCESSION_RE = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
MAX_DOCUMENT_BYTES = 2_000_000


class SecCorporateActionFetchParseError(ValueError):
    """The authorization, path, SEC request, fetch, parse, or output contract failed."""


class UrllibSecTextClient:
    def get_text(self, url: str, *, headers: dict[str, str]) -> str:
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                raise SecCorporateActionFetchParseError("SEC document redirect is not allowed")

        request = urllib.request.Request(url, headers=headers)
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=30) as response:
            raw = response.read(MAX_DOCUMENT_BYTES + 1)
            if len(raw) > MAX_DOCUMENT_BYTES:
                raise SecCorporateActionFetchParseError("SEC document exceeds the bounded parser size")
            charset = response.headers.get_content_charset() or "utf-8"
        try:
            return raw.decode(charset, errors="strict")
        except (LookupError, UnicodeDecodeError) as exc:
            raise SecCorporateActionFetchParseError("SEC document encoding is unsupported") from exc


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SecCorporateActionFetchParseError(f"{label} is not readable valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise SecCorporateActionFetchParseError(f"{label} must be a JSON object")
    return value


def _request(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _REQUEST_KEYS:
        raise SecCorporateActionFetchParseError("source request must have the exact contract keys")
    request_schema = json.loads(REQUEST_SCHEMA_PATH.read_text(encoding="utf-8"))
    if list(Draft7Validator(request_schema).iter_errors(value)):
        raise SecCorporateActionFetchParseError("source request failed its schema")
    if type(value["issuer_cik"]) is not str or re.fullmatch(r"[0-9]{10}", value["issuer_cik"]) is None:
        raise SecCorporateActionFetchParseError("source request issuer_cik must be ten digits")
    if type(value["accession_number"]) is not str or _ACCESSION_RE.fullmatch(value["accession_number"]) is None:
        raise SecCorporateActionFetchParseError("source request accession_number is invalid")
    _validate_archive_url(value["document_url"], cik=value["issuer_cik"], accession=value["accession_number"])
    return value


def _validate_archive_url(url: Any, *, cik: str, accession: str) -> str:
    if type(url) is not str or len(url) > 1000:
        raise SecCorporateActionFetchParseError("SEC document_url must be a bounded string")
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise SecCorporateActionFetchParseError("SEC document_url is malformed") from exc
    if (parsed.scheme != "https" or parsed.hostname != "www.sec.gov" or port not in (None, 443)
            or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment):
        raise SecCorporateActionFetchParseError("SEC document_url must be a plain https://www.sec.gov Archives URL")
    match = _ARCHIVE_PATH_RE.fullmatch(parsed.path)
    if match is None:
        raise SecCorporateActionFetchParseError("SEC document_url path is outside the bounded Archives shape")
    url_cik, url_accession, _ = match.groups()
    if int(url_cik) != int(cik) or url_accession != accession.replace("-", ""):
        raise SecCorporateActionFetchParseError("SEC document_url CIK/accession is not bound to the request")
    return url


def _user_agent(value: Any) -> str:
    if type(value) is not str or not value.strip() or len(value) > 256 or "\n" in value or "\r" in value:
        raise SecCorporateActionFetchParseError("SEC_USER_AGENT is required and must be a safe one-line value")
    return value.strip()


def _observed_at(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if type(value) is not str:
        raise SecCorporateActionFetchParseError("observed_at must be a string")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise SecCorporateActionFetchParseError("observed_at must be an aware ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise SecCorporateActionFetchParseError("observed_at must be timezone-aware")
    return value


def _validate_pre_fetch_bindings(
    identity_record: dict[str, Any],
    successor: dict[str, Any] | None,
    request: dict[str, Any],
    observed_at: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        identity_record = validate_security_identity(identity_record)
        successor = validate_security_identity(successor) if successor is not None else None
    except SecurityIdentityError as exc:
        raise SecCorporateActionFetchParseError("identity binding is invalid before SEC fetch") from exc
    allowed_ciks = {identity_record["issuer_cik"]}
    if successor is not None:
        if successor["security_id"] == identity_record["security_id"]:
            raise SecCorporateActionFetchParseError("successor identity must differ from the old security")
        allowed_ciks.add(successor["issuer_cik"])
    if request["issuer_cik"] not in allowed_ciks:
        raise SecCorporateActionFetchParseError("source request CIK is not bound to old or successor identity")
    if request["accession_number"][:10] != request["issuer_cik"]:
        raise SecCorporateActionFetchParseError("source request accession is not bound to its issuer CIK")
    try:
        filed = datetime.strptime(request["filed_date"], "%Y-%m-%d")
        accepted = datetime.fromisoformat(
            request["accepted_at"][:-1] + "+00:00" if request["accepted_at"].endswith("Z") else request["accepted_at"]
        )
        observed = datetime.fromisoformat(observed_at[:-1] + "+00:00" if observed_at.endswith("Z") else observed_at)
    except ValueError as exc:
        raise SecCorporateActionFetchParseError("source request dates/timestamps are invalid") from exc
    if accepted.tzinfo is None or observed.tzinfo is None:
        raise SecCorporateActionFetchParseError("source request timestamps must be timezone-aware")
    if filed.date() > accepted.date() or accepted > observed:
        raise SecCorporateActionFetchParseError("source request chronology is invalid before SEC fetch")
    return identity_record, successor


def _validate_result(result: dict[str, Any]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft7Validator(schema).iter_errors(result))
    if errors:
        raise SecCorporateActionFetchParseError("parser output failed its schema")


def _write_json_atomic(value: dict[str, Any], path: Path) -> None:
    try:
        reject_nonprivate_output_path(path)
    except PrivatePathError as exc:
        raise SecCorporateActionFetchParseError("output path is not provably private") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def run_sec_fetch_parse(
    *,
    identity_path: Path,
    source_request_path: Path,
    output_path: Path,
    successor_identity_path: Path | None = None,
    confirm_user_authorization: bool,
    sec_user_agent: str | None = None,
    observed_at: str | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Perform exactly one authorized SEC document call and write one private candidate."""
    output_path = Path(output_path).resolve()
    try:
        reject_nonprivate_output_path(output_path)
    except PrivatePathError as exc:
        raise SecCorporateActionFetchParseError("output path is not provably private") from exc
    if confirm_user_authorization is not True:
        raise SecCorporateActionFetchParseError("SEC fetch requires explicit per-execution user authorization")

    identity_record = _read_json(Path(identity_path), label="identity")
    successor = (_read_json(Path(successor_identity_path), label="successor identity")
                 if successor_identity_path is not None else None)
    request = _request(_read_json(Path(source_request_path), label="source request"))
    observed = _observed_at(observed_at)
    identity_record, successor = _validate_pre_fetch_bindings(identity_record, successor, request, observed)
    user_agent = _user_agent(sec_user_agent if sec_user_agent is not None else os.environ.get("SEC_USER_AGENT"))
    fetcher = client if client is not None else UrllibSecTextClient()
    try:
        text = fetcher.get_text(request["document_url"], headers={"User-Agent": user_agent, "Host": "www.sec.gov"})
    except SecCorporateActionFetchParseError:
        raise
    except Exception as exc:
        raise SecCorporateActionFetchParseError("SEC document fetch failed") from exc
    if type(text) is not str or not text or len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise SecCorporateActionFetchParseError("SEC client returned an invalid or oversized document")
    filing = {
        "provider_id": "sec_edgar",
        "issuer_cik": request["issuer_cik"],
        "form_type": request["form_type"],
        "accession_number": request["accession_number"],
        "filed_date": request["filed_date"],
        "accepted_at": request["accepted_at"],
        "observed_at": observed,
        "document_ref_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "document_text": text,
        "network_access_performed": True,
    }
    try:
        result = parse_simple_sec_corporate_action(
            identity_record=identity_record,
            successor_identity_record=successor,
            filing=filing,
        )
    except SecCorporateActionParserError as exc:
        raise SecCorporateActionFetchParseError("SEC document or source binding failed closed") from exc
    _validate_result(result)
    _write_json_atomic(result, output_path)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch one reviewed SEC filing and parse only strict simple corporate-action terms. Default dry-run.")
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--successor-identity", type=Path)
    parser.add_argument("--source-request", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--observed-at")
    parser.add_argument("--confirm-user-authorization", action="store_true")
    parser.add_argument("--run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.run:
        print(json.dumps({"status": "dry_run", "provider_calls": 0, "max_live_calls": 1,
                          "output_must_be_private": True, "automatic_confirmation_allowed": False}, indent=2))
        return 0
    try:
        result = run_sec_fetch_parse(
            identity_path=args.identity,
            successor_identity_path=args.successor_identity,
            source_request_path=args.source_request,
            output_path=args.out,
            observed_at=args.observed_at,
            confirm_user_authorization=args.confirm_user_authorization,
        )
    except SecCorporateActionFetchParseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"parse_status": result["parse_status"], "output": str(Path(args.out).resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
