# -*- coding: utf-8 -*-
"""US-short ship-gate sizing / live permission (§8 ship-gate sizing) — advisory size + real-money gate.

Design authority: docs/us_short_system_design.md §8 (line 233 sizing + line 234 hard-veto) and §12 /
docs/evidence_capital_policy.md; frozen field set + live_permission vocab + safety invariants in
presets/us_short_ship_gate_sizing_governance_20260620.json (LOADED here).

The system emits a NORMAL-basis `model_position_size_amount` / `model_position_size_shares` plus a
`live_permission_status` ∈ {paper_or_minimal_only, not_full_size_eligible, full_size_eligible} and a
`live_size_warning`. The load-bearing safety rules: maturity is a **REMINDER, not a sizing cap** (the model
size is passed through UNCHANGED — permission/warning never shrink it); an un-graduated / paper-only /
not-evaluable track is **NEVER a real-money full-size license** (paper evidence can never be full_size, §12);
the real-money amount is set MANUALLY by the human (the system only advises); and a **hard veto = 0 position**
(overrides any sizing). Graduation/maturity thresholds are §13.1 #12 forward priors — they are NOT computed
here; the graduation decision is an INPUT, and this engine only enforces the safety gate. Every public input
is fail-closed (whole-class). Pure/offline; no provider, no broker/auto-order, no A-share crossing.
"""
import json
import math
from pathlib import Path

_GOV_PATH = Path(__file__).resolve().parent.parent / "presets" / "us_short_ship_gate_sizing_governance_20260620.json"
_GOV = json.loads(_GOV_PATH.read_text(encoding="utf-8"))

SIZING_FIELDS = tuple(_GOV["sizing_fields"])
LIVE_PERMISSION_VOCAB = tuple(_GOV["live_permission_status_vocab"])   # paper_or_minimal_only / not_full_size_eligible / full_size_eligible
EVIDENCE_LEVELS = ("not_evaluable", "paper", "live_normalized")       # input domain (§12 / evidence_capital_policy)

# Load-bearing §8 safety invariants — fail loud at import if the governance preset ever drifts them off.
for _flag in ("maturity_is_reminder_not_cap", "ungraduated_not_full_size_license",
              "real_money_amount_manual", "hard_veto_zero_position"):
    if _GOV.get(_flag) is not True:
        raise ValueError(f"ship_gate governance safety invariant {_flag!r} is not pinned true")

_PERMISSION_WARNING = {
    "paper_or_minimal_only": "paper_or_minimal_only_not_full_size_license",
    "not_full_size_eligible": "live_track_not_graduated_not_full_size",
}


def _finite_number(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def _nonneg_int(x):
    """A non-negative integer share count (0 = no position is legal here). Fractional / bool / string /
    negative / NaN → None."""
    if isinstance(x, bool) or not isinstance(x, int):
        return None
    return x if x >= 0 else None


def classify_live_permission(hard_veto, evidence_level, graduated_full_size=False):
    """§8 live_permission_status. A hard veto → `paper_or_minimal_only` (0 position, certainly no real-money
    full size). Paper-only / not-evaluable / unknown-or-malformed evidence → `paper_or_minimal_only` (paper
    evidence can NEVER be full size, §12). A live_normalized track → `full_size_eligible` ONLY if
    `graduated_full_size` is exactly True, else `not_full_size_eligible`. Never auto-grants full size on an
    un-graduated track."""
    if hard_veto is True:
        return "paper_or_minimal_only"
    ev = evidence_level if evidence_level in EVIDENCE_LEVELS else "not_evaluable"   # fail closed
    if ev != "live_normalized":
        return "paper_or_minimal_only"
    return "full_size_eligible" if graduated_full_size is True else "not_full_size_eligible"


def ship_gate_sizing(model_position_size_amount, model_position_size_shares, hard_veto=False,
                     evidence_level="paper", graduated_full_size=False):
    """§8 ship-gate sizing. Returns the 4 frozen `sizing_fields`: {model_position_size_amount,
    model_position_size_shares, live_permission_status, live_size_warning}. A hard veto zeroes the position
    (`hard_veto_zero_position`). Otherwise the model size is passed through UNCHANGED (maturity is a reminder,
    NOT a cap) and only `live_permission_status` + `live_size_warning` reflect graduation; a malformed model
    size fails closed to a zero position + `paper_or_minimal_only`. The real-money amount is the human's to
    set — this is advisory."""
    permission = classify_live_permission(hard_veto, evidence_level, graduated_full_size)
    if hard_veto is True:
        return _result(0.0, 0, "paper_or_minimal_only", "hard_veto_zero_position")
    amount = _finite_number(model_position_size_amount)
    shares = _nonneg_int(model_position_size_shares)
    if amount is None or amount < 0.0 or shares is None:
        return _result(0.0, 0, "paper_or_minimal_only", "malformed_model_size")   # fail closed
    warning = None if permission == "full_size_eligible" else _PERMISSION_WARNING[permission]
    return _result(amount, shares, permission, warning)


def _result(amount, shares, permission, warning):
    return {"model_position_size_amount": amount, "model_position_size_shares": shares,
            "live_permission_status": permission, "live_size_warning": warning}
