from __future__ import annotations

import json
from pathlib import Path

from engine.us_short_projection_binding import build_projection_binding


ROOT = Path(__file__).resolve().parents[2]


def bound_projection(
    *,
    candidate_path: Path,
    component: str,
    projection: dict,
    producer_id: str = "us_short_batch5_full_candidate_projection_inputs",
    source_roles: tuple[str, ...] | None = None,
) -> dict:
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    result = dict(projection)
    roles = source_roles or ("candidate_artifact", f"source_{component}_projection")
    result["source_binding"] = build_projection_binding(
        component=component,
        producer_id=producer_id,
        generated_at="2026-06-15T12:00:00+00:00",
        expected_decision_date=candidate["decision_date"],
        candidate_price_basis_date=candidate["price_basis_date"],
        source_as_of=(
            f"{candidate['price_basis_date'][:4]}-{candidate['price_basis_date'][4:6]}-"
            f"{candidate['price_basis_date'][6:]}"
        ),
        target_tickers=list(result.get("coverage", {})),
        projection=result,
        source_artifact_paths={role: candidate_path for role in roles},
    )
    return result
