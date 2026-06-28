# -*- coding: utf-8 -*-
"""US-short action_table.csv renderer (batch-3 R2a; design §11.1 / §11.3).

Renders the §11.3 frozen 51-column action_table.csv FROM a machine record (design §11.1:
"周报/csv 从机器层渲染、validator 在机器层焊死"). The column SET + ORDER come from the frozen
`us_short_action_table_contract` (single source — no hardcoded copy), so the CSV can never drift from
the contract. The renderer:

  * refuses to render a machine record the §10 no-dangling validator does not mark clean — the renderer
    consumes ONLY a validated machine layer (a not-clean record raises, it is never half-rendered);
  * is the FIRST batch-3 PERSISTER, so `write_action_table` wires the §18.0 P0 fail-closed private-path
    guard (`engine/us_short_private_paths`) BEFORE writing — action_table.csv carries tickers / entry /
    stop / size and must land only on a provably-gitignored private path (or outside the repo).

Pure / offline: renders + writes a CSV, performs no provider/live/DataHub call; no A-share crossing.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from engine.us_short_no_dangling_validator import validate_official_machine_record
from engine.us_short_private_paths import reject_nonprivate_output_path

ROOT = Path(__file__).resolve().parent.parent
_ACTION_TABLE_PRESET = ROOT / "presets" / "us_short_action_table_contract_20260620.json"

_COLUMNS_CACHE: list = []


class NotCleanMachineRecordError(ValueError):
    """Raised when the renderer is asked to render a machine record the §10 validator rejects."""


def action_table_columns() -> list:
    """The frozen §11.3 column set + order, read from us_short_action_table_contract (single source)."""
    if not _COLUMNS_CACHE:
        contract = json.loads(_ACTION_TABLE_PRESET.read_text(encoding="utf-8"))
        _COLUMNS_CACHE.extend(contract["core_columns"])
    return list(_COLUMNS_CACHE)


def _cell(v) -> str:
    """Render one machine value into a CSV cell. None -> empty; list -> ';'-joined; dict -> compact JSON."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return ";".join(_cell(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return str(v)


def render_action_table(machine_record) -> dict:
    """Return ``{'columns': [...51...], 'rows': [[cell, ...], ...]}`` for the frozen action_table.csv.

    The machine record MUST be §10-clean: the §10 no-dangling validator ALWAYS runs — there is NO opt-out,
    the clean gate is welded at the machine layer (design §11.1) — and a not-clean record raises
    ``NotCleanMachineRecordError`` (the renderer never emits a CSV from an unvalidated machine layer). Each
    row renders the 51 frozen columns in exact contract order; a column the machine row omits → empty cell.
    """
    result = validate_official_machine_record(machine_record)
    if not result["clean"]:
        raise NotCleanMachineRecordError(
            "refusing to render a not-clean machine record; first violations: %s"
            % (result["violations"][:5],)
        )
    columns = action_table_columns()
    rows = machine_record.get("rows", []) if isinstance(machine_record, dict) else []
    out_rows = [
        [_cell(r.get(c)) if isinstance(r, dict) else "" for c in columns]
        for r in rows
    ]
    return {"columns": columns, "rows": out_rows}


def write_action_table(machine_record, out_path):
    """Render + write action_table.csv to ``out_path``.

    FIRST batch-3 persister: the §18.0 P0 fail-closed private-path guard runs BEFORE any rendering/writing,
    so a relative / non-gitignored in-repo destination is refused (action_table.csv carries tickers/levels).
    Returns the written path.
    """
    reject_nonprivate_output_path(out_path)        # §18.0 P0 guard — before validate / render / write
    table = render_action_table(machine_record)    # validates; refuses a not-clean record (before any dir/file side effect)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)  # the <决策日> private dir may not exist yet (only after render passes)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(table["columns"])
        writer.writerows(table["rows"])
    return out_path
