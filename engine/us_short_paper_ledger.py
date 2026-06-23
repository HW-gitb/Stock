# -*- coding: utf-8 -*-
"""US-short §12.1 model_paper_track 私密落盘 — batch-3 (#8 follow-up): paper_performance private persister.

Design authority: docs/us_short_system_design.md §12.1 (存储 state/us_short/model_paper_private/:
paper_orders / paper_positions / paper_performance) / §11.6 (lifecycle/shadow/paper 隐私: 含 $/持仓/成交 → 必须
private/gitignored) / §18.0 P0 (私密路径 guard) / §12 (paper 仅设计迭代). Consumes
``engine.us_short_paper_net_result.paper_net_result`` outputs.

paper_performance records carry per-fill $ / position / net-return detail, so they MUST land only on a gitignored
private path (``state/us_short/model_paper_private/``, §11.6). This is the FIRST paper persister:

  * ``write_paper_performance`` wires the §18.0 P0 fail-closed private-path guard (``reject_nonprivate_output_path``)
    BEFORE any validate / write, and refuses to persist a record whose per-entry shape is not self-consistent;
  * ``load_paper_performance`` applies the SAME §18.0 guard to the SOURCE first (SYMMETRIC — a private artifact is
    read only from a provably-private path), then re-validates (never consumes a garbage / inconsistent ledger).

The per-entry shape is FULLY self-enforced against the EXACT paper_net_result contract (the consumer never trusts
the producer): each entry carries EXACTLY the 6 keys (outcome, realized, gross_return, cost_fraction, net_return,
unfilled_cash — closed-world), and the per-outcome invariants hold — ``cash_unfilled`` = realized True /
gross=cost=net=0.0 / unfilled_cash True; ``open_unrealized`` = realized False / gross=cost=net=None /
unfilled_cash False; a closed outcome (``filled_stopped`` / ``filled_tp_exit``) = realized True / unfilled_cash
False / finite gross & net / finite NON-NEGATIVE cost / ``net_return == gross_return - cost_fraction``. An
inconsistent entry can never become official private paper evidence. Structure-over-IO: reads/writes a private
JSON only; no provider / live / DataHub / network; no A-share crossing. Malformed input fails closed.
"""
from __future__ import annotations

import datetime
import json
import math
from pathlib import Path

from engine.us_short_private_paths import reject_nonprivate_output_path

ROOT = Path(__file__).resolve().parent.parent
MODEL_PAPER_PRIVATE_DIR = ROOT / "state" / "us_short" / "model_paper_private"
PAPER_PERFORMANCE_PATH = MODEL_PAPER_PRIVATE_DIR / "paper_performance.json"  # canonical private location (§12.1 / §11.6)

# the paper_net_result outcomes + the exact entry key set a paper_performance entry carries (mirrors
# engine.us_short_paper_net_result; the integration test feeds real paper_net_result outputs so a shape change drifts loudly)
_OUTCOMES = ("cash_unfilled", "open_unrealized", "filled_stopped", "filled_tp_exit")
_ENTRY_KEYS = frozenset({"outcome", "realized", "gross_return", "cost_fraction", "net_return", "unfilled_cash"})
_CLOSE_TOL = 1e-9  # deterministic tolerance for net_return == gross_return - cost_fraction


class PaperLedgerError(ValueError):
    """Raised when a paper_performance record violates the §12.1 ledger contract (shape, date, entry consistency)."""


def _strict_yyyymmdd(s) -> bool:
    # inlined (mirrors the canonical lifecycle date gate) so this pure persistence helper stays importable on a
    # minimal runtime — it must NOT drag jsonschema in through engine.us_short_lifecycle_eval
    # (R-USSHORT-BATCH3-PAPER-LEDGER-IMPORT-COUPLING-GAP)
    if not (isinstance(s, str) and len(s) == 8 and s.isascii() and s.isdigit()):  # isascii() rejects Unicode digits (Arabic-Indic / fullwidth) that int() would still coerce
        return False
    try:
        datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        return True
    except ValueError:
        return False


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _validate_record(record) -> None:
    """Fail-closed §12.1 paper_performance record gate. Requires a dict with a strict real ``as_of`` and an
    ``entries`` list whose every entry carries EXACTLY the 6 paper_net_result keys (outcome, realized,
    gross_return, cost_fraction, net_return, unfilled_cash — closed-world) and satisfies the per-outcome
    invariants: ``cash_unfilled`` = realized True / gross=cost=net=0.0 / unfilled_cash True; ``open_unrealized`` =
    realized False / gross=cost=net=None / unfilled_cash False; a closed outcome = realized True / unfilled_cash
    False / finite gross & net / finite NON-NEGATIVE cost / ``net_return == gross_return - cost_fraction``. Raises
    ``PaperLedgerError`` on any violation (the persister never trusts the producer)."""
    if not isinstance(record, dict):
        raise PaperLedgerError("paper_performance record must be a dict")
    as_of = record.get("as_of")
    if not (isinstance(as_of, str) and _strict_yyyymmdd(as_of)):
        raise PaperLedgerError("paper_performance as_of must be a strict real YYYYMMDD, got %r" % (as_of,))
    entries = record.get("entries")
    if not isinstance(entries, list):
        raise PaperLedgerError("paper_performance entries must be a list, got %r" % (type(entries).__name__,))
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise PaperLedgerError("paper_performance entry %d must be a dict, got %r" % (i, type(e).__name__))
        if set(e) != _ENTRY_KEYS:
            raise PaperLedgerError("paper_performance entry %d must carry EXACTLY %s, got %s" % (i, sorted(_ENTRY_KEYS), sorted(map(str, e))))
        outcome, r, g, c, n, u = e["outcome"], e["realized"], e["gross_return"], e["cost_fraction"], e["net_return"], e["unfilled_cash"]
        if outcome not in _OUTCOMES:
            raise PaperLedgerError("paper_performance entry %d outcome %r not in %s" % (i, outcome, list(_OUTCOMES)))
        # full per-outcome net-result invariant (the persister enforces the EXACT paper_net_result contract)
        if outcome == "cash_unfilled":
            if not (r is True and u is True and _finite(g) and g == 0.0 and _finite(c) and c == 0.0 and _finite(n) and n == 0.0):
                raise PaperLedgerError("paper_performance entry %d cash_unfilled must be realized=True / gross=cost=net=0.0 / unfilled_cash=True, got %r" % (i, e))
        elif outcome == "open_unrealized":
            if not (r is False and u is False and g is None and c is None and n is None):
                raise PaperLedgerError("paper_performance entry %d open_unrealized must be realized=False / gross=cost=net=None / unfilled_cash=False, got %r" % (i, e))
        else:  # filled_stopped / filled_tp_exit
            if not (r is True and u is False and _finite(g) and _finite(c) and c >= 0 and _finite(n)):
                raise PaperLedgerError("paper_performance entry %d %s must be realized=True / unfilled_cash=False / finite gross & net / finite non-negative cost, got %r" % (i, outcome, e))
            if not math.isclose(n, g - c, abs_tol=_CLOSE_TOL):
                raise PaperLedgerError("paper_performance entry %d %s net_return %r != gross_return - cost_fraction (%r - %r)" % (i, outcome, n, g, c))


def write_paper_performance(record, out_path):
    """Persist a §12.1 paper_performance record to a gitignored private path. Returns the written ``Path``.

    The §18.0 P0 fail-closed private-path guard runs BEFORE any validate / write (the record carries $ / position /
    net-return detail), so a relative / non-gitignored in-repo destination is refused (``PrivatePathError``). The
    record's full per-entry shape + net-result consistency is then validated, so a malformed / inconsistent ledger
    is refused before any file side effect. Pass ``PAPER_PERFORMANCE_PATH`` (canonical) or an external absolute path."""
    reject_nonprivate_output_path(out_path)  # §18.0 P0 guard — before validate / write / any side effect
    _validate_record(record)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return out_path


def load_paper_performance(in_path) -> dict:
    """Load + re-validate a persisted paper_performance record. Returns the record dict.

    SYMMETRIC with the persister: the §18.0 P0 guard runs FIRST on ``in_path`` (a private artifact is read only
    from a provably-private source — a relative / non-gitignored in-repo source is refused before any read), then
    the record is re-validated (never consume a garbage / inconsistent ledger). Raises ``PaperLedgerError`` if the
    file is missing / unreadable / not valid JSON, or the content fails the §12.1 record contract."""
    reject_nonprivate_output_path(in_path)  # §18.0 P0 guard — symmetric: read a private artifact ONLY from a provably-private source
    in_path = Path(in_path)
    try:
        raw = in_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as e:
        raise PaperLedgerError("paper_performance artifact unreadable at %s: %s" % (in_path, e))
    try:
        record = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        raise PaperLedgerError("paper_performance artifact at %s is not valid JSON: %s" % (in_path, e))
    _validate_record(record)
    return record
