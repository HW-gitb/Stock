"""A-short EM (东方财富) news-feed feasibility probe — tracked, reproducible, probe-only.

This is the tracked source-feasibility path for the CURRENT weekly web_llm main source
(em 资讯搜索 on the same em endpoint as production ``fetch_em_news``), replacing the retired
one-off ``_diag_web_sources.py`` diagnostic that originally established EM reachability after the
Sina roll endpoint died (``code=11``). It mirrors the cninfo/Sina probe in
``a_short_semantic_risk_probe.py`` (classify → assess → build → validate → write → CLI) and REUSES
that module's helpers (``main_board_top15`` / ``_load_watch_pool`` / ``_is_canonical_date`` /
``_guard_out_path`` / the em endpoint constants + ``_strip_jsonp``) instead of re-implementing them.

What it characterizes (over the main-board Top15 watch pool): EM reachability per code,
recent-news coverage, future-dated rejection, and shape/date quality. To AUDIT that quality the
probe does its OWN unfiltered fetch (``fetch_em_news_unfiltered``): same em endpoint and request as
production ``fetch_em_news``, but it returns the normalized-but-UNFILTERED item stream (NO
PIT/recency window filter, no sort/cap, empty fields kept, non-dict rows kept) so
``classify_em_code`` can actually COUNT future / stale / bad-date / bad-shape rows. Production
weekly uses the FILTERED ``fetch_em_news``; the probe must NOT reuse it, because that function
drops future-dated / out-of-window / malformed rows BEFORE the probe sees them — which would let
the probe always report zero leak and silently overclaim auditing
(``R-ASHORT-EM-PROBE-FETCHER-FILTER-AUDIT-GAP``). Any future-dated / unparseable-date / bad-shape
item makes that code ``unknown``, NEVER ``reachable_*``. A pure/tested core; ``main`` is thin and
the real EM HTTP fetch is gated behind ``--confirm-fetch-authorized`` (the real fetch = a
user-authorized 执行).

Boundary (hard): probe-only, non-production, advisory_only. EM is a media publish-time source,
NOT an official disclosure-date PIT source (``backtest_evidence_capable=false``): it can REJECT
future-dated items but must NEVER hard-veto, change EGS scoring, change Phase5 decision, produce
historical-backtest evidence, or write a production ``result/a_short`` path. Provider failure for
a code => that code's status is ``unknown``, never ``reachable``. V14.2 stays frozen; the
production stage3 / DeepSeek judgment semantics are untouched (this probe only characterizes
取数可行性, not 判官 correctness).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import jsonschema  # noqa: E402

from engine.data.a_share_board_scope import is_a_share_main_board  # noqa: E402
from runners.a_short_semantic_risk_probe import (  # noqa: E402
    EM_NEWS_PAGE_SIZE, EM_NEWS_REFERER, EM_NEWS_SEARCH_URL, EM_NEWS_UA,
    TOP15_CAP, _categorize_error, _guard_out_path, _is_canonical_date,
    _load_watch_pool, _strip_jsonp, main_board_top15,
)

SCHEMA_NAME = "a_short_em_news_probe_summary"
SCHEMA_VERSION = "1.0.0"
SCHEMA_PATH = ROOT / "schemas" / "a_short_em_news_probe_summary.schema.json"

# EM(web advisory)可行性门槛(主板 Top15 探测对象)。
MIN_EM_OK_CODES = 8            # 至少 8 个码成功响应(链路可达)
MIN_EM_OK_RATIO = 0.6         # 成功率下限
MIN_EM_RECENT_NEWS_CODES = 3  # 至少 3 个码取到近期新闻(证明链路真在返回数据,而非端点全坏却不报错)
DEFAULT_LOOKBACK_DAYS = 30    # 近期新闻窗(天)


# ── 单条 EM 资讯的日期/形状分类(probe 走 unfiltered 取数,classify 独立审计每条 raw 质量)────
def _em_item_shape_ok(it) -> bool:
    """title / url / published_at 三者皆非空才算形状合格(否则 bad_shape)。"""
    return (isinstance(it, dict)
            and bool(str(it.get("title", "") or "").strip())
            and bool(str(it.get("url", "") or "").strip())
            and bool(str(it.get("published_at", "") or "").strip()))


def _em_item_date_class(published_at, as_of, lookback_days) -> str:
    """published_at 相对 as_of(PIT)与近期窗的分类:
    'recent'  = canonical 且 as_of-lookback <= d <= as_of(可喂判官);
    'future'  = d > as_of(PIT 泄漏 = 质量缺陷);
    'stale'   = canonical 且 d <= as_of 但早于窗起点(合法,只是不近期,非缺陷);
    'bad_date'= 不可解析(质量缺陷)。"""
    try:
        d = datetime.strptime(str(published_at)[:10], "%Y-%m-%d").date()
        a = datetime.strptime(str(as_of), "%Y%m%d").date()
    except (ValueError, TypeError):
        return "bad_date"
    if d > a:
        return "future"
    if d < a - timedelta(days=int(lookback_days)):
        return "stale"
    return "recent"


def classify_em_code(raw: dict, as_of: str, lookback_days: int) -> dict:
    """单代码 EM fetch 结果 → 分类。probe 自己重算每条 item(defense in depth,不信 fetcher 的过滤):
    传输失败 → 'unknown';任何 future / 不可解析日期 / 残缺条目(质量缺陷)→ 'unknown'(绝不伪装
    reachable);干净 ok 且 >=1 条近期新闻 → 'reachable_with_news';干净 ok 且 0 条近期 → 'reachable_quiet'。"""
    ts_code = str(raw.get("ts_code", ""))
    if not raw.get("ok"):
        return {"ts_code": ts_code, "ok": False,
                "error_category": raw.get("error_category") or "other",
                "n_items": 0, "n_recent": 0, "n_future": 0, "n_stale": 0,
                "n_bad_date": 0, "n_bad_shape": 0, "status": "unknown"}
    items = list(raw.get("items") or [])
    n_items = len(items)
    n_recent = n_future = n_stale = n_bad_date = n_bad_shape = 0
    for it in items:
        if not _em_item_shape_ok(it):
            n_bad_shape += 1
            continue
        cls = _em_item_date_class(it.get("published_at"), as_of, lookback_days)
        if cls == "recent":
            n_recent += 1
        elif cls == "future":
            n_future += 1
        elif cls == "stale":
            n_stale += 1
        else:
            n_bad_date += 1
    defect = (n_future > 0 or n_bad_date > 0 or n_bad_shape > 0)
    if defect:
        status = "unknown"
    elif n_recent > 0:
        status = "reachable_with_news"
    else:
        status = "reachable_quiet"
    return {"ts_code": ts_code, "ok": True, "error_category": None,
            "n_items": n_items, "n_recent": n_recent, "n_future": n_future,
            "n_stale": n_stale, "n_bad_date": n_bad_date, "n_bad_shape": n_bad_shape,
            "status": status}


def _tally_em_failures(classified: list[dict]) -> dict:
    """失败代码按 error_category 计数(sanitized:只给类别)。"""
    out: dict[str, int] = {}
    for c in classified:
        if not c["ok"]:
            cat = c["error_category"] or "other"
            out[cat] = out.get(cat, 0) + 1
    return out


def assess_em_feasibility(per_code_raw: list[dict], as_of: str, lookback_days: int) -> dict:
    """聚合 EM(web advisory)可行性。EM 能拒未来文(future_dated_rejection),但仍 advisory 媒体源、
    非官方披露 PIT → backtest_evidence_capable 恒 False。"""
    as_of = str(as_of)
    as_of_is_valid_date = _is_canonical_date(as_of)
    classified = [classify_em_code(r, as_of, lookback_days) for r in (per_code_raw or [])]
    n_requested = len(classified)
    n_ok = sum(1 for c in classified if c["ok"])
    n_failed = n_requested - n_ok
    n_with_recent_news = sum(1 for c in classified if c["status"] == "reachable_with_news")
    n_future_leak_codes = sum(1 for c in classified if c["n_future"] > 0)
    n_bad_date_codes = sum(1 for c in classified if c["n_bad_date"] > 0)
    n_bad_shape_codes = sum(1 for c in classified if c["n_bad_shape"] > 0)
    ok_ratio = round(n_ok / n_requested, 6) if n_requested else 0.0

    reasons: list[str] = []
    if not as_of_is_valid_date:
        reasons.append(f"as_of {as_of} 不是合法日历日期")
    if n_requested == 0:
        reasons.append("EM 探针未探测任何代码(观察池无主板代码或未运行)")
    else:
        if n_ok < MIN_EM_OK_CODES:
            reasons.append(f"成功响应代码数 {n_ok} < {MIN_EM_OK_CODES}")
        if ok_ratio < MIN_EM_OK_RATIO:
            reasons.append(f"成功率 {ok_ratio:.2f} < {MIN_EM_OK_RATIO}")
        if n_with_recent_news < MIN_EM_RECENT_NEWS_CODES:
            reasons.append(f"有近期新闻代码数 {n_with_recent_news} < {MIN_EM_RECENT_NEWS_CODES}")
        if n_future_leak_codes:
            reasons.append(f"{n_future_leak_codes} 个代码出现未来日期新闻(PIT 泄漏)")
        if n_bad_date_codes:
            reasons.append(f"{n_bad_date_codes} 个代码出现不可解析日期")
        if n_bad_shape_codes:
            reasons.append(f"{n_bad_shape_codes} 个代码出现残缺条目(缺 title/url/date)")

    feasible = (
        as_of_is_valid_date
        and n_requested > 0
        and n_ok >= MIN_EM_OK_CODES
        and ok_ratio >= MIN_EM_OK_RATIO
        and n_with_recent_news >= MIN_EM_RECENT_NEWS_CODES
        and n_future_leak_codes == 0
        and n_bad_date_codes == 0
        and n_bad_shape_codes == 0
    )
    return {
        "as_of_is_valid_date": bool(as_of_is_valid_date),
        "future_dated_rejection": n_future_leak_codes == 0,
        "backtest_evidence_capable": False,
        "lookback_days": int(lookback_days),
        "n_requested": n_requested, "n_ok": n_ok, "n_failed": n_failed,
        "n_with_recent_news": n_with_recent_news,
        "n_future_leak_codes": n_future_leak_codes,
        "n_bad_date_codes": n_bad_date_codes,
        "n_bad_shape_codes": n_bad_shape_codes,
        "ok_ratio": ok_ratio,
        "failure_categories": _tally_em_failures(classified),
        "per_code": classified, "feasible": bool(feasible), "reasons": reasons,
    }


# ── summary 组装 + 一致性硬门 ─────────────────────────────────────────────────
def build_em_probe_summary(universe: dict, em: dict, as_of: str, generated_at: str) -> dict:
    return {
        "schema_name": SCHEMA_NAME, "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at, "as_of": as_of,
        "universe": {
            "requested": list(universe.get("requested", [])),
            "main_board_top15": list(universe.get("main_board_top15", [])),
            "dropped_non_main": list(universe.get("dropped_non_main", [])),
        },
        "thresholds": {
            "min_em_ok_codes": MIN_EM_OK_CODES,
            "min_em_ok_ratio": MIN_EM_OK_RATIO,
            "min_em_recent_news_codes": MIN_EM_RECENT_NEWS_CODES,
            "lookback_days": int(em["lookback_days"]),
        },
        "em": em,
        "feasible": bool(em["feasible"]),       # 总可行性 = em(本 probe 只验 EM 一个源)
        "boundary": {
            "production": False, "real_money": False, "hard_veto": False,
            "changes_egs_scoring": False, "changes_phase5_decision": False,
            "historical_backtest_evidence": False, "writes_production_path": False,
            "advisory_only": True,
        },
    }


def _check_em_counts(em: dict) -> None:
    if em["n_ok"] + em["n_failed"] != em["n_requested"]:
        raise ValueError("n_ok + n_failed != n_requested")
    if em["n_requested"]:
        expect = round(em["n_ok"] / em["n_requested"], 6)
        if abs(em["ok_ratio"] - expect) > 1e-6:
            raise ValueError("ok_ratio 与 n_ok/n_requested 不一致")
    elif em["ok_ratio"] != 0.0:
        raise ValueError("n_requested=0 时 ok_ratio 必须为 0")
    sum_failed = sum(1 for c in em["per_code"] if not c["ok"])
    if sum_failed != em["n_failed"]:
        raise ValueError("per_code 失败数与 n_failed 不一致")
    if sum(em["failure_categories"].values()) != em["n_failed"]:
        raise ValueError("failure_categories 总数与 n_failed 不一致")
    # 聚合计数与 per_code 一致
    if sum(1 for c in em["per_code"] if c["status"] == "reachable_with_news") != em["n_with_recent_news"]:
        raise ValueError("n_with_recent_news 与 per_code 不一致")
    for cnt, key in (("n_future", "n_future_leak_codes"),
                     ("n_bad_date", "n_bad_date_codes"),
                     ("n_bad_shape", "n_bad_shape_codes")):
        if sum(1 for c in em["per_code"] if c[cnt] > 0) != em[key]:
            raise ValueError(f"{key} 与 per_code 不一致")
    # 逐代码不变式
    for c in em["per_code"]:
        # 精确划分:recent + future + stale + bad_date + bad_shape == n_items
        if (c["n_recent"] + c["n_future"] + c["n_stale"] + c["n_bad_date"]
                + c["n_bad_shape"]) != c["n_items"]:
            raise ValueError(f"{c['ts_code']}: 条目分类计数和 != n_items")
        defect = (c["n_future"] > 0 or c["n_bad_date"] > 0 or c["n_bad_shape"] > 0)
        # 传输失败 ⇒ unknown(绝不伪装 reachable)
        if not c["ok"] and c["status"] != "unknown":
            raise ValueError(f"{c['ts_code']}: 传输失败必须为 unknown,不得伪装 reachable")
        # status 质量不变式:reachable 仅许 真正干净 的 ok 代码;有缺陷 ⇒ unknown
        if c["status"] in ("reachable_quiet", "reachable_with_news"):
            if not c["ok"]:
                raise ValueError(f"{c['ts_code']}: reachable 必须 ok")
            if defect:
                raise ValueError(f"{c['ts_code']}: 有质量缺陷的代码不得报 reachable(应 unknown)")
        if c["status"] == "reachable_with_news" and c["n_recent"] == 0:
            raise ValueError(f"{c['ts_code']}: reachable_with_news 需有近期新闻")
        if c["status"] == "reachable_quiet" and c["n_recent"] > 0:
            raise ValueError(f"{c['ts_code']}: 有近期新闻不应为 reachable_quiet")
        # 反向:ok 且无缺陷不得藏成 unknown(精确双向,防手搓虚报)
        if c["ok"] and not defect and c["status"] == "unknown":
            raise ValueError(f"{c['ts_code']}: ok 且无质量缺陷不得为 unknown(应 reachable)")


def validate_em_probe_summary_consistency(summary: dict) -> None:
    """顶层/子层不矛盾 + 逐代码失败→unknown 不变式 + universe 主板 + advisory 声明 + feasible⇒门全过。"""
    if bool(summary["feasible"]) != bool(summary["em"]["feasible"]):
        raise ValueError("顶层 feasible 必须等于 em.feasible")
    if not _is_canonical_date(summary["as_of"]):
        raise ValueError("as_of 非合法 canonical 日历日期")

    uni = summary["universe"]
    main = uni["main_board_top15"]
    if len(main) > TOP15_CAP:
        raise ValueError("main_board_top15 超过 15")
    if any(not is_a_share_main_board(c) for c in main):
        raise ValueError("main_board_top15 含非主板代码")
    if any(is_a_share_main_board(c) for c in uni["dropped_non_main"]):
        raise ValueError("dropped_non_main 含本应保留的主板代码")
    if set(main) & set(uni["dropped_non_main"]):
        raise ValueError("main_board_top15 与 dropped_non_main 不应重叠")

    em = summary["em"]
    if em["as_of_is_valid_date"] != _is_canonical_date(summary["as_of"]):
        raise ValueError("em.as_of_is_valid_date 与 as_of 不一致")
    if em["backtest_evidence_capable"] is not False:
        raise ValueError("em.backtest_evidence_capable 必须为 False(advisory 媒体源,不作回测/PIT 证据)")
    if em["future_dated_rejection"] != (em["n_future_leak_codes"] == 0):
        raise ValueError("future_dated_rejection 必须等于'零未来日期泄漏'")
    if em["lookback_days"] != summary["thresholds"]["lookback_days"]:
        raise ValueError("em.lookback_days 与 thresholds.lookback_days 不一致")
    _check_em_counts(em)

    # EM 探测对象 = 主板 Top15(否则 feasible 无意义)
    if em["n_requested"] != len(main):
        raise ValueError("em.n_requested 必须等于 main_board_top15 数(探测对象=主板 Top15)")

    if summary["feasible"]:
        if em["reasons"]:
            raise ValueError("feasible=true 却携带 em blocking reasons")
        gates = [
            em["as_of_is_valid_date"],
            em["n_requested"] > 0,
            em["n_ok"] >= MIN_EM_OK_CODES,
            em["ok_ratio"] >= MIN_EM_OK_RATIO,
            em["n_with_recent_news"] >= MIN_EM_RECENT_NEWS_CODES,
            em["n_future_leak_codes"] == 0,
            em["n_bad_date_codes"] == 0,
            em["n_bad_shape_codes"] == 0,
        ]
        if not all(gates):
            raise ValueError("feasible=true 但 em 有门未达标")


# ── 写盘(schema + consistency + production-path guard + 原子写)────────────────
def write_em_probe_summary(summary: dict, out_path: str) -> None:
    _guard_out_path(out_path)
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(summary, schema)
    validate_em_probe_summary_consistency(summary)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = str(out_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, allow_nan=False)
    os.replace(tmp, out_path)


# ── 取数薄层 + CLI(执行期;真 fetch = 用户授权 执行)──────────────────────────────
def fetch_em_news_unfiltered(codes, names_by_code, session=None) -> list[dict]:
    """probe 专用 EM 取数:与生产 `fetch_em_news` 打**同一 em 端点 / 同请求**,但返回 **normalized-but-UNFILTERED**
    条目流——保留型映射(em 原始 `date` → `published_at`),**不**做 PIT/recency 窗过滤、**不** sort/cap、空字段保留为
    空字符串、非 dict 行原样保留——使 `classify_em_code` 能真正审计 EM 端点返回的 future / stale / bad-date /
    bad-shape 质量缺陷。weekly 生产路径用过滤版 `fetch_em_news`;probe **绝不**复用它,否则 future/越窗/残缺行会在
    probe 分类前被静默丢弃、probe 永远报零泄漏(`R-ASHORT-EM-PROBE-FETCHER-FILTER-AUDIT-GAP`)。fail-closed:
    缺 name / 非 200 / JSONP 解析 / 异常 → 该码 ok:False、items:[](绝不阻断、绝不伪 reachable、不打印 key)。"""
    import json as _json
    import requests
    from urllib.parse import quote
    sess = session or requests
    headers = {"User-Agent": EM_NEWS_UA, "Accept": "application/json, text/plain, */*",
               "Referer": EM_NEWS_REFERER}
    out: list[dict] = []
    for ts_code in (codes or []):
        name = (names_by_code or {}).get(str(ts_code)) or (names_by_code or {}).get(ts_code)
        if not name:
            out.append({"ts_code": ts_code, "ok": False, "error_category": "no_name", "items": []})
            continue
        param = {"uid": "", "keyword": str(name), "type": ["cmsArticleWeb"],
                 "client": "web", "clientType": "web", "clientVersion": "curr",
                 "param": {"cmsArticleWeb": {"searchScope": "default", "sort": "default",
                                             "pageIndex": 1, "pageSize": EM_NEWS_PAGE_SIZE,
                                             "preTag": "", "postTag": ""}}}
        url = EM_NEWS_SEARCH_URL.format(param=quote(_json.dumps(param, ensure_ascii=False)))
        try:
            resp = sess.get(url, headers=headers, timeout=12)
            if resp.status_code != 200:
                cat = "anti_scrape" if resp.status_code in (403, 429) else "network"
                out.append({"ts_code": ts_code, "ok": False, "error_category": cat, "items": []})
                continue
            data = _json.loads(_strip_jsonp(resp.text))
            raw = (((data or {}).get("result") or {}).get("cmsArticleWeb")) if isinstance(data, dict) else None
            raw = raw if isinstance(raw, list) else []
            items = []
            for it in raw:
                if isinstance(it, dict):
                    # 保留型映射:em 原始 date→published_at;缺字段保留为空(由 classify 判 bad_shape),不丢弃
                    items.append({"title": str(it.get("title", "") or ""),
                                  "url": str(it.get("url", "") or ""),
                                  "published_at": str(it.get("date", "") or "")})
                else:
                    items.append(it)        # 非 dict 行原样保留 → classify 判 bad_shape
            out.append({"ts_code": ts_code, "ok": True, "error_category": None, "items": items})
        except Exception as exc:  # noqa: BLE001
            out.append({"ts_code": ts_code, "ok": False,
                        "error_category": _categorize_error(exc), "items": []})
    return out


def _load_names(spec: str) -> dict:
    """`@path.json`(JSON object {ts_code: name})或内联 `code:name,code:name`。"""
    if spec.startswith("@"):
        with open(spec[1:], "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise SystemExit("[FATAL] --names 文件须是 JSON object {ts_code: name}")
        return {str(k): str(v) for k, v in data.items()}
    out: dict[str, str] = {}
    for pair in spec.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if ":" not in pair:
            raise SystemExit(f"[FATAL] --names 项缺冒号:{pair!r}(应 code:name)")
        k, v = pair.split(":", 1)
        out[k.strip()] = v.strip()
    return out


def main(argv=None, news_fetcher=None):
    p = argparse.ArgumentParser(
        description="A-short EM(东方财富)资讯 web_llm 源可行性探针(tracked,probe-only,非生产)")
    p.add_argument("--as-of", required=True, help="YYYYMMDD")
    p.add_argument("--watch-pool", required=True,
                   help="主板 Top15 候选:逗号分隔 ts_code,或 @path 指向 JSON 数组")
    p.add_argument("--names", required=True,
                   help="ts_code→股票名映射(EM 按名搜索):@path 指向 JSON object,或 code:name,code:name")
    p.add_argument("--out", required=True, help="probe summary 落点(禁 result/a_short)")
    p.add_argument("--confirm-fetch-authorized", action="store_true",
                   help="确认用户已授权本次 EM(东方财富)真实 HTTP 探测调用")
    p.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS,
                   help=f"近期新闻窗(天,默认 {DEFAULT_LOOKBACK_DAYS})")
    args = p.parse_args(argv)

    if not args.confirm_fetch_authorized:
        raise SystemExit("[FATAL] 需 --confirm-fetch-authorized:本 probe 会真实抓取 EM 资讯,须用户授权")
    if not _is_canonical_date(args.as_of):
        raise SystemExit(f"[FATAL] --as-of {args.as_of} 不是合法日历日期")
    if not (isinstance(args.lookback_days, int) and args.lookback_days > 0):
        raise SystemExit("[FATAL] --lookback-days 须为正整数")
    _guard_out_path(args.out)              # 取数前先挡掉生产路径,别白抓

    requested = _load_watch_pool(args.watch_pool)
    names = _load_names(args.names)
    main_codes, dropped = main_board_top15(requested)
    print(f"[em-probe] universe: requested={len(requested)} → main-board Top15={len(main_codes)} "
          f"(dropped non-main={len(dropped)})")
    if not main_codes:
        print("[em-probe] WARNING: 观察池无主板代码,写 not-feasible summary")

    nf = news_fetcher or fetch_em_news_unfiltered
    em_raw = nf(main_codes, names)              # unfiltered:保留 future/stale/bad 供 classify 审计
    em = assess_em_feasibility(em_raw, args.as_of, args.lookback_days)

    universe = {"requested": requested, "main_board_top15": main_codes, "dropped_non_main": dropped}
    summary = build_em_probe_summary(universe, em, args.as_of,
                                     datetime.now().astimezone().isoformat(timespec="seconds"))
    write_em_probe_summary(summary, args.out)
    print(f"[em-probe] em: ok={em['n_ok']}/{em['n_requested']} recent_news={em['n_with_recent_news']} "
          f"future_leak={em['n_future_leak_codes']} bad_date={em['n_bad_date_codes']} "
          f"bad_shape={em['n_bad_shape_codes']} feasible={em['feasible']}")
    print(f"[em-probe] reasons={em['reasons']}")
    print(f"[em-probe] overall feasible(=em)={summary['feasible']} → summary {args.out}")


if __name__ == "__main__":
    main()
