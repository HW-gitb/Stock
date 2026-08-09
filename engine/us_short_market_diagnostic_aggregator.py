"""US-short 26-week market-diagnostic Knife 4 aggregation and publication.

Knife 4 consumes only the already-settled, private weekly records from Knife 3.
It publishes a deterministic, de-identified report only when a canonical 26-week
boundary closes.  It never reads a provider, account, order, or selection store.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import uuid
from typing import Any, Mapping

import jsonschema
from referencing import Registry, Resource

from engine.us_short_market_diagnostic import (
    BENCHMARKS,
    BOUNDARY,
    MarketDiagnosticError,
    STATUS_REASONS,
    segment_epoch_and_ruleset,
    summarize_since_inception,
    summarize_window,
    window_for_week,
)
from engine.us_short_market_diagnostic_lifecycle import (
    DEFAULT_ROOT as DEFAULT_LIFECYCLE_ROOT,
    MarketDiagnosticLifecycleError,
    load_settled_weekly_records,
)
from engine.us_short_market_diagnostic_start_receipt import DiagnosticStartReceiptError
from engine.us_short_model_paper_portfolio import canonical_json_bytes


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PUBLIC_ROOT = ROOT / "research" / "results" / "us_short" / "market_diagnostic_26w"
REPORT_SCHEMA_PATH = ROOT / "schemas" / "us_short_market_diagnostic_report.schema.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_market_diagnostic_summary.schema.json"
WINDOW_ID_PATTERN = re.compile(r"^26w-[1-9][0-9]*-[1-9][0-9]*$")
PUBLIC_REMINDER_TEXT = {
    "pending": "v1.1 attribution is system-derived and waits for four consecutive paper-evaluable weeks.",
    "ready_for_v1_1_implementation": "v1.1 attribution is system-derived and waits for four consecutive paper-evaluable weeks.",
    "overdue": "v1.1 attribution is system-derived and waits for four consecutive paper-evaluable weeks.",
    "active": "v1.1 attribution is active and remains sticky after automatic activation.",
}
PUBLIC_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
REPORT_BOUNDARY = dict(BOUNDARY)


class MarketDiagnosticAggregationError(RuntimeError):
    """Raised when a completed diagnostic window cannot be safely aggregated or published."""


def _load_schema(path: Path) -> dict[str, Any]:
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        jsonschema.Draft7Validator.check_schema(schema)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, jsonschema.exceptions.SchemaError) as exc:
        raise MarketDiagnosticAggregationError(f"cannot load diagnostic report schema: {path}") from exc
    return schema


def _validate_report(report: Mapping[str, Any]) -> None:
    if not isinstance(report, Mapping):
        raise MarketDiagnosticAggregationError("diagnostic report must be an object")
    _validate_public_summary(report.get("window_summary"), require_reminder=True)
    _validate_public_summary(report.get("since_inception"), require_reminder=False)
    summary_schema = _load_schema(SUMMARY_SCHEMA_PATH)
    summary_errors = sorted(
        jsonschema.Draft7Validator(summary_schema).iter_errors(report.get("window_summary")),
        key=lambda error: list(error.absolute_path),
    )
    if summary_errors:
        error = summary_errors[0]
        raise MarketDiagnosticAggregationError(f"window summary schema violation: {error.message}")

    report_schema = _load_schema(REPORT_SCHEMA_PATH)
    summary_id = summary_schema.get("$id", "us_short_market_diagnostic_summary.schema.json")
    registry = Registry().with_resources(
        [
            (report_schema["$id"], Resource.from_contents(report_schema)),
            (summary_id, Resource.from_contents(summary_schema)),
            ("us_short_market_diagnostic_summary.schema.json", Resource.from_contents(summary_schema)),
        ]
    )
    errors = sorted(
        jsonschema.Draft7Validator(report_schema, registry=registry).iter_errors(report),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise MarketDiagnosticAggregationError(f"diagnostic report schema violation at {location}: {error.message}")


def _validate_public_summary(summary: object, *, require_reminder: bool) -> None:
    if not isinstance(summary, Mapping):
        return
    reason = summary.get("status_reason")
    if reason not in STATUS_REASONS:
        raise MarketDiagnosticAggregationError("public diagnostic status_reason is not a machine reason")
    epoch = summary.get("diagnostic_epoch")
    if not isinstance(epoch, str) or PUBLIC_IDENTIFIER.fullmatch(epoch) is None:
        raise MarketDiagnosticAggregationError("public diagnostic diagnostic_epoch is not a safe identifier")
    if not require_reminder:
        return
    reminder = summary.get("v1_1_reminder")
    if not isinstance(reminder, Mapping):
        raise MarketDiagnosticAggregationError("public diagnostic reminder is not an object")
    status = reminder.get("status")
    if status not in PUBLIC_REMINDER_TEXT or reminder.get("text") != PUBLIC_REMINDER_TEXT[status]:
        raise MarketDiagnosticAggregationError("public diagnostic reminder contains non-canonical text")


def _publicize_window_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    public = dict(summary)
    reminder = dict(summary["v1_1_reminder"])
    status = reminder["status"]
    if status not in PUBLIC_REMINDER_TEXT:
        raise MarketDiagnosticAggregationError("diagnostic reminder status is unknown")
    reminder["text"] = PUBLIC_REMINDER_TEXT[status]
    public["v1_1_reminder"] = reminder
    return public


def _authorized_records(
    lifecycle_root: str | Path, *, as_of_date: str | None = None
) -> list[dict[str, Any]]:
    """The only way weeks enter a verdict: fetched from the store, through the gate.

    Returning the records rather than returning ``None`` is the point. A guard that
    merely asserts and hands control back invites the caller to summarise something
    else; a guard that *supplies* the data leaves nothing else to summarise.
    """

    try:
        records = load_settled_weekly_records(lifecycle_root, as_of_date=as_of_date)
    except (MarketDiagnosticLifecycleError, DiagnosticStartReceiptError) as exc:
        raise MarketDiagnosticAggregationError(
            f"the diagnostic clock is not authorized, so no verdict may be produced: {exc}"
        ) from exc
    if not records:
        raise MarketDiagnosticAggregationError("the authorized diagnostic store holds no settled weeks")
    return records


def _report_output_paths(window_id: str, output_root: str | Path) -> tuple[Path, Path]:
    if not isinstance(window_id, str) or WINDOW_ID_PATTERN.fullmatch(window_id) is None:
        raise MarketDiagnosticAggregationError("report window_id is not a canonical 26-week id")
    root = Path(output_root)
    if not root.is_absolute():
        raise MarketDiagnosticAggregationError("public diagnostic output root must be absolute")
    root = root.resolve()
    json_path = (root / f"{window_id}.json").resolve()
    markdown_path = (root / f"{window_id}.md").resolve()
    if json_path.parent != root or markdown_path.parent != root:
        raise MarketDiagnosticAggregationError("diagnostic report path escaped its output root")
    return json_path, markdown_path


def build_market_diagnostic_report(
    *, lifecycle_root: str | Path, as_of_date: str | None = None
) -> dict[str, Any] | None:
    """Build the next report, or return ``None`` until a canonical boundary closes.

    There is deliberately no ``records`` parameter. An earlier version took the
    records and the store as independent arguments and checked the store — which
    proved that *a* clock was authorized while saying nothing about the history
    being published, so a fabricated 26 weeks published against a store holding
    one. The summarised weeks are now fetched here, through the gated loader, so
    publishing a history the store does not contain is not something this API can
    express.
    """

    normalized = _authorized_records(lifecycle_root, as_of_date=as_of_date)
    try:
        since_inception = summarize_since_inception(normalized, as_of_date=as_of_date)
    except MarketDiagnosticError as exc:
        raise MarketDiagnosticAggregationError(f"since-inception validation failed: {exc}") from exc
    boundary = window_for_week(since_inception["through_calendar_week"])
    if boundary is None:
        return None

    start = boundary["window_start_week"]
    end = boundary["window_end_week"]
    block_rows = normalized[start - 1 : end]
    if len(block_rows) != boundary["calendar_weeks"]:
        raise MarketDiagnosticAggregationError("completed diagnostic window does not have 26 settled records")
    try:
        window_summary = _publicize_window_summary(
            summarize_window(block_rows, as_of_date=as_of_date)
        )
    except MarketDiagnosticError as exc:
        raise MarketDiagnosticAggregationError(f"fixed-window validation failed: {exc}") from exc

    report = {
        "schema_name": "us_short_market_diagnostic_report",
        "schema_version": "1.0.0",
        "window_summary": window_summary,
        "since_inception": since_inception,
        "ruleset_segments": {
            "fixed_window": segment_epoch_and_ruleset(block_rows),
            "since_inception": segment_epoch_and_ruleset(normalized),
        },
        "boundary": dict(REPORT_BOUNDARY),
    }
    _validate_report(report)
    return report


def _number(value: Any) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _summary_lines(label: str, summary: Mapping[str, Any]) -> list[str]:
    strategy = summary["strategy"]
    lines = [
        f"## {label}",
        f"- 状态：`{summary['overall_status']}`（{summary['status_reason']}）",
        f"- 策略累计收益：`{_number(strategy['cumulative_return'])}`；最大回撤：`{_number(strategy['max_drawdown'])}`",
        f"- 策略可评估周：`{strategy['strategy_evaluable_weeks']}`；数据覆盖率：`{_number(strategy['data_coverage'])}`",
        "",
        "| 基准 | 状态 | 累计收益 | 相对财富 | raw excess | joint 周 | 数据覆盖率 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for symbol in BENCHMARKS:
        benchmark = summary["benchmarks"][symbol]
        lines.append(
            f"| {symbol} | `{benchmark['status']}` | `{_number(benchmark['cumulative_return'])}` | "
            f"`{_number(benchmark['relative_wealth'])}` | `{_number(benchmark['raw_excess'])}` | "
            f"`{benchmark['joint_evaluable_weeks']}` | `{_number(benchmark['data_coverage'])}` |"
        )
    return lines


def render_market_diagnostic_markdown(report: Mapping[str, Any]) -> str:
    """Render only the de-identified report fields; never render weekly records."""

    _validate_report(report)
    window = report["window_summary"]
    since = report["since_inception"]
    lines = [
        "# US-short 26 周市场表现诊断",
        "",
        f"- 当前区块：`{window['window_id']}`（第 `{window['window_start_week']}`—`{window['window_end_week']}` 周）",
        f"- 诊断 epoch：`{window['diagnostic_epoch']}`",
        "- 边界：仅作比较诊断，不改变选股、操作建议、仓位或 NAV，不计入 Ship gate。",
        "",
    ]
    lines.extend(_summary_lines("当前 26 周区块", window))
    lines.extend(
        [
            "",
            "## Since-inception",
            f"- 已累计日历周：`{since['calendar_week_count']}`；截至第 `{since['through_calendar_week']}` 周。",
        ]
    )
    lines.extend(_summary_lines("Since-inception 表现", since))
    lines.extend(
        [
            "",
            "## Ruleset 分段",
            "",
            "| 范围 | fingerprint | 日历周 | 可评估周 |",
            "|---|---|---:|---:|",
        ]
    )
    for scope, label in (("fixed_window", "当前区块"), ("since_inception", "Since-inception")):
        for segment in report["ruleset_segments"][scope]:
            lines.append(
                f"| {label} `{segment['start_week']}—{segment['end_week']}` | "
                f"`{segment['strategy_ruleset_fingerprint']}` | `{segment['calendar_weeks']}` | "
                f"`{segment['strategy_evaluable_weeks']}` |"
            )
    lines.extend(["", "> 这是事实记录，不是 alpha 认证，也不是自动操作信号。", ""])
    return "\n".join(lines)


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise MarketDiagnosticAggregationError(f"cannot write diagnostic report: {path}") from exc
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def write_market_diagnostic_report(
    *,
    lifecycle_root: str | Path,
    output_root: str | Path = DEFAULT_PUBLIC_ROOT,
    as_of_date: str | None = None,
) -> str:
    """Write one JSON/Markdown pair; identical reruns are idempotent and conflicts fail closed.

    Like the builder, this takes no caller-supplied report. Publication is
    write-once per window, so a report accepted from a caller could pre-empt the
    genuine one permanently; deriving it here from the authorized store removes
    the opportunity rather than checking for it.
    """

    report = build_market_diagnostic_report(
        lifecycle_root=lifecycle_root, as_of_date=as_of_date
    )
    if report is None:
        raise MarketDiagnosticAggregationError("no canonical diagnostic window has closed yet")
    _validate_report(report)
    window_id = report["window_summary"]["window_id"]
    json_path, markdown_path = _report_output_paths(window_id, output_root)
    try:
        json_payload = canonical_json_bytes(report)
    except (ValueError, TypeError, OverflowError) as exc:
        raise MarketDiagnosticAggregationError(
            "diagnostic report cannot be canonicalized"
        ) from exc
    markdown_payload = render_market_diagnostic_markdown(report).encode("utf-8")
    existing_json = json_path.read_bytes() if json_path.is_file() else None
    existing_markdown = markdown_path.read_bytes() if markdown_path.is_file() else None
    if (existing_json is None) != (existing_markdown is None):
        raise MarketDiagnosticAggregationError("diagnostic report pair is incomplete; refusing partial repair")
    if existing_json is not None and existing_markdown is not None:
        if existing_json == json_payload and existing_markdown == markdown_payload:
            return "idempotent"
        raise MarketDiagnosticAggregationError("diagnostic report conflicts with an existing immutable window")
    _write_bytes(json_path, json_payload)
    try:
        _write_bytes(markdown_path, markdown_payload)
    except MarketDiagnosticAggregationError:
        try:
            json_path.unlink()
        except OSError:
            pass
        raise
    return "published"


def publish_completed_market_diagnostic_window(
    *,
    lifecycle_root: str | Path = DEFAULT_LIFECYCLE_ROOT,
    output_root: str | Path = DEFAULT_PUBLIC_ROOT,
    as_of_date: str | None,
) -> dict[str, Any]:
    """Load the private lifecycle and publish only when its last week closes a window.

    ``as_of_date`` is required for the reason given on ``validate_window``: a
    default of ``None`` disabled the look-ahead gate for the one entry that
    actually publishes.
    """

    lifecycle_path = Path(lifecycle_root)
    if lifecycle_path.is_absolute() and not lifecycle_path.exists():
        return {"status": "not_started"}
    report = build_market_diagnostic_report(lifecycle_root=lifecycle_root, as_of_date=as_of_date)
    if report is None:
        records = _authorized_records(lifecycle_root, as_of_date=as_of_date)
        return {
            "status": "not_ready",
            "last_calendar_week_index": records[-1]["calendar_week_index"],
        }
    status = write_market_diagnostic_report(
        lifecycle_root=lifecycle_root, output_root=output_root, as_of_date=as_of_date
    )
    # Both fields come out of the same derivation, so this result cannot report a
    # window from one read of the store and a week count from another.
    return {
        "status": status,
        "window_id": report["window_summary"]["window_id"],
        "last_calendar_week_index": report["since_inception"]["through_calendar_week"],
    }


__all__ = [
    "DEFAULT_LIFECYCLE_ROOT",
    "DEFAULT_PUBLIC_ROOT",
    "MarketDiagnosticAggregationError",
    "build_market_diagnostic_report",
    "publish_completed_market_diagnostic_window",
    "render_market_diagnostic_markdown",
    "write_market_diagnostic_report",
]
