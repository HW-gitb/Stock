"""Offline replay of the full-candidate Pass2 source packet from ALREADY-PERSISTED provider raw.

Motivation. A gated Pass2 live fetch (`runners.us_short_batch5_full_candidate_live_source_packet`) persists every
provider response under `provider_samples/.../<run>_raw/<provider>/<symbol>/<endpoint>.json` as a wrapper
`{provider_id, endpoint_family, symbol, http_status, ok, error_type, payload}`. When only the ASSEMBLY step (the
engine resolvers) needs a fix, re-running the whole fetch re-pays 1000+ gated provider calls -- and on a free tier
can DEGRADE coverage as daily quotas deplete. This replay serves that already-captured raw back through the
IDENTICAL stage-5 runner so the fix can be validated on the real payloads with ZERO new provider calls.

Mechanism. `run_full_candidate_live_source_packet` performs exactly one network step -- `_fetch_live_records` via its
injectable `client`. `ReplayClient` implements the same `get_json(url) -> (payload, http_status, ok, error_type)`
contract but resolves each call from the persisted wrapper keyed by the (provider, endpoint_family, symbol) parsed
out of the URL the runner builds. Every downstream step (resolvers, corporate-action capture, packet build + schema
validation + secret scrubbing + atomic writes) runs UNCHANGED, so the output is the exact source packet that fetch
would have produced from that raw.

Honesty / safety. NO network is performed and NO real provider secret is read: the driver sets dummy provider env
values (the ReplayClient never uses the key -- it matches on symbol/ticker/CIK), and the source raw is read-only (a
fresh, separate replay raw is written by the runner). This is NOT a provider fetch and NOT a substitute for a real
fetch when fresh data is wanted; it only re-derives a packet from raw that was already captured under an approved
gated run (SR-PROVIDER-001 stays governed by the original fetch)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import us_short_batch5_full_candidate_live_source_packet as live_source_packet  # noqa: E402


class ReplayError(RuntimeError):
    """Raised when the persisted raw cannot back a faithful replay."""


def _query_param(url: str, name: str) -> str | None:
    values = parse_qs(urlparse(url).query).get(name)
    return values[0] if values else None


class ReplayClient:
    """A `JsonHttpClient`-shaped stand-in that returns persisted provider responses instead of calling the network.

    It loads every wrapper under `source_raw_root` into a (provider_id, endpoint_family, symbol) -> wrapper map, and
    builds a 10-digit-CIK -> symbol index from the SEC submissions wrappers so a `.../submissions/CIK##########.json`
    URL (which carries no ticker) resolves back to its symbol. `get_json` returns the wrapper's own
    (payload, http_status, ok, error_type) verbatim -- a rate-limited (ok=False / 429) call replays as ok=False, so
    the runner's graceful-degradation path is exercised exactly as it was during the real fetch."""

    def __init__(self, source_raw_root: Path) -> None:
        self._by_key: dict[tuple, dict] = {}
        self._cik_to_symbol: dict[str, str] = {}
        loaded = 0
        for wrapper_path in Path(source_raw_root).rglob("*.json"):
            if wrapper_path.name.endswith(".tmp"):
                continue
            try:
                wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(wrapper, dict) or "payload" not in wrapper:
                continue
            key = (wrapper.get("provider_id"), wrapper.get("endpoint_family"), wrapper.get("symbol"))
            self._by_key[key] = wrapper
            loaded += 1
            if wrapper.get("provider_id") == "sec_edgar" and wrapper.get("endpoint_family") == "submissions":
                payload = wrapper.get("payload")
                cik = payload.get("cik") if isinstance(payload, dict) else None
                symbol = wrapper.get("symbol")
                if isinstance(cik, str) and cik.strip() and isinstance(symbol, str):
                    self._cik_to_symbol[cik.strip().zfill(10)] = symbol
        if loaded == 0:
            raise ReplayError(f"no persisted raw wrappers found under {source_raw_root}")

    def _url_to_key(self, url: str) -> tuple:
        if "company_tickers.json" in url:
            return ("sec_edgar", "company_tickers_mapping", None)
        submissions = re.search(r"/submissions/CIK(\d{10})\.json", url)
        if submissions:
            return ("sec_edgar", "submissions", self._cik_to_symbol.get(submissions.group(1)))
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
                family = None
            return ("massive", family, ticker)
        return (None, None, None)

    def get_json(self, url: str, *, headers: dict | None = None, timeout_seconds: int | None = None):
        wrapper = self._by_key.get(self._url_to_key(url))
        if wrapper is None:
            # No captured raw for this call -> replay as a failed fetch (coverage=missing), never fabricate a payload.
            return None, None, False, "replay_missing"
        return wrapper.get("payload"), wrapper.get("http_status"), bool(wrapper.get("ok")), wrapper.get("error_type")


def run_replay(
    *,
    source_raw_root: Path,
    preflight_summary_path: Path,
    expected_total_call_budget: int,
    output_prefix: Path,
    summary_path: Path,
    replay_raw_root: Path,
    observed_at: str,
    generated_at: str | None = None,
    run_data_context: bool = True,
) -> dict:
    client = ReplayClient(source_raw_root)
    # Dummy provider env so read_required_env is satisfied without reading (or exposing) any real secret; the
    # ReplayClient never uses these values.
    for name in ("FMP_API_KEY", "SEC_USER_AGENT", "MASSIVE_API_KEY"):
        os.environ[name] = "REPLAY_NO_NETWORK_NOT_A_SECRET"
    return live_source_packet.run_full_candidate_live_source_packet(
        preflight_summary_path=preflight_summary_path,
        expected_total_call_budget=expected_total_call_budget,
        output_data_context_path=output_prefix.with_name(output_prefix.name + "_data_context.json"),
        context_components_output_path=output_prefix.with_name(output_prefix.name + "_context_components.json"),
        source_artifact_prefix=output_prefix,
        summary_path=summary_path,
        raw_root=replay_raw_root,
        client=client,
        confirm_user_authorization=True,
        run_data_context=run_data_context,
        generated_at=generated_at,
        observed_at=observed_at,
        sec_sleep_seconds=0,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-raw-root", required=True, type=Path)
    parser.add_argument("--preflight-summary-path", required=True, type=Path)
    parser.add_argument("--expected-total-call-budget", required=True, type=int)
    parser.add_argument("--output-prefix", required=True, type=Path)
    parser.add_argument("--summary-path", required=True, type=Path)
    parser.add_argument("--replay-raw-root", required=True, type=Path)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--no-data-context", action="store_true")
    args = parser.parse_args(argv)
    summary = run_replay(
        source_raw_root=args.source_raw_root,
        preflight_summary_path=args.preflight_summary_path,
        expected_total_call_budget=args.expected_total_call_budget,
        output_prefix=args.output_prefix,
        summary_path=args.summary_path,
        replay_raw_root=args.replay_raw_root,
        observed_at=args.observed_at,
        generated_at=args.generated_at,
        run_data_context=not args.no_data_context,
    )
    print(json.dumps({"status": "replay_complete", "source_packet": summary.get("source_packet")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
