"""实盘 tushare 健康检查探针(最小 · 只读 · 不落盘 · 不打印 token · HTTPS-only)。

用途: 实盘环境(有 TUSHARE_TOKEN)跑 `python runners/tushare_health_probe.py`,确认 **weekly pipeline
真取数路径**是否健康。weekly 真取数走 `runners.a_short_iv_feed_probe.init_tushare_pro`——它 pin DataApi
base url 到 `https://api.tushare.pro/dataapi`(绕过 tushare 1.4.29 默认 waditu/503 静默空)。本探针 A 段
**复用同一 pinned 路径**,故诊断的就是 weekly 真实层(不会冤枉 raw 未 pin 的 `ts.pro_api`)。

判定: health = 必需列齐 + known-good(`trade_cal` 固定历史日,必有行)**非空行**——有列但 0 行不算健康
(防 false-OK,正是要抓"包静默返回空")。B 段 HTTPS 直连对照仅在 weekly path 异常时区分 token/网络/权限,
**绝不向非 HTTPS 端点发 token**(AGENTS 安全:secret 不明文传输)。token 取 env、不打印;不写文件、不改状态。
退出码: 0=健康 / 1=异常(看诊断) / 2=前置缺失。**真网络调用须先 Codex 审过本探针**(见 register)。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# weekly 真取数关键接口 + 必需列(broken 包返回无列空表 → 列不齐 → 不健康)
_PKG_CALLS = [
    ("trade_cal", {"start_date": "20260101", "end_date": "20260105"}),
    ("share_float", {"ts_code": "600000.SH"}),
    ("disclosure_date", {"ts_code": "600000.SH", "end_date": "20251231"}),
]
_REQUIRED_COLS = {
    "trade_cal": {"cal_date", "is_open"},
    "share_float": {"ann_date", "float_date"},
    "disclosure_date": {"ann_date", "pre_date"},
}
_KNOWN_GOOD = "trade_cal"   # 固定历史日期必有行 → 健康锚(0 行=端点不通,非"真无数据")
# B 段对照端点: 与 weekly pinned base 一致(HTTPS),仅用于异常时区分 token/网络/权限
_HTTPS_BASE = os.environ.get("TUSHARE_BASE_URL", "https://api.tushare.pro/dataapi")


def _pkg_health(df, api):
    """(健康?, 行数)。健康 = 必需列齐 + (known-good 接口)非空行;有列但 0 行的 known-good 不算健康(防 false-OK)。
    数据接口(share_float/disclosure_date)只验列齐(rows 可能真为 0=该票无记录)。"""
    if df is None:
        return False, 0
    _cols = getattr(df, "columns", None)   # 真 pandas df.columns 是 Index;不能 `or []`(bool(Index) ambiguous)
    cols = set(_cols) if _cols is not None else set()
    rows = len(df)
    cols_ok = _REQUIRED_COLS[api].issubset(cols)
    if api == _KNOWN_GOOD:
        return (cols_ok and rows > 0), rows
    return cols_ok, rows


def _verdict(pkg_health, http_kg_ok):
    """纯判定(可测,no-network)。pkg_health={api:(ok,rows)};http_kg_ok=bool|None(known-good HTTPS 直连是否成功)。
    返回 (label, exit_code)。**所有关键接口(trade_cal+share_float+disclosure_date)都健康才 OK**——任一坏(无列
    空表/列不齐)都不算健康,防"trade_cal 好但解禁/财报接口坏仍 rc=0";否则按 HTTPS 对照区分 pin/包问题 vs token/网络。"""
    if all(pkg_health.get(k, (False, 0))[0] for k, _ in _PKG_CALLS):
        return "OK", 0
    if pkg_health.get(_KNOWN_GOOD, (False, 0))[0]:
        return "CRITICAL-API-BROKEN", 1   # known-good 通(pin/token/网络好)但解禁/财报接口缺列 → 特定接口坏,非 pin/网络
    if http_kg_ok is True:
        return "PINNED-PATH-EMPTY", 1
    if http_kg_ok is False:
        return "CHECK-TOKEN-NET", 1
    return "UNKNOWN", 1


def _require_https(url):
    """绝不向非 HTTPS 端点发送 token(AGENTS 安全:secret 不明文传输)。非 https → 抛,调用方在发请求前即被拦。"""
    if not str(url).lower().startswith("https://"):
        raise ValueError(f"[FATAL] 拒绝向非 HTTPS 端点发送 token: {url!r}")


def _http_known_good(token, base_url, post=None):
    """HTTPS 直连 known-good 接口对照(绕过 tushare 包,验 token/网络/权限)。`post` 可注入便于 no-network 测试。
    返回 bool(成功有数据)|None(异常)。base_url 必须 HTTPS,否则 `_require_https` 在发请求前抛。"""
    _require_https(base_url)
    if post is None:
        import requests
        post = requests.post
    url = f"{base_url.rstrip('/')}/{_KNOWN_GOOD}"
    try:
        r = post(url, json={"api_name": _KNOWN_GOOD, "token": token,
                            "params": dict(_PKG_CALLS[0][1]), "fields": ""}, timeout=20)
        j = r.json()
        return (getattr(r, "status_code", None) == 200 and j.get("code") == 0
                and len((j.get("data") or {}).get("items") or []) > 0)
    except Exception:
        return None


def main(token=None, pro=None, http_kg=None):
    """token/pro/http_kg 可注入便于 no-network 测试;默认从 env + init_tushare_pro + 真 HTTPS。"""
    if token is None:
        token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        print("[FATAL] TUSHARE_TOKEN 未设置(环境变量)。在实盘环境设好后重跑。")
        return 2
    print("TUSHARE_TOKEN: set(值不显示)")

    # A. weekly pinned path(复用 init_tushare_pro)——诊断的就是 weekly 真实取数层
    if pro is None:
        try:
            from runners.a_short_iv_feed_probe import init_tushare_pro
            pro = init_tushare_pro(token)
        except Exception as e:
            print(f"[FATAL] init_tushare_pro 失败(weekly pinned 初始化): {type(e).__name__} {e}")
            return 2
    print("\n--- A. weekly pinned path (init_tushare_pro → https://api.tushare.pro/dataapi) ---")
    pkg_health = {}
    for api, kw in _PKG_CALLS:
        try:
            df = getattr(pro, api)(**kw)
            ok, rows = _pkg_health(df, api)
            pkg_health[api] = (ok, rows)
            cols = list(getattr(df, "columns", [])) if df is not None else None   # 不 `or []`(pandas Index bool ambiguous)
            print(f"  {api}: cols={cols} rows={rows} health={ok}")
        except Exception as e:
            pkg_health[api] = (False, 0)
            print(f"  {api}: EXC {type(e).__name__} | {str(e)[:200]}")

    # B. HTTPS 直连 known-good 对照(仅 weekly path 异常时;绝不明文发 token)
    if http_kg is None and _verdict(pkg_health, None)[0] != "OK":
        print("\n--- B. HTTPS 直连 known-good 对照(token/网络/权限) ---")
        http_kg = _http_known_good(token, _HTTPS_BASE)
        print(f"  {_KNOWN_GOOD} via HTTPS({_HTTPS_BASE}): ok={http_kg}")

    label, code = _verdict(pkg_health, http_kg)
    print("\n--- 诊断 ---")
    unhealthy = [k for k, _ in _PKG_CALLS if not pkg_health.get(k, (False, 0))[0]]
    if unhealthy:
        print(f"不健康接口(无列空表/列不齐/known-good 0 行): {unhealthy}")
    print({
        "OK": "[OK] weekly pinned 真取数正常(forward_events 第1/2刀及价格/解禁/财报取数会工作)。",
        "CRITICAL-API-BROKEN": ("[CRITICAL-API-BROKEN] trade_cal 通(pin/token/网络好)但 share_float/disclosure_date "
                                "缺列 → 解禁/财报取数会拿空;排查这些接口权限(积分)或 tushare 版本(见上方不健康接口)。"),
        "PINNED-PATH-EMPTY": ("[PINNED-PATH-EMPTY] weekly pinned 路径连 known-good 都拿不到,但 HTTPS 直连正常 → "
                              "pin 失效或包更深问题;排查 init_tushare_pro / TUSHARE_BASE_URL / tushare 版本。"),
        "CHECK-TOKEN-NET": "[CHECK-TOKEN-NET] HTTPS 直连也失败 → token 无效 / 接口无权限(积分) / 网络不可达。",
        "UNKNOWN": "[UNKNOWN] 无法判定,逐项看上方 cols/rows/ok。",
    }[label])
    return code


if __name__ == "__main__":
    sys.exit(main())
