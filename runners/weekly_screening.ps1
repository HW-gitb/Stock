# weekly_screening.ps1 — 周五实盘选股 + 数据保险一键脚本
#
# 顺序：
#   1) A-EGS\egs_main.py                       (主选股；产 data_health.json by Codex layer)
#   2) runners\data_canary.py                  (旁路跨源对账；sina 默认，VPN-agnostic)
#   3) runners\forward_tracker.py              (Phase 3.5 实盘 forward 累计；不影响主流程)
#   4) M6.7 advisory 周报(a_short_iv_feed_build + a_short_weekly_pipeline:建市场 IV feed → 跑
#                                               M6.7 pipeline,语义 cninfo+DeepSeek 行内;watch pool =
#                                               当次 EGS analysis_input;run-path 见契约 §web_llm 产出路径)
#   5) V14.3 regime 比较账本(a_short_regime_comparison_runner:旁路 sidecar,comparison-only 非生产、V14.2 冻结;
#                                               **只在实盘当天跑**(历史回放跳过——账本是 forward 累积的已结算交易日证据);
#                                               无 ledger→一次性 --bootstrap 252日回填(首跑数分钟)、有→increment ~5日;
#                                               runner 把 as_of 收敛到最新已结算交易日(盘中周一→上周五),复用本次 IV feed)
#
# 设计约束：
# - canary / tracker / semantic 在 egs_main 失败时不跑（拿不到当次 candidates，意义为零）
# - canary / tracker / semantic 自身失败不影响整体 exit code（旁路约束：不阻断选股）
# - semantic 是 advisory-only:cninfo 取数失败/反爬绝不阻断周报;落 research 非生产 lane,
#   绝不进 result/a_short、不进 production scoring/decision/veto
# - 整体 exit code 取 egs_main 的 exit code
#
# Usage:
#   .\runners\weekly_screening.ps1                                   # as-of = 今天
#   .\runners\weekly_screening.ps1 -AsOf 20260522
#   .\runners\weekly_screening.ps1 -AsOf 20260522 -CanarySource em
#   .\runners\weekly_screening.ps1 -PythonExe C:\Path\To\python.exe   # python 不在 PATH 时
#   .\runners\weekly_screening.ps1 -SkipCanary                        # 只跑选股
#   .\runners\weekly_screening.ps1 -SkipTracker                       # 不跑 forward tracker capture
#   .\runners\weekly_screening.ps1 -SkipSemanticRisk                  # skip the M6.7 advisory (semantic)
#   .\runners\weekly_screening.ps1 -Account path\to\account.json      # M6.7 account-state JSON (cash/positions/Rule12/Rule13); omit = no-sizing observation only
#   .\runners\weekly_screening.ps1 -AsOf 20260522 -L3Mode neutralize  # historical replay guard
#
# 运行 cadence(A-short 周五实盘;用户 2026-06-15 定):
#   今后跑周五实盘用「决策日 as_of + 收盘前运行」—— 周一(决策日)**收盘前**跑 `-AsOf <周一日期>`
#   (不传 -L3Mode;as_of==运行日 → 默认 l3-mode=today)。机理(已核 egs_main 代码):周一收盘前 Tushare
#   当日 EOD(daily / daily_basic / suspend)尚未生成 → egs_main「空就回退前一交易日」逻辑(get_daily_basic 等)
#   自动落到上周五,所以**选股价格/估值/停牌依据上周五收盘**;而新闻 / 语义 web·LLM 层窗口到周一、抓得到
#   周末突发利好利空。= 周五选股池 + 周末最新新闻。
#   M6.7 周报(含 EM 新闻→DeepSeek 判官)也在这同一次盘中跑里产出:本脚本给 weekly_pipeline 传 `--run-date <运行日>`,
#   当 run-date==as_of(实盘当天、as_of 当日 EOD 未发布)时**价格新鲜度门容忍最新已结算 bar=前一交易日(=上周五)**,
#   故 M6.7 不再 FATAL;新闻窗 as_of=周一 → 判到周六/周日(及任何周一早间)。历史回放(as_of≠运行日)仍严格 == as_of。
#   *必须收盘前跑*:周一**收盘后**再跑,egs_main 会用周一收盘(不再回退),选股池就变成周一而非周五。
#   确认依据周五的标志:日志出现 `daily_basic <周一> 无数据，回退至 <周五>`。
#   (非交易日 as_of 如周日不可用:egs_main 拒非交易日 → ValueError "not an A-share trading day"。)

param(
    [ValidatePattern('^\d{8}$')]
    [string]$AsOf = (Get-Date -Format 'yyyyMMdd'),
    [ValidateSet('sina', 'em')]
    [string]$CanarySource = 'sina',
    [ValidateSet('pit', 'today', 'neutralize')]
    [string]$L3Mode = $null,
    [string]$PythonExe = 'python',
    [string]$Account = $null,
    [switch]$AllowHistoricalOverwrite,
    [switch]$SkipCanary,
    [switch]$SkipTracker,
    [switch]$SkipSemanticRisk,
    [switch]$SkipRegime
)

# We rely on $LASTEXITCODE from native exes (python.exe), not PowerShell
# cmdlet error handling, so the default $ErrorActionPreference is fine —
# explicit override removed (it was cosmetic and misled readers into
# thinking it affected the Python subprocess exit semantics).
#
# $PSScriptRoot is the directory of THIS .ps1 file (runners/), so the
# project root is one level up. If this script is ever moved, update
# both the path math and the python invocations below.
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $ProjectRoot 'A-EGS\egs_main.py') -PathType Leaf)) {
    Write-Host "[FATAL] expected A-EGS\egs_main.py (as a file) under $ProjectRoot." -ForegroundColor Red
    exit 1
}
if (-not (Get-Command $PythonExe -ErrorAction SilentlyContinue)) {
    Write-Host "[FATAL] Python executable not found: $PythonExe" -ForegroundColor Red
    Write-Host "        Pass -PythonExe C:\Path\To\python.exe or add python to PATH." -ForegroundColor Red
    exit 1
}

$RunDate = Get-Date -Format 'yyyyMMdd'
$IsHistoricalAsOf = $AsOf -ne $RunDate
$EffectiveL3Mode = $L3Mode

if ([string]::IsNullOrWhiteSpace($EffectiveL3Mode)) {
    if ($IsHistoricalAsOf) {
        Write-Host "[FATAL] Historical -AsOf $AsOf is not the current run date $RunDate." -ForegroundColor Red
        Write-Host "        Pass -L3Mode pit or -L3Mode neutralize explicitly; default --l3-mode=today is blocked for historical official-output runs." -ForegroundColor Red
        exit 1
    }
    $EffectiveL3Mode = 'today'
}

if ($IsHistoricalAsOf -and $EffectiveL3Mode -eq 'today') {
    Write-Host "[FATAL] Historical -AsOf $AsOf cannot run with -L3Mode today." -ForegroundColor Red
    Write-Host "        Use -L3Mode pit for a strict PIT snapshot, or -L3Mode neutralize for an L3-neutral replay." -ForegroundColor Red
    exit 1
}

$ExistingOfficialOutputs = @()
$OfficialResultDir = Join-Path $ProjectRoot "result\a_short\$AsOf"
if (Test-Path $OfficialResultDir) {
    $ExistingOfficialOutputs += $OfficialResultDir
}
$EgsRootDir = Join-Path $ProjectRoot 'A-EGS'
$EgsResultDir = Join-Path $EgsRootDir 'Result'
@(
    (Join-Path $EgsResultDir "egs_tier1_$AsOf.csv"),
    (Join-Path $EgsResultDir "egs_full_$AsOf.csv"),
    # egs_main.py defaults xlsx output to A-EGS\ unless CONF["xlsx_dir"] is set.
    (Join-Path $EgsRootDir "egs_tier1_$AsOf.xlsx"),
    (Join-Path $EgsResultDir "egs_tier1_$AsOf.xlsx")
) | ForEach-Object {
    $Path = $_
    if (Test-Path $Path) {
        $ExistingOfficialOutputs += $Path
    }
}

if ($IsHistoricalAsOf -and $ExistingOfficialOutputs.Count -gt 0 -and -not $AllowHistoricalOverwrite) {
    Write-Host "[FATAL] Historical -AsOf $AsOf would overwrite existing official output(s):" -ForegroundColor Red
    foreach ($Path in $ExistingOfficialOutputs) {
        Write-Host "        $Path" -ForegroundColor Red
    }
    Write-Host "        Re-run only after reviewing those outputs, and pass -AllowHistoricalOverwrite if the overwrite is intentional." -ForegroundColor Red
    exit 1
}

if ($IsHistoricalAsOf -and $AllowHistoricalOverwrite) {
    Write-Host "[WARN] Historical official-output overwrite explicitly allowed for $AsOf." -ForegroundColor Yellow
}

Set-Location $ProjectRoot

Write-Host "=== Weekly screening pipeline ===" -ForegroundColor Cyan
Write-Host "as-of:         $AsOf"
Write-Host "run date:      $RunDate"
Write-Host "historical:    $IsHistoricalAsOf"
Write-Host "l3 mode:       $EffectiveL3Mode"
Write-Host "canary source: $CanarySource"
Write-Host "skip canary:   $SkipCanary"
Write-Host "skip tracker:  $SkipTracker"
Write-Host "skip semantic: $SkipSemanticRisk"
Write-Host ""

# --- Stage 1: egs_main ---
$EgsArgs = @('A-EGS\egs_main.py', '--as-of', $AsOf, '--l3-mode', $EffectiveL3Mode)
if ($EffectiveL3Mode -eq 'pit') {
    $EgsArgs += '--l3-pit-strict'
}

Write-Host "[1/4] Running $PythonExe $($EgsArgs -join ' ') ..." -ForegroundColor Yellow
& $PythonExe @EgsArgs
$EgsExitCode = $LASTEXITCODE
if ($null -eq $EgsExitCode) { $EgsExitCode = 1 }

if ($EgsExitCode -ne 0) {
    Write-Host ""
    Write-Host "[SKIP] egs_main exit $EgsExitCode -> skipping canary + tracker + semantic (no fresh candidates)" -ForegroundColor Red
    exit $EgsExitCode
}

# --- Stage 2: data_canary ---
if ($SkipCanary) {
    Write-Host ""
    Write-Host "[2/4] -SkipCanary set, canary not run" -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Host "[2/4] Running runners\data_canary.py --as-of $AsOf --source $CanarySource ..." -ForegroundColor Yellow
    & $PythonExe runners\data_canary.py --as-of $AsOf --source $CanarySource
    $CanaryExitCode = $LASTEXITCODE
    if ($null -eq $CanaryExitCode) { $CanaryExitCode = 1 }

    $CanaryLog = Join-Path $ProjectRoot "logs\data_canary_$AsOf.json"
    if (Test-Path $CanaryLog) {
        try {
            $CanaryPayload = Get-Content -Raw -Encoding UTF8 $CanaryLog | ConvertFrom-Json
            Write-Host "[ADVISORY] data_canary status=$($CanaryPayload.status); sidecar only, not a data-pass and not a ship-gate signal. Log: $CanaryLog" -ForegroundColor Yellow
        } catch {
            Write-Host "[ADVISORY] data_canary log exists but could not be parsed; sidecar only, not a data-pass and not a ship-gate signal. Log: $CanaryLog" -ForegroundColor Yellow
        }
    } else {
        Write-Host "[ADVISORY] data_canary log not found; sidecar only, not a data-pass and not a ship-gate signal." -ForegroundColor Yellow
    }

    if ($CanaryExitCode -ne 0) {
        # canary 本身设计为永远 exit 0；非 0 说明 Python 进程崩了，不是数据问题
        # 仍然不让它影响主流程退出码（旁路约束）
        Write-Host "[WARN] canary process exit $CanaryExitCode (unexpected; check logs/data_canary_$AsOf.json)" -ForegroundColor Yellow
    }
}

# --- Stage 3: forward_tracker capture ---
if ($SkipTracker) {
    Write-Host ""
    Write-Host "[3/4] -SkipTracker set, forward tracker not run" -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Host "[3/4] Running runners\forward_tracker.py capture --as-of $AsOf ..." -ForegroundColor Yellow
    & $PythonExe runners\forward_tracker.py capture --as-of $AsOf
    $TrackerExitCode = $LASTEXITCODE
    if ($null -eq $TrackerExitCode) { $TrackerExitCode = 1 }

    if ($TrackerExitCode -ne 0) {
        # tracker capture 失败不影响主流程退出码（旁路约束）。
        # 失败原因通常是 analysis_input.json 缺失或 Python 异常，不是数据问题。
        Write-Host "[WARN] forward_tracker exit $TrackerExitCode (check logs/forward_tracker.csv)" -ForegroundColor Yellow
    }
}

# --- Stage 4: M6.7 advisory weekly report (Slice 3b-2: replaces the standalone semantic-risk summary
#     sidecar; ONE Friday entry now also runs the M6.7 pipeline with semantic [cninfo official + DeepSeek
#     web] rendered inline). 旁路约束(同 canary/tracker):advisory-only,失败绝不阻断周报;落 research 非生产
#     lane(禁 result/a_short)。真取数:IV options + 前复权价 + cninfo + em 资讯(web 源)+ DeepSeek。web 源 = em(取代失效 sina);run-path 见契约 §web_llm 产出路径。
if ($SkipSemanticRisk) {
    Write-Host ""
    Write-Host "[4/4] -SkipSemanticRisk set, M6.7 advisory not run" -ForegroundColor DarkGray
} else {
    Write-Host ""
    $SemAnalysisInput = Join-Path $ProjectRoot "result\a_short\$AsOf\analysis_input.json"
    if (-not (Test-Path $SemAnalysisInput)) {
        Write-Host "[WARN] M6.7 advisory skipped: analysis_input not found at $SemAnalysisInput (advisory sidecar, weekly not blocked)" -ForegroundColor Yellow
    } else {
        $M67Dir = Join-Path $ProjectRoot "research\results\a_short\$AsOf"
        $IvFeed = Join-Path $ProjectRoot "research\results\a_short\iv_feed_$AsOf\iv_feed.json"
        $M67Out = Join-Path $M67Dir "weekly_m67.json"
        $OverlayPath = Join-Path $ProjectRoot "result\a_short\$AsOf\overlay.json"
        Write-Host "[4/4] Building market IV feed: runners\a_short_iv_feed_build.py --as-of $AsOf ..." -ForegroundColor Yellow
        & $PythonExe runners\a_short_iv_feed_build.py --as-of $AsOf --out $IvFeed --confirm-fetch-authorized
        $IvExitCode = $LASTEXITCODE
        if ($null -eq $IvExitCode) { $IvExitCode = 1 }
        if ($IvExitCode -ne 0 -or -not (Test-Path $IvFeed)) {
            Write-Host "[WARN] M6.7 advisory skipped: IV feed build failed (exit $IvExitCode; advisory sidecar, weekly not blocked)" -ForegroundColor Yellow
        } else {
            $M67Args = @('runners\a_short_weekly_pipeline.py', '--as-of', $AsOf, '--run-date', $RunDate, '--analysis-input', $SemAnalysisInput, '--iv-feed', $IvFeed, '--out', $M67Out, '--confirm-fetch-authorized')
            if (-not $IsHistoricalAsOf) {
                # 实盘当天(as_of==运行日):as_of 当日 EOD 盘中尚未发布 → 显式启用价格门 intraday tolerance
                # (容忍最新已结算 bar=前一交易日);历史回放保持默认 strict_as_of。实际价格时钟记进 weekly_m67 lineage。
                $M67Args += @('--price-freshness-mode', 'intraday_prior_settled')
            }
            if (Test-Path $OverlayPath) { $M67Args += @('--overlay', $OverlayPath) }
            $RunM67 = $true
            if ($Account) {
                if (Test-Path $Account) {
                    $M67Args += @('--account', $Account)
                } else {
                    # bad -Account path: refuse to silently run sizing-less M6.7 (skip, not a misleading 观察 artifact)
                    Write-Host "[WARN] M6.7 advisory skipped: -Account path not found: $Account (refusing to run sizing-less with a bad account path; fix the path, or omit -Account for observation-only)" -ForegroundColor Yellow
                    $RunM67 = $false
                }
            } else {
                Write-Host "[WARN] M6.7 no -Account: observation-only (no position sizing/holding-state). The weekly_m67 artifact is marked sizing_mode=observation_only_no_account - 建仓 candidates render as 观察 (sizing artifact, NOT a real avoid signal). Pass -Account <account-state.json> (cash/positions/Rule12/Rule13) for real sizing and holding-state decisions." -ForegroundColor Yellow
            }
            if ($RunM67) {
                Write-Host "[4/4] Running M6.7 pipeline: runners\a_short_weekly_pipeline.py --as-of $AsOf ..." -ForegroundColor Yellow
                & $PythonExe @M67Args
                $M67ExitCode = $LASTEXITCODE
                if ($null -eq $M67ExitCode) { $M67ExitCode = 1 }
                if ($M67ExitCode -ne 0) {
                    # 真取数失败(IV/价/cninfo/em/DeepSeek)不影响主流程退出码(旁路约束:advisory 绝不阻断选股)
                    Write-Host "[WARN] M6.7 advisory exit $M67ExitCode (advisory sidecar; real-fetch/cninfo/DeepSeek failure does NOT block the weekly)" -ForegroundColor Yellow
                } else {
                    Write-Host "[ADVISORY] M6.7 weekly report (semantic inline) -> $M67Out. Standalone summary sidecar retired (Slice 3b-2); advisory-only, not a veto/ship-gate." -ForegroundColor Yellow
                }
            }
        }
    }
}

# --- Stage 5: V14.3 regime comparison ledger (旁路 sidecar;comparison-only 非生产,V14.2 仍冻结;失败绝不阻断
#     周报)。只在实盘当天(as_of==运行日)跑——regime ledger 是 forward 累积的已结算交易日证据,历史回放不该推进它。
#     无 ledger→一次性 --bootstrap(252日回填,首跑数分钟)、有→increment(秒级)。runner 把 as_of 收敛到最新已结算
#     交易日(盘中周一→上周五),复用本次已建的 IV feed(有则传)。egs 成功才会走到这(egs 失败已在上面 exit)。
if ($SkipRegime) {
    Write-Host ""
    Write-Host "[regime] -SkipRegime set, V14.3 regime comparison not run" -ForegroundColor DarkGray
} elseif ($IsHistoricalAsOf) {
    Write-Host ""
    Write-Host "[regime] historical -AsOf $AsOf -> skipping V14.3 regime ledger (only live runs advance the forward regime evidence)" -ForegroundColor DarkGray
} else {
    Write-Host ""
    $RegimeLedger = Join-Path $ProjectRoot "research\results\a_short\regime_daily_ledger.json"
    $RegimeIvFeed = Join-Path $ProjectRoot "research\results\a_short\iv_feed_$AsOf\iv_feed.json"
    $RegimeArgs = @('runners\a_short_regime_comparison_runner.py', '--as-of', $AsOf, '--confirm-fetch-authorized')
    if (-not (Test-Path $RegimeLedger)) {
        Write-Host "[regime] no existing ledger -> one-time --bootstrap (252-day backfill; may take several minutes)" -ForegroundColor Yellow
        $RegimeArgs += '--bootstrap'
    } else {
        Write-Host "[regime] existing ledger found -> incremental append (settled trading days since last)" -ForegroundColor Yellow
    }
    if (Test-Path $RegimeIvFeed) { $RegimeArgs += @('--iv-feed', $RegimeIvFeed) }
    Write-Host "[5/5] Running $PythonExe $($RegimeArgs -join ' ') ..." -ForegroundColor Yellow
    & $PythonExe @RegimeArgs
    $RegimeExitCode = $LASTEXITCODE
    if ($null -eq $RegimeExitCode) { $RegimeExitCode = 1 }
    if ($RegimeExitCode -ne 0) {
        # 真取数失败(daily/stk_limit/指数/IV)不影响主流程退出码(旁路约束:comparison-only 绝不阻断选股)
        Write-Host "[WARN] V14.3 regime comparison exit $RegimeExitCode (advisory sidecar; comparison-only, does NOT block the weekly)" -ForegroundColor Yellow
    } else {
        Write-Host "[ADVISORY] V14.3 regime comparison ledger updated (non-production; V14.2 frozen)." -ForegroundColor Yellow
    }
}

Write-Host "=== Pipeline done ===" -ForegroundColor Cyan
exit 0
