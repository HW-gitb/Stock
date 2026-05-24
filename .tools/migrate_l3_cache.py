#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Merge dated L3 concept caches into shared reusable caches."""

import pickle
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "A-EGS" / "Result" / "egs_cache"


def load_pickle(path):
    with path.open("rb") as f:
        return pickle.load(f)


def save_pickle(path, data):
    with path.open("wb") as f:
        pickle.dump(data, f)


def migrate_concepts():
    target = CACHE_DIR / "concepts_ts_latest.pkl"
    if target.exists():
        return "concepts_ts_latest exists"
    sources = sorted(CACHE_DIR.glob("concepts_ts_20*.pkl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not sources:
        return "no concepts_ts source"
    save_pickle(target, load_pickle(sources[0]))
    return f"created {target.name} from {sources[0].name}"


def migrate_stock_concepts():
    target = CACHE_DIR / "stock_concepts_latest.pkl"
    merged = load_pickle(target) if target.exists() else {}
    before = len(merged)
    for path in sorted(CACHE_DIR.glob("stock_concepts_20*.pkl")):
        data = load_pickle(path)
        if isinstance(data, dict):
            merged.update(data)
    save_pickle(target, merged)
    return f"{target.name}: {before} -> {len(merged)} stocks"


def migrate_concept_members():
    grouped = {}
    for path in sorted(CACHE_DIR.glob("concept_members_20*.pkl")):
        try:
            count = int(path.stem.split("_")[-1])
        except ValueError:
            continue
        grouped.setdefault(count, []).append(path)

    messages = []
    for count, paths in grouped.items():
        target = CACHE_DIR / f"concept_members_latest_{count}.pkl"
        merged = load_pickle(target) if target.exists() else {}
        before = len(merged)
        for path in paths:
            data = load_pickle(path)
            if isinstance(data, dict):
                merged.update(data)
        save_pickle(target, merged)
        messages.append(f"{target.name}: {before} -> {len(merged)} concepts")
    return "; ".join(messages) if messages else "no concept_members source"


def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print(migrate_concepts())
    print(migrate_stock_concepts())
    print(migrate_concept_members())


if __name__ == "__main__":
    main()
