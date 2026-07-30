"""Exact tracked-output path policy for the US-short query-quality probe.

The Web/X discovery and raw paths remain owned by their runner modules.  The
offline post-run assessor consumes this helper at preflight and immediately
before immutable publication, so no provider runner or operator command can
choose a second tracked assessment slot.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"


class QueryQualityProbePathError(ValueError):
    """A probe path is malformed or is not its exact decision-date slot."""


def _decision_date(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{8}", value) is None:
        raise QueryQualityProbePathError("expected_decision_date must be YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise QueryQualityProbePathError("expected_decision_date must be a real date") from exc
    return value


def default_assessment_path(expected_decision_date: str) -> Path:
    decision_date = _decision_date(expected_decision_date)
    return DOCS_DIR / f"us_short_soft_discovery_query_quality_probe_assessment_{decision_date}.json"


def validate_assessment_path(path: Path | str, expected_decision_date: str) -> Path:
    expected = default_assessment_path(expected_decision_date)
    if DOCS_DIR.is_symlink() or expected.is_symlink():
        raise QueryQualityProbePathError("assessment output slot must not be a symlink")
    try:
        expected.relative_to(ROOT)
    except ValueError as exc:
        raise QueryQualityProbePathError("assessment output slot must stay under the repository root") from exc

    candidate = Path(path)
    if candidate.is_absolute():
        lexical_candidate = candidate
    else:
        lexical_candidate = ROOT / candidate
    if lexical_candidate != expected:
        raise QueryQualityProbePathError(
            f"assessment output must use the exact decision-date slot: {expected.name}"
        )
    resolved = lexical_candidate.resolve()
    if resolved != expected.resolve():
        raise QueryQualityProbePathError("assessment output slot must not escape through a symlink")
    return resolved
