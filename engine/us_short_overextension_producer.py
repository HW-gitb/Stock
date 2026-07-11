# -*- coding: utf-8 -*-
"""US-short full-universe overextension PRODUCER (offline; §4.3 过热分档, pool-level).

Design authority: docs/us_short_system_design.md §4.3 + docs/system_risk_register.md::
R-USSHORT-BATCH5-OVEREXTENSION-WIRING-INCOMPLETE (cut 2b, offline half).

Consume an OHLCV series packet + the Pass-1 eligible set → a per-ticker overextension tier map, computed at
the SCORING stage (before ranking) so `chasing_extreme` can strip theme at the §4.3 selection layer and
`warning` can drive the §6/§8 execution levers downstream.

ENVELOPE coherence is fail-closed (mirrors the momentum producer's `_canonical_series_by_ticker`): every
packet series must be for a canonical, non-duplicate, ELIGIBLE ticker whose clock matches the run
(`series.as_of == price_basis_date`, `session` / `adjustment_mode` == the run contract). A stray / duplicate /
clock-mismatched series is a forged or look-ahead packet and RAISES — a series carrying a future `as_of` would
otherwise PIT-cut at a different (later) date and leak look-ahead. Per-ticker DATA quality is NOT judged here:
an eligible ticker ABSENT from the packet, or one whose series is thin / short / malformed, dispositions to
`insufficient_data` via engine/us_short_overextension.py::compute_overextension_features (the single PIT /
classify authority, which never raises on per-ticker data). Pure/offline; no provider/live/network; no
DataHub/production/ship-gate; no A-share crossing.
"""
import hashlib
import json

from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_overextension import compute_overextension_features, validate_overextension_result

DISPOSITIONS = ("scored", "insufficient_data")


class OverextensionProducerError(ValueError):
    """An OHLCV series packet cannot be consumed into an overextension projection safely (corrupt envelope)."""


def eligible_tickers_sha256(tickers):
    """Stable candidate-universe binding used by the producer and the source-packet consumer."""
    if not isinstance(tickers, (list, tuple)):
        raise OverextensionProducerError("eligible tickers must be a list/tuple")
    canonical, seen = [], set()
    for raw in tickers:
        ct = _canonical(raw, field="eligible ticker digest")
        if ct in seen:
            raise OverextensionProducerError(f"eligible ticker digest contains duplicate canonical ticker: {ct}")
        seen.add(ct)
        canonical.append(ct)
    payload = json.dumps(sorted(canonical), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical(raw, *, field):
    if not isinstance(raw, str):
        raise OverextensionProducerError(f"{field} must be a ticker string")
    ct = canonical_us_ticker(raw)
    if ct is None:
        raise OverextensionProducerError(f"{field} must be a canonicalizable US ticker: {raw!r}")
    return ct


def build_overextension_projection(series_by_ticker, eligible, *, price_basis_date, session, adjustment_mode):
    """Per-ticker §4.3 overextension tier for every eligible ticker, from the OHLCV series packet.

    ENVELOPE fail-closed (corrupt-packet / look-ahead signals): every packet series must be for a canonical,
    non-duplicate, eligible ticker with a clock matching the run (`as_of == price_basis_date`, `session` /
    `adjustment_mode` == the contract). A stray / duplicate / clock-mismatched / malformed present series RAISES.
    Per-ticker DATA quality is dispositioned (never raised): an eligible ticker ABSENT from the packet, or one
    whose series is thin / short, → `insufficient_data` via `compute_overextension_features`.

    Returns {overextension_by_ticker: {ticker: <compute_overextension_features result>},
             disposition_counts: {scored, insufficient_data}, scored_count, target_count}.
    """
    if not isinstance(eligible, (list, tuple)):
        raise OverextensionProducerError("eligible must be a list/tuple of tickers")
    eligible_canon, seen = [], set()
    for t in eligible:
        ct = _canonical(t, field="eligible ticker")
        if ct in seen:
            raise OverextensionProducerError(f"eligible contains a duplicate canonical ticker: {ct}")
        seen.add(ct)
        eligible_canon.append(ct)
    allowed = set(eligible_canon)

    if type(series_by_ticker) is not dict:
        raise OverextensionProducerError("series_by_ticker must be an exact dict")
    canonical_series = {}
    for raw_key, series in series_by_ticker.items():
        ct = _canonical(raw_key, field="series_by_ticker key")
        if ct in canonical_series:
            raise OverextensionProducerError(f"series_by_ticker contains a duplicate canonical ticker: {ct}")
        if ct not in allowed:
            raise OverextensionProducerError(f"series_by_ticker contains a ticker outside the eligible set: {ct}")
        if not isinstance(series, dict):
            raise OverextensionProducerError(f"{ct} series must be a dict")
        if series.get("as_of") != price_basis_date:
            raise OverextensionProducerError(
                f"{ct} series.as_of must equal the price_basis_date (look-ahead / forged-packet guard)")
        if series.get("session") != session:
            raise OverextensionProducerError(f"{ct} series.session must match the run contract")
        if series.get("adjustment_mode") != adjustment_mode:
            raise OverextensionProducerError(f"{ct} series.adjustment_mode must match the run contract")
        canonical_series[ct] = series

    overextension_by_ticker, counts = {}, {d: 0 for d in DISPOSITIONS}
    for ct in eligible_canon:
        result = compute_overextension_features(canonical_series.get(ct))
        try:
            validate_overextension_result(result, require_producer_metadata=True)
        except ValueError as exc:
            raise OverextensionProducerError(f"{ct} overextension result violated the producer contract") from exc
        overextension_by_ticker[ct] = result
        counts[result["disposition"]] = counts.get(result["disposition"], 0) + 1
    return {
        "overextension_by_ticker": overextension_by_ticker,
        "disposition_counts": counts,
        "scored_count": counts["scored"],
        "target_count": len(eligible_canon),
    }
