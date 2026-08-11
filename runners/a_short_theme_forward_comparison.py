"""Generate the A-short industry/theme forward comparison packet from the local tracker."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_theme_forward_comparison import (
    EPOCH_PATH, TRACK_ID, admission_receipt_manifest, build_cohort_admission_receipt,
    build_formal_decision_receipt, build_frozen_epoch, build_terminal_outcome_receipt,
    evaluate_theme_forward_comparison, eligible_formal_cohorts, load_epoch, load_governance,
    outcome_receipt_manifest, validate_cohort_admission_receipt, validate_comparison_packet,
    validate_terminal_outcome_receipt,
    validate_tracker_lineage, _weekly_latest_as_ofs,
)
from engine import a_short_evidence_epoch_mode as epoch_mode
from engine.a_short_run_revision import (
    private_revision_root,
    require_official_revision,
    resolve_official_revision,
    validate_run_revision_id,
)


DEFAULT_TRACKER = ROOT / "logs" / "forward_tracker.csv"
DEFAULT_OUTPUT = ROOT / "research" / "results" / "a_short_theme_forward_comparison.json"
EPOCH_ARCHIVE_DIR = ROOT / "docs" / "a_short_theme_forward_comparison_epochs"
DEFAULT_PRIVATE_ROOT = ROOT / "state" / "a_short" / "theme_forward_comparison_private" / "v1"
TRACKER_STRING_COLUMNS = {
    "as_of": str, "decision_as_of": str, "run_date": str,
    "price_data_through": str, "industry_trend_source_as_of": str,
    "theme_taxonomy_source_as_of": str, "theme_taxonomy_l3_snapshot_date": str,
    "entry_date": str, "ret_10d_exit_date": str, "ts_code": str,
}


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _json_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_json_exclusive(path: Path, payload: dict) -> None:
    """Create an immutable receipt; a pre-existing target is never overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_json_exclusive_idempotent(path: Path, payload: dict) -> bool:
    """Create an immutable artifact, or resume only when its exact bytes already exist."""
    expected = _json_bytes(payload)
    try:
        _write_json_exclusive(path, payload)
        return True
    except FileExistsError:
        try:
            actual = path.read_bytes()
        except OSError as exc:
            raise SystemExit(f"[FATAL] cannot verify existing immutable artifact: {path}") from exc
        if actual != expected:
            raise SystemExit(f"[FATAL] immutable artifact exists with different bytes: {path}")
        return False


def _write_json_atomic_idempotent(path: Path, payload: dict) -> bool:
    """Write a mutable pointer once, or resume only when its exact bytes already exist."""
    expected = _json_bytes(payload)
    if path.exists():
        try:
            actual = path.read_bytes()
        except OSError as exc:
            raise SystemExit(f"[FATAL] cannot verify existing epoch archive: {path}") from exc
        if actual != expected:
            raise SystemExit(f"[FATAL] epoch archive exists with different bytes: {path}")
        return False
    _write_json_atomic(path, payload)
    return True


def _private_root(path: str | Path) -> Path:
    resolved = Path(path).resolve()
    if tuple(part.lower() for part in resolved.parts[-4:]) != (
        "state", "a_short", "theme_forward_comparison_private", "v1",
    ):
        raise SystemExit("[FATAL] private root must end in state/a_short/theme_forward_comparison_private/v1")
    try:
        relative = resolved.relative_to(ROOT)
    except ValueError:
        return resolved
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "-q", "--", str(relative)],
            capture_output=True, text=True, check=False,
        )
    except OSError as exc:
        raise SystemExit("[FATAL] cannot prove theme comparison private root is gitignored") from exc
    if result.returncode != 0:
        raise SystemExit("[FATAL] theme comparison private root is not a provably gitignored path")
    return resolved


def _epoch_private_dir(private_root: Path, epoch: dict) -> Path:
    return private_root / "epochs" / str(epoch["epoch_id"])


def _load_private_receipts(directory: Path, label: str) -> dict[str, dict]:
    receipts: dict[str, dict] = {}
    if not directory.exists():
        return receipts
    for path in sorted(directory.glob("*.json")):
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SystemExit(f"[FATAL] invalid {label} receipt {path}: {exc}") from exc
        as_of = str(receipt.get("as_of") or "")
        if path.stem != as_of or as_of in receipts:
            raise SystemExit(f"[FATAL] duplicate or misnamed {label} receipt: {path}")
        receipts[as_of] = receipt
    return receipts


def _manifest_is_prefix(expected: dict, receipts: dict[str, dict], manifest_builder) -> bool:
    """Allow restart after a receipt write succeeded before the epoch pointer advanced."""
    for count in range(len(receipts) + 1):
        prefix = {key: receipts[key] for key in sorted(receipts)[:count]}
        if manifest_builder(prefix) == expected:
            return True
    return False


def _validate_epoch_packet_binding(epoch: dict) -> dict[str, str] | None:
    """Validate the shared packet identity before any frozen receipt write."""
    if epoch["mode"] != "frozen_enforced":
        return None
    return epoch_mode.validate_bound_frozen_packet_identity(
        TRACK_ID, epoch.get("freeze_packet_identity"),
    )


def _sync_cohort_admission_receipts(
    tracker: pd.DataFrame, epoch: dict, private_root: Path
) -> dict[str, dict]:
    """Seal complete decision-time cohorts before any H10 result is observable."""
    if epoch["mode"] != "frozen_enforced":
        return {}
    _validate_epoch_packet_binding(epoch)
    live = validate_tracker_lineage(tracker)
    live = live[live["as_of"].astype(str) >= str(epoch["epoch_start_as_of"])].copy()
    policy = load_governance()["policy"]
    live, _ = eligible_formal_cohorts(
        live, int(policy["top_n"]), require_decision_effective=False
    )
    admissions_dir = _epoch_private_dir(private_root, epoch) / "admissions"
    receipts = _load_private_receipts(admissions_dir, "cohort admission")
    expected_manifest = epoch["admission_receipt_manifest"]
    current_manifest = admission_receipt_manifest(receipts)
    if current_manifest != expected_manifest:
        if not _manifest_is_prefix(expected_manifest, receipts, admission_receipt_manifest):
            raise SystemExit("[FATAL] cohort admission receipt manifest rolled back or no longer matches")
    weekly_as_ofs = set(_weekly_latest_as_ofs(
        [str(value) for value in live["as_of"]], set(receipts),
    ))
    live = live[live["as_of"].astype(str).isin(weekly_as_ofs)].copy()
    cohorts = {str(as_of): cohort for as_of, cohort in live.groupby("as_of", dropna=False)}
    for as_of, receipt in receipts.items():
        cohort = cohorts.get(as_of)
        if cohort is None:
            raise SystemExit(f"[FATAL] sealed admitted cohort disappeared from tracker: {as_of}")
        try:
            validate_cohort_admission_receipt(receipt, cohort, epoch, int(policy["top_n"]))
        except Exception as exc:
            raise SystemExit(f"[FATAL] cohort admission receipt mismatch for {as_of}: {exc}") from exc
    for as_of, cohort in cohorts.items():
        if as_of in receipts:
            continue
        receipt = build_cohort_admission_receipt(cohort, epoch, int(policy["top_n"]))
        if receipt is None:
            continue
        path = admissions_dir / f"{as_of}.json"
        _write_json_exclusive_idempotent(path, receipt)
        receipts[as_of] = receipt
    new_manifest = admission_receipt_manifest(receipts)
    if new_manifest != epoch["admission_receipt_manifest"]:
        epoch["admission_receipt_manifest"] = new_manifest
        _write_json_atomic(EPOCH_PATH, epoch)
    return receipts


def _sync_terminal_outcome_receipts(
    tracker: pd.DataFrame, epoch: dict, private_root: Path,
    admission_receipts: dict[str, dict],
) -> dict[str, dict]:
    """Seal newly terminal cohorts and fail if any prior seal no longer matches."""
    if epoch["mode"] != "frozen_enforced":
        return {}
    _validate_epoch_packet_binding(epoch)
    live = validate_tracker_lineage(tracker)
    live = live[
        live["as_of"].astype(str) >= str(epoch["epoch_start_as_of"])
    ].copy()
    policy = load_governance()["policy"]
    live, _ = eligible_formal_cohorts(live, int(policy["top_n"]))
    outcomes_dir = _epoch_private_dir(private_root, epoch) / "outcomes"
    receipts = _load_private_receipts(outcomes_dir, "terminal outcome")
    expected_manifest = epoch["outcome_receipt_manifest"]
    current_manifest = outcome_receipt_manifest(receipts)
    if current_manifest != expected_manifest:
        if not _manifest_is_prefix(expected_manifest, receipts, outcome_receipt_manifest):
            raise SystemExit("[FATAL] terminal outcome receipt manifest rolled back or no longer matches")
    weekly_as_ofs = set(_weekly_latest_as_ofs(
        [str(value) for value in live["as_of"]], set(admission_receipts),
    ))
    live = live[live["as_of"].astype(str).isin(weekly_as_ofs)].copy()
    cohorts = {str(as_of): cohort for as_of, cohort in live.groupby("as_of", dropna=False)}
    for as_of, receipt in receipts.items():
        cohort = cohorts.get(as_of)
        if cohort is None:
            raise SystemExit(f"[FATAL] sealed terminal cohort disappeared from tracker: {as_of}")
        try:
            validate_terminal_outcome_receipt(
                receipt, cohort, epoch, int(policy["top_n"]),
                admission_receipt=admission_receipts.get(as_of),
            )
        except Exception as exc:
            raise SystemExit(f"[FATAL] terminal outcome receipt mismatch for {as_of}: {exc}") from exc
    for as_of, cohort in cohorts.items():
        receipt = build_terminal_outcome_receipt(
            cohort, epoch, int(policy["top_n"]),
            admission_receipt=admission_receipts.get(as_of),
        )
        if receipt is None or as_of in receipts:
            continue
        path = outcomes_dir / f"{as_of}.json"
        _write_json_exclusive_idempotent(path, receipt)
        receipts[as_of] = receipt
    new_manifest = outcome_receipt_manifest(receipts)
    if new_manifest != epoch["outcome_receipt_manifest"]:
        epoch["outcome_receipt_manifest"] = new_manifest
        _write_json_atomic(EPOCH_PATH, epoch)
    return receipts


def _load_formal_decision_receipt(epoch: dict, private_root: Path) -> dict | None:
    if epoch["mode"] != "frozen_enforced":
        return None
    path = _epoch_private_dir(private_root, epoch) / "formal_decision.json"
    if not path.exists():
        return None
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"[FATAL] invalid formal decision receipt: {exc}") from exc
    archive_path = (private_root / str(receipt.get("archive_relative_path") or "")).resolve()
    try:
        archive_path.relative_to(private_root)
    except ValueError as exc:
        raise SystemExit("[FATAL] immutable formal packet archive escaped the private root") from exc
    if not archive_path.is_file() or hashlib.sha256(archive_path.read_bytes()).hexdigest() != \
            str(receipt.get("packet_sha256") or ""):
        raise SystemExit("[FATAL] immutable formal packet archive is missing or changed")
    return receipt


def _load_recorded_formal_packet(
    epoch: dict, receipt: dict | None, private_root: Path
) -> dict | None:
    if epoch["mode"] != "frozen_enforced" or epoch["formal_decision"]["status"] != "recorded":
        return None
    if receipt is None:
        raise SystemExit("[FATAL] recorded formal decision has no validated receipt")
    path = (private_root / str(receipt["archive_relative_path"])).resolve()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"[FATAL] immutable formal packet cannot be read: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit("[FATAL] immutable formal packet is not an object")
    return value


def _record_formal_decision_if_due(packet: dict, packet_path: Path, private_root: Path) -> None:
    """Consume the sole 36-week look only after its receipt is durable."""
    if not packet.get("formal_verdict_allowed") or \
            (packet.get("checkpoints") or {}).get("current_checkpoint") != "formal_decision_due":
        return
    epoch = load_epoch()
    decision = epoch["formal_decision"]
    expected_epoch = packet.get("epoch") or {}
    if epoch.get("mode") != "frozen_enforced" or any(
            epoch.get(key) != expected_epoch.get(key)
            for key in (
                "epoch_id", "epoch_start_as_of", "contract_fingerprint",
                "freeze_packet_identity",
            )):
        raise SystemExit("[FATAL] active epoch changed after packet evaluation; refusing to consume a formal look")
    _validate_epoch_packet_binding(epoch)
    if decision["status"] != "not_recorded":
        raise SystemExit("[FATAL] formal theme decision was already recorded for this epoch")
    decision_as_of = str((packet.get("checkpoints") or {}).get("formal_decision_as_of") or "")
    epoch_dir = _epoch_private_dir(private_root, epoch)
    archive_path = epoch_dir / "formal_packet.json"
    archive_relative_path = archive_path.relative_to(private_root).as_posix()
    _write_json_exclusive_idempotent(archive_path, packet)
    packet_sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    receipt = build_formal_decision_receipt(
        epoch, decision_as_of, packet_sha256, archive_relative_path
    )
    receipt_path = epoch_dir / "formal_decision.json"
    _write_json_exclusive_idempotent(receipt_path, receipt)
    epoch["formal_decision"] = {
        "status": "recorded",
        "as_of": decision_as_of,
        "packet_sha256": packet_sha256,
        "archive_relative_path": archive_relative_path,
        "receipt_sha256": receipt["record_sha256"],
    }
    _write_json_atomic(EPOCH_PATH, epoch)


def _start_or_reset_epoch(
    tracker: pd.DataFrame, epoch_id: str, start_as_of: str, private_root: Path,
    *, reset_epoch: bool,
) -> dict:
    """Explicitly open a new track epoch; never repair or reset one implicitly."""
    epoch = load_epoch()
    try:
        registry = json.loads(epoch_mode.TRACK_MODE_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"[FATAL] cannot read epoch mode registry: {exc}") from exc
    if registry.get("schema_name") != "a_short_evidence_epoch_mode_registry" or \
            registry.get("schema_version") != "1.0.0" or \
            set((registry.get("track_modes") or {})) != set(epoch_mode.TRACKS):
        raise SystemExit("[FATAL] invalid epoch mode registry")
    # A CLI request to start an epoch is not itself the design-completion
    # decision. The user must first record that explicit directive in the
    # shared registry; otherwise no durable frozen epoch may be published.
    try:
        epoch_mode.require_design_completion_authorization()
    except epoch_mode.EvidenceEpochModeError as exc:
        raise SystemExit(f"[FATAL] {exc}") from exc
    registry_mode = registry["track_modes"][TRACK_ID]
    epoch_is_frozen = epoch["mode"] == "frozen_enforced"
    if epoch_is_frozen != (registry_mode == "frozen_enforced"):
        if epoch_is_frozen and registry_mode == "pre_freeze_audit_only" and not reset_epoch and \
                epoch.get("epoch_id") == epoch_id and epoch.get("epoch_start_as_of") == start_as_of:
            # The active epoch pointer is the final durable commitment.  A crash
            # immediately before registry publication resumes by publishing only
            # the matching track switch, never by rebuilding evidence.
            packet_identity = epoch_mode.validate_frozen_transition(TRACK_ID)
            if epoch.get("freeze_packet_identity") != packet_identity:
                raise epoch_mode.EvidenceEpochModeError(
                    "interrupted epoch start packet identity changed"
                )
            registry["track_modes"][TRACK_ID] = "frozen_enforced"
            _write_json_atomic(epoch_mode.TRACK_MODE_REGISTRY_PATH, registry)
            return epoch
        raise SystemExit("[FATAL] epoch/registry mode mismatch; resolve manually before starting a new epoch")
    proposed_archive_path = EPOCH_ARCHIVE_DIR / f"{epoch_id}.json"
    if proposed_archive_path.exists():
        raise SystemExit("[FATAL] epoch_id was already used; epoch identities and receipts are never reusable")
    packet_identity = epoch_mode.validate_frozen_transition(TRACK_ID)
    new_epoch = build_frozen_epoch(
        tracker, epoch_id, start_as_of,
        freeze_packet_identity=packet_identity,
    )
    old_archive_path = None
    if reset_epoch:
        if not epoch_is_frozen:
            raise SystemExit("[FATAL] --reset-epoch requires an existing frozen epoch")
        old_archive_path = EPOCH_ARCHIVE_DIR / f"{epoch['epoch_id']}.json"
        if new_epoch["epoch_id"] == epoch["epoch_id"]:
            raise SystemExit("[FATAL] reset epoch_id must be new; private receipts are immutable")
    elif epoch_is_frozen:
        raise SystemExit("[FATAL] a frozen epoch exists; use explicit --reset-epoch to archive and replace it")
    start_live = validate_tracker_lineage(tracker)
    start_cohort = start_live[start_live["as_of"].astype(str) == str(start_as_of)].copy()
    receipt = build_cohort_admission_receipt(
        start_cohort, new_epoch, int(load_governance()["policy"]["top_n"])
    )
    if receipt is None:
        raise SystemExit("[FATAL] epoch start cohort could not be sealed before H10 observation")
    proposed_private_dir = _epoch_private_dir(private_root, new_epoch)
    admission_path = _epoch_private_dir(private_root, new_epoch) / "admissions" / f"{start_as_of}.json"
    if proposed_private_dir.exists():
        expected_paths = {admission_path.resolve()}
        actual_paths = {path.resolve() for path in proposed_private_dir.rglob("*") if path.is_file()}
        if actual_paths != expected_paths:
            raise SystemExit("[FATAL] interrupted epoch start has unexpected immutable artifacts")
    _write_json_exclusive_idempotent(admission_path, receipt)
    new_epoch["admission_receipt_manifest"] = admission_receipt_manifest({str(start_as_of): receipt})
    if old_archive_path is not None:
        _write_json_atomic_idempotent(old_archive_path, epoch)
    # Active epoch first, registry second: interruption between the writes is
    # fail-closed as epoch_mode_mismatch and cannot advance the clock.
    _write_json_atomic(EPOCH_PATH, new_epoch)
    registry["track_modes"][TRACK_ID] = "frozen_enforced"
    _write_json_atomic(epoch_mode.TRACK_MODE_REGISTRY_PATH, registry)
    return new_epoch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate local A-short theme comparison evidence; no data fetch or promotion.")
    parser.add_argument("--tracker", default=str(DEFAULT_TRACKER))
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--start-epoch", help="explicit new epoch id; does not evaluate or promote")
    parser.add_argument("--epoch-start-as-of", help="YYYYMMDD cohort whose theme family is frozen")
    parser.add_argument("--reset-epoch", action="store_true", help="archive the current frozen epoch before opening --start-epoch")
    parser.add_argument("--private-root", default=str(DEFAULT_PRIVATE_ROOT))
    parser.add_argument("--run-revision-id", default=None)
    parser.add_argument("--official-project-root", default=None,
                        help="optional project root whose official pointer gates formal receipts")
    args = parser.parse_args(argv)
    tracker_path = Path(args.tracker)
    if not tracker_path.exists():
        raise SystemExit(f"[FATAL] forward tracker not found: {tracker_path}")
    tracker = pd.read_csv(tracker_path, dtype=TRACKER_STRING_COLUMNS)
    private_root = _private_root(args.private_root)
    run_revision_id = None
    if args.run_revision_id is not None:
        try:
            run_revision_id = validate_run_revision_id(args.run_revision_id)
        except ValueError as exc:
            raise SystemExit(f"[FATAL] invalid --run-revision-id: {exc}") from exc
        if "run_revision_id" not in tracker.columns:
            raise SystemExit("[FATAL] tracker has no run_revision_id; cannot prove theme cohort binding")
        if args.official_project_root:
            # A current invocation id must not hide older official cohorts.
            # Resolve each tracker row by its own decision date; the private
            # epoch remains rooted at the shared theme directory.
            official_rows = []
            for _, row in tracker.iterrows():
                row_revision = str(row.get("run_revision_id") or "")
                row_as_of = str(row.get("as_of") or "")
                if not row_revision or not row_as_of:
                    continue
                selected = resolve_official_revision(
                    args.official_project_root, row_as_of, require=False,
                )
                if selected is not None and selected["selected_revision_id"] == row_revision:
                    official_rows.append(row)
            tracker = pd.DataFrame(official_rows, columns=tracker.columns)
        else:
            tracker = tracker[tracker["run_revision_id"].fillna("").astype(str) == run_revision_id].copy()
            private_root = (
                private_revision_root(private_root, str(tracker["as_of"].iloc[0]), run_revision_id)
                if not tracker.empty else private_root / "revisions" / run_revision_id
            )
    elif "run_revision_id" in tracker.columns:
        revisions = {
            str(value) for value in tracker["run_revision_id"]
            if not pd.isna(value) and str(value or "")
        }
        has_legacy_rows = any(
            pd.isna(value) or not str(value or "")
            for value in tracker["run_revision_id"]
        )
        if len(revisions) > 1 or (revisions and has_legacy_rows):
            raise SystemExit("[FATAL] mixed revisionized tracker requires explicit --run-revision-id")
        if revisions:
            run_revision_id = validate_run_revision_id(next(iter(revisions)))
    if args.official_project_root and run_revision_id is None and not tracker.empty:
        raise SystemExit("[FATAL] official theme settlement requires revision-bound tracker rows")
    if run_revision_id is not None and args.official_project_root:
        for as_of in sorted({str(value) for value in tracker["as_of"]}):
            require_official_revision(args.official_project_root, as_of, run_revision_id)
    if args.start_epoch:
        if not args.epoch_start_as_of:
            raise SystemExit("[FATAL] --start-epoch requires --epoch-start-as-of")
        epoch = _start_or_reset_epoch(
            tracker, args.start_epoch, args.epoch_start_as_of, private_root,
            reset_epoch=args.reset_epoch,
        )
        print(f"[OK] opened frozen theme comparison epoch: {epoch['epoch_id']}; clock starts from {epoch['epoch_start_as_of']}")
        return 0
    if args.epoch_start_as_of or args.reset_epoch:
        raise SystemExit("[FATAL] --epoch-start-as-of and --reset-epoch require --start-epoch")
    epoch = load_epoch()
    admission_receipts = _sync_cohort_admission_receipts(tracker, epoch, private_root)
    outcome_receipts = _sync_terminal_outcome_receipts(
        tracker, epoch, private_root, admission_receipts
    )
    formal_receipt = _load_formal_decision_receipt(epoch, private_root)
    recorded_formal_packet = _load_recorded_formal_packet(
        epoch, formal_receipt, private_root
    )
    packet = evaluate_theme_forward_comparison(
        tracker,
        admission_receipts=admission_receipts,
        outcome_receipts=outcome_receipts,
        formal_decision_receipt=formal_receipt,
        recorded_formal_packet=recorded_formal_packet,
    )
    # The packet is a de-identified public current view.  When a formal
    # resolver is supplied, carry the one selected identity instead of letting
    # a reader infer it from tracker row order.  A mixed-date packet is left
    # explicitly unbound rather than inventing one revision for all cohorts.
    official_revision_id = None
    if args.official_project_root and run_revision_id is not None and not tracker.empty:
        selected = {str(value) for value in tracker["run_revision_id"].dropna().astype(str) if value}
        if len(selected) == 1:
            official_revision_id = next(iter(selected))
    packet["official_revision_id"] = official_revision_id
    validate_comparison_packet(packet)
    output_path = Path(args.out)
    _write_json_atomic(output_path, packet)
    _record_formal_decision_if_due(packet, output_path, private_root)
    print(f"[OK] wrote comparison packet: {args.out}; checkpoint={packet['checkpoints']['current_checkpoint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
