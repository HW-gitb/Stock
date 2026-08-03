"""Single source of truth for the bounded US-short discovery provider caps."""

from __future__ import annotations


MAX_TAVILY_QUERIES = 25
MAX_DEEPSEEK_REGROUP_CALLS = 25
MAX_X_QUERIES = 15

PROVIDER_CALL_BUDGET = {
    ("web", "tavily"): MAX_TAVILY_QUERIES,
    ("web", "deepseek"): MAX_DEEPSEEK_REGROUP_CALLS,
    ("x", "xai"): MAX_X_QUERIES,
}
