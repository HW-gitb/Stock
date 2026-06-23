# -*- coding: utf-8 -*-
"""US-short §12.2 upgrade-gate forward-observation discover — batch-3 (#13/#24/#28 follow-up; ①③ artifact layer).

Design authority: docs/us_short_system_design.md §12.2 升级闸防自欺 ① (只数 live forward 观测: 决策当日 PIT、无
look-ahead) / ③ (陈旧/错位 artifact fail-closed 不计入) / §11.6 (含票名的 shadow 比较 → private). Mirrors the
A-share ``runners/a_short_overlay_eval.discover_forward_overlays``.

Scans the private shadow_compare buckets for the forward (live decision-week, PIT) comparison observations that
feed ``engine.us_short_upgrade_gate.build_upgrade_eval``. Each candidate bucket is loaded through
``engine.us_short_shadow_compare_store.load_shadow_comparison`` with ``expected_as_of = the run's decision_date``,
so the §18.0 private-path guard + the record / §12.2 comparison contract + the bucket-name == content as_of check +
the stale gate (a bucket dated AFTER the decision date is a look-ahead leak, §12.2 ①③) all apply. CRUCIALLY it
then counts ONLY a record whose ``observation_kind == LIVE_FORWARD`` (§12.2 ①: only a genuine live decision-week
forward run advances the upgrade clock — date ordering alone can't tell a true live-forward bucket from a
today-produced historical one); a historical replay / research backfill / manual record carries a non-live kind and
is SKIPPED. A malformed / stale / mis-bucketed / unreadable / non-live-kind / non-canonical artifact is SKIPPED
(fail-closed: never count bad / backfilled evidence toward the upgrade clock). Returns the forward observations as a
list of ``{"as_of"}`` (de-identified — only the decision-week date),
ascending + unique, ready for ``build_upgrade_eval``.

Pure IO + reuse: lists a directory + loads private JSON through the store; no provider / live / DataHub / network;
no jsonschema; no A-share crossing. Only a bad ``run_as_of`` raises (``UpgradeObsDiscoverError``).
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

from engine.us_short_shadow_compare import ShadowCompareError
from engine.us_short_shadow_compare_store import LIVE_FORWARD, SHADOW_COMPARE_PRIVATE_DIR, load_shadow_comparison
from engine.us_short_private_paths import PrivatePathError

_BUCKET_RE = re.compile(r"^shadow_comparison_\d{8}\.json$")


class UpgradeObsDiscoverError(ValueError):
    """Raised when the discover inputs are malformed (a bad run decision_date)."""


def _strict_yyyymmdd(s) -> bool:
    if not (isinstance(s, str) and len(s) == 8 and s.isascii() and s.isdigit()):
        return False
    try:
        datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        return True
    except ValueError:
        return False


def discover_forward_observations(run_as_of, *, buckets_dir=None) -> list:
    """Discover the forward comparison observations (decision-week ``as_of`` ≤ ``run_as_of``, contract-clean) from
    the private shadow_compare buckets → a list of ``{"as_of"}`` ascending + unique, ready for
    ``engine.us_short_upgrade_gate.build_upgrade_eval``. ``run_as_of`` = the run's decision_date (strict YYYYMMDD);
    ``buckets_dir`` defaults to the canonical ``SHADOW_COMPARE_PRIVATE_DIR``. A malformed / stale (dated after
    ``run_as_of``) / mis-bucketed / unreadable bucket is SKIPPED (fail-closed, §12.2 ①③ — never count bad evidence).
    Raises ``UpgradeObsDiscoverError`` only on a bad ``run_as_of``."""
    if not _strict_yyyymmdd(run_as_of):
        raise UpgradeObsDiscoverError("run_as_of must be a strict real YYYYMMDD, got %r" % (run_as_of,))
    base = Path(buckets_dir) if buckets_dir is not None else SHADOW_COMPARE_PRIVATE_DIR
    if not base.is_dir():
        return []
    by_as_of = {}
    for path in sorted(base.glob("shadow_comparison_*.json")):
        if not _BUCKET_RE.match(path.name):
            continue  # not a canonical dated bucket filename
        try:
            # §18.0 guard + record/§12.2 contract + bucket-name==content + stale gate (content as_of ≤ run_as_of)
            rec = load_shadow_comparison(path, expected_as_of=run_as_of)
        except (ShadowCompareError, PrivatePathError, OSError):
            continue  # malformed / stale (future) / mis-bucketed / unreadable → skip (fail-closed, never counted)
        if rec["observation_kind"] != LIVE_FORWARD:
            continue  # §12.2 ①: only a genuine live-forward run counts; historical replay / research backfill / manual skipped
        by_as_of[rec["as_of"]] = {"as_of": rec["as_of"]}  # de-identified — only the decision-week date
    return [by_as_of[k] for k in sorted(by_as_of)]
