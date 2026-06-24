# -*- coding: utf-8 -*-
"""Anti-bloat guard for `docs/README.md` route rows (位置无关机械守护).

存在目的: README 是导航路由表, 不是第二份规则书 / 契约书。每条路由行的**描述列 (col1)** 必须是薄指针
(topic + 一句话 + 文件); 细节去 owner doc / module docstring / tests / register。光靠 AGENTS.md 文字规范
未来一定会逐刀重新膨胀 (本仓多次实证), 所以用这道**行长 guard** 焊死: 任何路由行 col1 超过 ``COL1_CAP``
就 CI 红 —— 不管哪个 LLM、哪条 lane、未来哪一刀。

行解析按**未转义 ``|``** 切列: Markdown 允许 cell 内**转义管道 ``\\|``**(渲染成字面竖线, 如数学 ``|NI|``);
naive ``str.split('|')`` 会在 ``\\|`` 处误切、**UNDER-count col1**, 让真 over-cap 行漏过(fail-open,
``R-README-ROUTE-ROW-LENGTH-ESCAPED-PIPE-BYPASS``)。col2 文件列从不限长。

当前已存在的 over-cap 行 (a_short / a_long 设计已完成·文档不动 + Phase provider-evidence 历史 + Production
EGS 生产配置 = 用户接受的**稳定历史行**) 经 ``GRANDFATHERED_OVERCAP_ROWS`` (整行 sha256) 放行: 旧行**原样
不动**即过; 一旦有人**改**那行 (hash 变) 就必须压到 cap (= 谁动旧胖行谁顺手压, 增量清理)。新增行 / 已压的
US-short / US-long 行 / 任何非 grandfather 的 over-cap 行都必须满足 cap。

grandfather set 是**实现时机器扫描当前 README 的 over-cap 行** (修正 parser 后) 得到的 (不是凭口头假设
"只含 a_short/a_long" —— 实测含 Phase / Production 两条非 a_short/a_long 旧胖行 + 1 条转义管道 a_long 行,
口头假设会漏放), 2026-06-24 US-long 压缩 + escaped-pipe parser 修复后捕获: 5 A-long + 26 A-short + 1 Phase +
1 Production = 33 行。
"""
import hashlib
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

README_PATH = ROOT / "docs" / "README.md"
COL1_CAP = 350  # max chars of a route row's stripped description cell (col1) — a thin pointer fits well under this
_SPLIT_UNESCAPED = re.compile(r"(?<!\\)\|")  # split on UNESCAPED pipes only (an escaped \| is a literal pipe in a cell)

# sha256 of each currently-accepted OVER-CAP route row (整行), captured 2026-06-24 after US-long compression +
# escaped-pipe parser fix by machine-scanning README. All are stable historical rows the user keeps un-touched: 5
# A-long + 26 A-short + 1 Phase (provider-evidence 历史) + 1 Production (EGS industry_heat 生产配置). A grandfathered
# row passes ONLY while byte-identical; editing it (hash changes) forces compliance with the cap. To compress one
# later, drop its hash.
GRANDFATHERED_OVERCAP_ROWS = frozenset({
    "02150176fbf7870dc1cb64724a6565e92950d19c532de71b1ebab45a882793b6",
    "97d8db3b7a2304246541014b4c11ca104909707141143afa379c891b2d2d5974",
    "6ee63422c5765259dcd52c6b8216a9d1ebd03293783d013b54410a396cf8b621",
    "39c27792f698a37932e138eb8753d6abe3a24c32a3e19010025a9de3fa0a2f73",
    "f907758927e2fa6f04ca08b9f311b639e2e363ba48e423028f5c95315c33da2d",
    "2f737b1c8fb48cda41693933468c71bc63e190760eff7587f3737ffac27ad6aa",
    "f5e220a565b4d0a93a0624479ac1c65ad1402296e44694a7373eed2e2ae93bce",
    "fd5877db863cefb96f4850aad4bc226e6556c3888c69cfa73a84050c36f36570",
    "ededd8c440a22f7604a844e100ec6f31cfc81c179242f507b4222f701d52032b",
    "14be0e230d91b1d622655abfc2130bc817cd3aa1ae4d737974f4c67de1b0e854",
    "0eda0a2d79addf693b4e1b14e383df4a6095d6394e95da5e03d3fa27a5d7baec",
    "97021be6016739e676e8c34987dbd48ef869ed3c20f7394cd5f8cc0d9819f438",
    "f04caa0e2196995290d450998401b227ffb8e88e75c34eacf0abfe5749f56573",
    "198353c3796a3aa9189d4d73b19b9386dc1d06ee80f94be2a8dfad7c5bb63130",
    "5cde0f95f824f90b4c84e89f0b83052ed682d2742e15ba5792ed140a0542a169",
    "1e90d8ae7b4d1fa7ffb36db2cdc568f77140e893b98208fa52b90aeb4796bfff",
    "4ee2aaf6a16fe5e111596b3c47fa53bcd8437f278583b7b38543b64f99fd5ba1",
    "f19e228c6d5693fbc244759d1353ccc1510b1669ab32d48c8db4fcfa6d3f8232",
    "b52021903cc4ff92554bd146c8242f940defbec9e81d0045dab8c5dcb866ded7",
    "d1c7f2dcb4651cc74b1cd16605792ed20633d5354f887eaa3b12d078bc508104",
    "c14e03e1ef3bf3f4c4d6ea71d05115e97da35e0e2fac83ddf8fe4cabcdf51b48",
    "798f3c1747ef1f05213c2bc097c5e482f3e0992d9659738cc56892d81ce5520e",
    "14f2f689d000f1b1904279289cf98ab2721a527ac82919147253c5955cefd7b2",
    "90e7532fc801e8224136f30e93827ef751987fad3d5d8d7fc8cbf5e4f4297551",
    "6286f9a0f0fba46efc7221349b4247b67c5e6323a31fed0d5bc5d584e19146f4",
    "96f951baf7258964169231785c6729e5cc6b5a1f49aa351681e9c1684dc02559",
    "43731d9a52ab644f76d267b469dca8b74b05bf4fd517c6bdd88d9b089773e301",
    "6fa95b30cec1a5a28935973649655a9ab21b4c076f5fa219a3ec311e8e562516",
    "aeeac110036aabdeceb9567118b53fa963aca9fc910461c7fcb274912b144b25",
    "47325f9e15cb2dd9e39131132d86ef8401ad80d6a585a9f77fd93606353d1eb2",
    "7b15456b11de6f2f065ed61903ddda0b437dc7d51084c43fbba4614cc5169473",
    "dea34613eb66d335f5b6f4e7d2b72d7242735d71f1ad5c131376b7f9f1b0d114",
    "d0ebd88b1a458c5f878d27a942ab05b5f170337c82a5b0e051c8dde559c0505f",
})


def _overcap_offenders(text):
    """Return ``[(col1_len, col1_preview), ...]`` for routing rows whose stripped description cell (col1) exceeds
    ``COL1_CAP`` AND are NOT grandfathered (整行 sha256 not in the accepted-historical set). A routing data row =
    a line that — after stripping leading whitespace — starts with ``|`` (covers INDENTED rows and ``|col1|`` with
    no space after the pipe) and has at least 2 cells; cells are split on UNESCAPED ``|`` (an escaped ``\\|`` is a
    literal pipe INSIDE a cell, so col1 is never under-counted by a stray pipe). The header ``| Need | Read |`` /
    ``|---|---|`` separator are short and pass the cap anyway. col2 (the file-pointer column) is NEVER measured —
    its length varies with file count."""
    offenders = []
    for ln in text.splitlines():
        if not ln.lstrip().startswith("|"):   # a Markdown table row may be INDENTED (≤3 leading spaces) and/or have
            continue                          # NO space after the leading pipe (|col1|) — robust detection covers both
        cells = _SPLIT_UNESCAPED.split(ln)   # split the ORIGINAL line on UNESCAPED pipes; leading indent → cells[0],
        # so col1 = cells[1] regardless of indent / no-space; '| a | b |' or '  |a|b|' → cells[1] is col1
        if len(cells) < 3:
            continue
        col1 = cells[1].strip()
        if len(col1) <= COL1_CAP:
            continue
        if hashlib.sha256(ln.encode("utf-8")).hexdigest() in GRANDFATHERED_OVERCAP_ROWS:
            continue               # accepted stable historical row, un-touched → grandfathered
        offenders.append((len(col1), col1[:70]))
    return offenders


class ReadmeRouteRowLength(unittest.TestCase):
    def test_current_readme_clean(self):
        """The committed README: every over-cap route row is grandfathered, everything else is a thin pointer."""
        offenders = _overcap_offenders(README_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            offenders, [],
            "README route rows over the %d-char col1 cap that are NOT grandfathered — compress to a thin pointer "
            "(topic + 文件 + 一句话; 细节 → owner doc / module docstring / tests / register): %r" % (COL1_CAP, offenders))

    def test_new_overcap_row_is_caught(self):
        """A NEW (non-grandfathered) bloated route row fails the guard (the anti-future-膨胀 point)."""
        fat = "| US-short new feature — " + ("详述" * 200) + " | `engine/x.py` |"
        self.assertTrue(_overcap_offenders(fat), "a new over-cap route row must be flagged")

    def test_no_space_after_pipe_overcap_caught(self):
        """R-README-ROUTE-ROW-LENGTH-TABLE-ROW-DETECTION-BYPASS: a valid Markdown row with NO space after the
        leading pipe (|col1|) must not bypass detection."""
        fat = "|US-short no-space — " + ("详" * 400) + "|`engine/x.py`|"
        self.assertTrue(_overcap_offenders(fat), "a |col1| (no-space-after-pipe) over-cap row must be flagged")

    def test_indented_overcap_caught(self):
        """R-README-ROUTE-ROW-LENGTH-TABLE-ROW-DETECTION-BYPASS: a valid Markdown row with leading indentation
        must not bypass detection."""
        fat = "   | US-short indented — " + ("详" * 400) + " | `engine/x.py` |"
        self.assertTrue(_overcap_offenders(fat), "an indented over-cap row must be flagged")

    def test_no_space_and_indented_thin_pass(self):
        """Positive control: thin rows that are indented or have no space after the leading pipe still pass."""
        self.assertEqual(_overcap_offenders("|US-short thin no-space — 一句话|`engine/x.py`|"), [])
        self.assertEqual(_overcap_offenders("  | US-short thin indented — 一句话 | `engine/x.py` |"), [])

    def test_thin_row_passes(self):
        thin = "| US-short new — `do_x` 干 X, 一句话不变式 | `engine/x.py`, `tests/test_x.py` |"
        self.assertEqual(_overcap_offenders(thin), [])

    def test_file_heavy_thin_description_passes(self):
        """A row with a SHORT col1 but a LONG col2 (many files) passes — only col1 is capped, never the file list."""
        row = "| US-short short topic — 一句话 | " + ", ".join("`engine/f%d.py`" % i for i in range(40)) + " |"
        self.assertEqual(_overcap_offenders(row), [])

    def test_escaped_pipe_not_undercounted(self):
        """R-README-ROUTE-ROW-LENGTH-ESCAPED-PIPE-BYPASS: an escaped pipe (\\|, a literal pipe inside a cell, e.g.
        math |NI|) must NOT be treated as a cell boundary — else col1 is UNDER-counted and a real over-cap row
        escapes. A NEW over-cap row whose col1 carries an escaped pipe must still be flagged at its TRUE length."""
        fat = "| A-new factor — " + ("详" * 400) + r" 含 \|abs\| 转义 | `engine/x.py` |"
        offs = _overcap_offenders(fat)
        self.assertTrue(offs, "an over-cap row with an escaped pipe must still be flagged (col1 not under-counted)")
        self.assertGreater(offs[0][0], COL1_CAP)   # the measured col1 length is the TRUE (post-escape) length

    def test_thin_escaped_pipe_row_passes(self):
        """Positive control: a SHORT row that legally contains an escaped pipe (\\|) is NOT false-flagged — the
        escaped-pipe-aware parser keeps it as ONE col1 cell and measures it under the cap."""
        thin = "| A-short factor — `f` abs " + r"\|x\|" + " 残差正交一次 | `engine/f.py`, `tests/test_f.py` |"
        self.assertEqual(_overcap_offenders(thin), [])

    def test_real_escaped_pipe_row_measured_and_grandfathered(self):
        """The real README escaped-pipe row (a_long cash_conversion, true col1 ~463) is now correctly measured as
        over-cap (was mis-measured ~95 by str.split) AND grandfathered, so it passes un-touched."""
        text = README_PATH.read_text(encoding="utf-8")
        row = next((ln for ln in text.splitlines() if ln.startswith("| ") and "\\|" in ln), None)
        self.assertIsNotNone(row, "expected the README escaped-pipe row to exist")
        col1 = _SPLIT_UNESCAPED.split(row)[1].strip()
        self.assertGreater(len(col1), COL1_CAP)        # correctly measured as over-cap (not under-counted)
        self.assertEqual(_overcap_offenders(row), [])  # grandfathered → passes (not an offender)

    def test_grandfathered_row_edit_breaks_pass(self):
        """A grandfathered over-cap row passes un-touched, but EDITING it (hash changes) forces the cap."""
        text = README_PATH.read_text(encoding="utf-8")
        overcap = next((ln for ln in text.splitlines()
                        if ln.startswith("| ") and len(_SPLIT_UNESCAPED.split(ln)) >= 3
                        and len(_SPLIT_UNESCAPED.split(ln)[1].strip()) > COL1_CAP), None)
        self.assertIsNotNone(overcap, "expected at least one grandfathered over-cap row in README")
        self.assertEqual(_overcap_offenders(overcap), [])                 # un-touched → grandfathered, passes
        self.assertTrue(_overcap_offenders(overcap + " EDIT"), "editing a grandfathered over-cap row must force the cap")


if __name__ == "__main__":
    unittest.main()
