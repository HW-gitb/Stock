# -*- coding: utf-8 -*-
"""US-short core_score assembly (§4.2) — the 40/35/25 momentum/theme/catalyst weighted sum − risk_downgrade.

Design authority: docs/us_short_system_design.md §4.2; the named weight profiles are frozen in
presets/us_short_scoring_profile_governance_20260620.json (LOADED here — single source).

core_score = Σ weight[c] × block[c] (over momentum / theme / catalyst) − risk_downgrade. The weight
profile is named (`balanced` 40/35/25 = the v1 primary / live model_paper track; `theme_plus` /
`theme_aggressive` / `theme_off` = shadow comparison only). A missing or malformed block scores a
NEUTRAL value and is flagged — the present blocks' weights are NOT re-normalised, so a missing block
can never silently amplify the others (§4.2 "不偷偷重新归一放大权重"). The 35%-block input is the theme
block AFTER the cross-sectional industry⊥theme orthogonalization (防双重计数), which is a separate pool-
level concern and NOT computed here — this engine consumes the already-combined block value.

Weights are frozen const (the design value); the neutral block value is a §13 forward prior. Every
public input is validated fail-closed (whole-class): block / risk_downgrade values use a strict
`_finite_number` (rejects bool AND numeric string), an unknown profile raises (no silent default).
`profile_weights` returns a COPY so a consumer can't mutate the frozen table. Pure/offline; no
provider, no A-share crossing; §8 sizing / §9 action_rank consume the score + rank.
"""
import json
import math
from pathlib import Path

_GOV_PATH = Path(__file__).resolve().parent.parent / "presets" / "us_short_scoring_profile_governance_20260620.json"
_GOV = json.loads(_GOV_PATH.read_text(encoding="utf-8"))

CORE_COMPONENTS = tuple(_GOV["core_score_components"])     # ("momentum", "theme", "catalyst")
_PROFILES = _GOV["profiles"]                              # frozen named weight profiles
PRIMARY_PROFILE = _GOV["primary_profile"]                 # "balanced"
PROFILE_NAMES = tuple(_PROFILES)
NEUTRAL_BLOCK = 50.0   # §13 forward prior: a missing block scores neutral (mid of the 0-100 range)
_BLOCK_MIN, _BLOCK_MAX = 0.0, 100.0


def _finite_number(x):
    """A strictly-typed finite number (int/float, NOT bool, NOT a numeric string); else None — so a
    malformed block / risk_downgrade can't be parsed into a live score value."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def profile_weights(profile=PRIMARY_PROFILE):
    """Frozen §4.2 component weights for a named scoring_profile, returned as a COPY (a consumer can't
    mutate the single-source governance table). Raises KeyError on an unknown profile (fail closed)."""
    return dict(_PROFILES[profile]["weights"])


def core_score(blocks, profile=PRIMARY_PROFILE, risk_downgrade_points=0.0, neutral_block=NEUTRAL_BLOCK):
    """§4.2 core_score = Σ weight[c] × block[c] − risk_downgrade, over momentum / theme / catalyst.

    `blocks` = {component: 0-100 value}; a missing or malformed (non-number / bool / NaN) block scores
    `neutral_block` and is listed in `missing_blocks` — the present blocks' weights are NOT
    re-normalised. A real block is clamped to 0-100. A malformed `risk_downgrade_points` fails closed
    to 0; the final score is clamped >= 0 (never negative). Returns {core_score, profile, weights,
    blocks_used, missing_blocks, risk_downgrade}. Raises KeyError on an unknown profile (fail closed)."""
    w = profile_weights(profile)                          # raises on an unknown profile
    nb = _finite_number(neutral_block)                    # the neutral fallback is a public input too:
    if nb is None or not (_BLOCK_MIN <= nb <= _BLOCK_MAX):  # malformed / NaN / Inf / out-of-domain override
        nb = NEUTRAL_BLOCK                                # → fail closed to the frozen default (no crash / inflation)
    blocks = blocks if isinstance(blocks, dict) else {}
    used, missing = {}, []
    for c in CORE_COMPONENTS:
        v = _finite_number(blocks.get(c))
        if v is None:
            used[c] = nb
            missing.append(c)
        else:
            used[c] = max(_BLOCK_MIN, min(_BLOCK_MAX, v))  # clamp a real block to 0-100
    rdv = _finite_number(risk_downgrade_points)
    rd = max(0.0, rdv) if rdv is not None else 0.0        # malformed / negative risk_downgrade → 0
    raw = sum(w[c] * used[c] for c in CORE_COMPONENTS)
    return {"core_score": max(0.0, raw - rd), "profile": profile, "weights": w,
            "blocks_used": used, "missing_blocks": missing, "risk_downgrade": rd}
