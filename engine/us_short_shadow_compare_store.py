# -*- coding: utf-8 -*-
"""US-short §12.2 比较轨 shadow comparison persistence — batch-3 (#13/#24 follow-up): gitignored write + stale-aware load.

Design authority: docs/us_short_system_design.md §12.2 (存储隐私: 比较轨含票名的 shadow 选股/成绩 →
state/us_short/shadow_compare_private/, gitignored) / §11.6 (lifecycle/shadow/paper 隐私: 含票名/$/持仓 → 必须
private/gitignored) / §18.0 P0 (私密路径 guard) / §2.1 (桶名 ≠ decision_date → fail-closed 弃) / §18.1 #20 (陈旧
artifact fail-closed). Consumes ``engine.us_short_shadow_compare.build_shadow_comparison`` output.

A shadow comparison carries per-profile TopN selections WITH ticker names (private-tier, §11.6), so it MUST land
only on a gitignored private path (``state/us_short/shadow_compare_private/``). This is the FIRST shadow-compare
PERSISTER, mirroring ``engine.us_short_lifecycle_store`` / ``engine.us_short_paper_ledger``:

  * ``write_shadow_comparison`` wires the §18.0 P0 fail-closed private-path guard (``reject_nonprivate_output_path``)
    BEFORE any validate / write, and persists a DATED record ``{as_of, comparison}`` only after the record (strict
    real ``as_of`` + the §12.2 projection contract via ``validate_shadow_comparison``) validates — a malformed
    comparison / date is refused before any file side effect;
  * ``load_shadow_comparison`` applies the SAME §18.0 guard to the SOURCE first (SYMMETRIC — a private artifact is
    read only from a provably-private path, never a tracked in-repo one), then re-validates and fails closed on a
    stale / bad bucket: an unreadable / corrupt-JSON / malformed record, or (given the run's decision_date) a
    persisted ``as_of`` NEWER than that decision_date (§2.1 桶名 ≠ decision_date → 弃 / §18.1 #20 / §12.2 升级闸 陈旧
    artifact). Re-running the SAME decision_date (idempotent) and loading an OLDER week's comparison for the
    upgrade accumulator (forward progress) are both fine.

Beyond the §18.0 PRIVACY guard, both write and load also enforce a store-specific BUCKET / NAMESPACE guard
(``_check_bucket``): the §18.0 guard only proves a path is gitignored, not that it is the RIGHT US-short
shadow-compare bucket. An IN-REPO path MUST be the canonical ``SHADOW_COMPARE_PRIVATE_DIR /
shadow_comparison_<as_of>.json`` (the US-short shadow-compare namespace + filename date == record ``as_of``,
§2.1 桶名 = as_of), so a US-short comparison can never be mis-filed into another lane (``state/a_short`` /
``state/us_long``) or another US-short private dir (``model_paper_private`` / ``lifecycle``), nor under the wrong
week. OUTSIDE-repo absolute paths stay allowed as external non-canonical locations (tests / a manual private
store), EXCEPT a canonical-LOOKING ``shadow_comparison_<date>.json`` filename there must still match ``as_of``.

``shadow_comparison_path(as_of)`` is the canonical dated bucket (桶名 = as_of by construction). The de-identified
TRACKED summary, the paper-NAV two-way scorecard, and the anti-self-deception upgrade gate are LATER §12.2 cuts —
this slice only persists / loads the ticker-bearing private artifact. Structure-over-IO: reads/writes a private
JSON only; no provider / live / DataHub / network; no A-share crossing. The strict date gate is inlined (with the
``isascii()`` guard) so this persister stays jsonschema-free / importable on a minimal runtime. Malformed input
fails closed.
"""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

from engine.us_short_shadow_compare import ShadowCompareError, validate_shadow_comparison
from engine.us_short_private_paths import reject_nonprivate_output_path

ROOT = Path(__file__).resolve().parent.parent
SHADOW_COMPARE_PRIVATE_DIR = ROOT / "state" / "us_short" / "shadow_compare_private"  # gitignored private location (§12.2 / §11.6)

_RECORD_KEYS = frozenset({"as_of", "comparison"})
_CANONICAL_BUCKET_RE = re.compile(r"^shadow_comparison_\d{8}\.json$")  # the canonical dated bucket filename shape


class ShadowCompareStoreError(ShadowCompareError):
    """Raised when a persisted shadow_comparison record violates the §12.2 store contract (record shape / date)."""


class StaleShadowComparisonError(ShadowCompareStoreError):
    """Raised when a persisted shadow_comparison cannot be trusted for the current run — unreadable / corrupt JSON,
    or a stale / misaligned bucket whose as_of is NEWER than the run's decision_date (§2.1 / §18.1 #20 / §12.2)."""


def _strict_yyyymmdd(s) -> bool:
    # inlined (mirrors the canonical lifecycle date gate) so this pure persistence helper stays importable on a
    # minimal runtime — it must NOT drag jsonschema in through engine.us_short_lifecycle_eval. isascii() rejects
    # Unicode digits (Arabic-Indic / fullwidth) that int() would still coerce (the whole-class DATE-ASCII lesson)
    if not (isinstance(s, str) and len(s) == 8 and s.isascii() and s.isdigit()):
        return False
    try:
        datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        return True
    except ValueError:
        return False


def _validate_record(record) -> None:
    """Fail-closed §12.2 shadow_comparison record gate: a dict carrying EXACTLY ``{as_of, comparison}`` (closed
    world), a strict real ``as_of`` (YYYYMMDD), and a ``comparison`` that passes the §12.2 projection contract
    (``validate_shadow_comparison`` — the frozen track / boundary / profile const-pin / deterministic selection).
    Raises ``ShadowCompareStoreError`` on a bad record shape / date, ``ShadowCompareError`` on a bad comparison —
    the persister never trusts the producer."""
    if not isinstance(record, dict):
        raise ShadowCompareStoreError("shadow_comparison record must be a dict, got %r" % (type(record).__name__,))
    if set(record) != _RECORD_KEYS:
        raise ShadowCompareStoreError(
            "shadow_comparison record must carry EXACTLY %s, got %s" % (sorted(_RECORD_KEYS), sorted(map(str, record))))
    as_of = record["as_of"]
    if not (isinstance(as_of, str) and _strict_yyyymmdd(as_of)):
        raise ShadowCompareStoreError("shadow_comparison as_of must be a strict real YYYYMMDD, got %r" % (as_of,))
    validate_shadow_comparison(record["comparison"])  # the §12.2 projection contract (raises ShadowCompareError)


def shadow_comparison_path(as_of):
    """The canonical gitignored private bucket for a decision_date's shadow comparison
    (``state/us_short/shadow_compare_private/shadow_comparison_<as_of>.json``, §11.6 / §12.2 桶名 = as_of). Raises
    ``ShadowCompareStoreError`` on a non-strict as_of (a bad bucket name is refused at construction)."""
    if not (isinstance(as_of, str) and _strict_yyyymmdd(as_of)):
        raise ShadowCompareStoreError("shadow_comparison bucket as_of must be a strict real YYYYMMDD, got %r" % (as_of,))
    return SHADOW_COMPARE_PRIVATE_DIR / ("shadow_comparison_%s.json" % as_of)


def _check_bucket(path, as_of, *, where) -> None:
    """Store-specific bucket / namespace guard, BEYOND the §18.0 privacy guard (which only proves a path is
    gitignored, not that it is the RIGHT US-short shadow-compare bucket) — §2.1 桶名 = as_of + A-vs-US lane
    isolation. An IN-REPO path MUST be the canonical bucket ``SHADOW_COMPARE_PRIVATE_DIR /
    shadow_comparison_<as_of>.json``: another gitignored private dir (``model_paper_private`` / ``lifecycle`` /
    ``state/a_short/...`` / ``state/us_long/...``) or a filename whose date disagrees with the record ``as_of`` is
    refused, so a US-short comparison can never be mis-filed into another lane / week. An OUTSIDE-repo path is an
    external non-canonical location (tests / a manual private store) and is allowed, EXCEPT a canonical-LOOKING
    ``shadow_comparison_<date>.json`` filename there must still match ``as_of`` (never let the bucket label disagree
    with the record date). Raises ``ShadowCompareStoreError``."""
    p = Path(path).resolve()
    canonical_name = "shadow_comparison_%s.json" % as_of
    try:
        p.relative_to(ROOT)
        in_repo = True
    except ValueError:
        in_repo = False
    if in_repo:
        if p.parent != SHADOW_COMPARE_PRIVATE_DIR.resolve() or p.name != canonical_name:
            raise ShadowCompareStoreError(
                "%s in-repo shadow_comparison path must be the canonical bucket %s (the US-short "
                "shadow_compare_private namespace + filename date == record as_of, §2.1 / §12.2), got %s"
                % (where, SHADOW_COMPARE_PRIVATE_DIR / canonical_name, p))
    elif _CANONICAL_BUCKET_RE.match(p.name) and p.name != canonical_name:
        raise ShadowCompareStoreError(
            "%s external shadow_comparison filename %r looks canonical but its date disagrees with the record "
            "as_of %r (桶名 ≠ as_of) — align the filename or the record date" % (where, p.name, as_of))


def write_shadow_comparison(comparison, out_path, *, as_of):
    """Persist a §12.2 shadow comparison (ticker-bearing, private-tier §11.6) as a DATED record
    ``{as_of, comparison}`` to a gitignored private path. Returns the written ``Path``.

    The §18.0 P0 fail-closed private-path guard runs BEFORE any validate / write (the comparison carries ticker
    names), so a relative / non-gitignored in-repo destination is refused (``PrivatePathError``). The record (strict
    real ``as_of`` + the §12.2 ``validate_shadow_comparison`` contract) is then validated, so a malformed comparison
    / date is refused before any file side effect. Pass ``shadow_comparison_path(as_of)`` (canonical dated bucket)
    or an external absolute path."""
    reject_nonprivate_output_path(out_path)  # §18.0 P0 guard — before validate / write / any side effect
    record = {"as_of": as_of, "comparison": comparison}
    _validate_record(record)
    _check_bucket(out_path, as_of, where="write")  # §2.1 桶名=as_of + US-short shadow-compare namespace (beyond the privacy guard)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)  # the gitignored private dir may not exist yet
    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return out_path


def load_shadow_comparison(in_path, *, expected_as_of=None) -> dict:
    """Load + re-validate a persisted shadow_comparison record; fail closed on a stale / bad bucket. Returns the
    ``{as_of, comparison}`` record dict.

    SYMMETRIC with the persister: the §18.0 P0 guard runs FIRST on ``in_path`` (a private artifact is read only
    from a provably-private source — a relative / non-gitignored in-repo source is refused before any read, so a
    tracked-path comparison can't enter the pipeline). Raises ``StaleShadowComparisonError`` if the file is
    missing / unreadable / not valid JSON, or — when ``expected_as_of`` is the run's decision_date — the persisted
    ``as_of`` is NEWER than ``expected_as_of`` (§2.1 桶名 ≠ decision_date → fail-closed 弃 / §18.1 #20 / §12.2 升级闸
    陈旧 artifact). Raises ``ShadowCompareStoreError`` / ``ShadowCompareError`` if the persisted CONTENT fails the
    record / §12.2 contract (never consume an un-validated comparison). Re-running the SAME decision_date
    (as_of == expected_as_of, idempotent) and loading an OLDER week's comparison (as_of < expected_as_of, forward
    progress for the upgrade accumulator) are both fine."""
    reject_nonprivate_output_path(in_path)  # §18.0 P0 guard — symmetric: read a private artifact ONLY from a provably-private source
    in_path = Path(in_path)
    try:
        raw = in_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as e:
        raise StaleShadowComparisonError("shadow_comparison artifact unreadable at %s: %s" % (in_path, e))
    try:
        record = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        raise StaleShadowComparisonError("shadow_comparison artifact at %s is not valid JSON: %s" % (in_path, e))

    _validate_record(record)  # record shape + strict as_of + the §12.2 comparison contract
    _check_bucket(in_path, record["as_of"], where="load")  # §2.1 桶名=as_of + namespace — the bucket must match the record's own date

    if expected_as_of is not None:
        if not _strict_yyyymmdd(expected_as_of):
            raise StaleShadowComparisonError("expected_as_of %r is not a strict real YYYYMMDD" % (expected_as_of,))
        as_of = record["as_of"]  # _validate_record guarantees a strict YYYYMMDD string (lexicographic compare OK)
        if as_of > expected_as_of:
            raise StaleShadowComparisonError(
                "stale / misaligned shadow_comparison bucket: persisted as_of %s is NEWER than the run "
                "decision_date %s (a future-dated comparison leaking into an earlier run, §2.1 / §18.1 #20 / "
                "§12.2 升级闸) — fail closed" % (as_of, expected_as_of))
    return record
