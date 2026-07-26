# weekly_screening.ps1 — 周五实盘选股 + 数据保险一键脚本
#
# 顺序：
#   1) A-EGS\egs_main.py                       (主选股；产 data_health.json by Codex layer)
#   2) runners\data_canary.py                  (旁路跨源对账；sina 默认，VPN-agnostic)
#   3) runners\forward_tracker.py              (Phase 3.5 实盘 forward 累计；不影响主流程)
#   3b) a_short_crash_veto_tracker.py          (旁路冻结闪崩否决名单，补算5/10交易日并写大白话结论；不改选股)
#   4) M6.7 authoritative operation 周报(a_short_iv_feed_build + a_short_weekly_pipeline:建市场 IV feed → 跑
#                                               M6.7 pipeline,语义 cninfo+DeepSeek 行内;watch pool =
#                                               当次 EGS analysis_input;run-path 见契约 §web_llm 产出路径)
#   5) V14.3 regime 比较账本(a_short_regime_comparison_runner:旁路 sidecar,comparison-only 非生产、V14.2 冻结;
#                                               **只在 live 运行跑**(as_of>=运行日:今日 或 前瞻 canonical;真·过去回放 as_of<运行日 跳过——账本是 forward 累积的已结算交易日证据);
#                                               无 ledger→一次性 --bootstrap 252日回填(首跑数分钟)、有→increment ~5日;
#                                               runner 把 as_of 收敛到最新已结算交易日(盘中周一→上周五),复用本次 IV feed)
# 设计约束：
# - canary / tracker / M6.7 在 egs_main 失败时不跑（拿不到当次 candidates，意义为零）
# - canary / tracker 自身失败不影响整体 exit code（旁路约束：不阻断选股）
# - M6.7 内的 semantic 证据仍是 advisory-only，不进 production scoring/veto；但调用方既已请求
#   M6.7，则 analysis/IV/account/pipeline 任一失败必须写 failed receipt 并以非零退出，不能假装周报成功
# - 未请求 M6.7 时整体 exit code 取 egs_main；请求后还必须包含 M6.7 成功
#
# Usage:
#   .\runners\weekly_screening.ps1                                   # 省略 -AsOf = 自动解析 canonical(即将到来/当前未收盘的交易日)
#   .\runners\weekly_screening.ps1 -AsOf 20260522                    # 显式决策日(前瞻 live 或真·过去 historical)
#   .\runners\weekly_screening.ps1 -AsOf 20260522 -CanarySource em
#   .\runners\weekly_screening.ps1 -PythonExe C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe   # 可省略；传值仅校验固定主 Python
#   .\runners\weekly_screening.ps1 -SkipCanary                        # 只跑选股
#   .\runners\weekly_screening.ps1 -SkipTracker                       # 不跑 forward tracker capture
#   .\runners\weekly_screening.ps1 -SkipSemanticRisk                  # 跳过【整个】M6.7 operation 周报(IV/价/account/语义全跳;非仅 semantic — Slice 3b-2 起语义已行内化)
#   .\runners\weekly_screening.ps1 -Account state\a_short\account_bundle.json # a_short_account_bundle generated from the five manual CSV tables; omit = no-sizing observation only
#                                                                     # 带 -Account 报告含真实持仓 → 自动落 gitignored 私密目录 state\a_short\weekly_private\<as_of>\(防提交泄漏);无 -Account 走标准 research lane
#   .\runners\weekly_screening.ps1 -RegulatoryConfirmations path\to\candidate.json # 可选候选域监管确认；精确转发至 M6.7
#   .\runners\weekly_screening.ps1 -Account state\a_short\account_bundle.json -HoldingRegulatoryConfirmations path\to\holding.json # 可选私有持仓域确认
#   .\runners\weekly_screening.ps1 -AsOf 20260522 -L3Mode neutralize  # historical replay guard
#
# 运行 cadence(A-short 周实盘;用户 2026-06-15 定方向 / 2026-06-22 加 canonical 解析器放宽窗口):
#   **窗口内任意时刻跑都收敛到同一个决策日**——周五收盘后 → 周一收盘前 的任何时刻(含周六/周日)跑,
#   都自动解析到「即将到来/当前未收盘的交易日」(正常周 = 即将到来的周一)。直接 `.\weekly_screening.ps1`
#   省略 -AsOf 即可(不传 -L3Mode);解析器(resolve_canonical_asof.py,拉 trade_cal)算出 canonical as_of,
#   脚本在 [CANONICAL] 行打印,并把 live/historical 分类(mode)贯穿给 egs_main / pipeline / regime。
#   机理(已核 egs_main 代码):canonical as_of=即将到来的周一时,周一当日 EOD(daily / daily_basic / suspend)
#   尚未生成 → egs_main「空就回退前一交易日」逻辑自动落到最近已结算交易日,所以**选股价格/估值/停牌依据
#   节前收盘**;而新闻 / 语义 web·LLM 层只查 `ann_date<=as_of`、物理上抓不到未来新闻 → 自然=到运行时刻为止
#   (含周末突发 + 周一早间)。= 节前选股池 + 最新新闻。多次跑同一 canonical as_of:forward_tracker 按
#   (as_of,ts_code)去重、regime 收敛到已结算日、overlay 数单一 as_of → 幂等不灌水;result/私密周报后跑覆盖前跑。
#   M6.7 周报(含 EM 新闻→DeepSeek 判官)同次产出:脚本传 `--run-date <运行日>`,live(as_of>=run_date,
#   含前瞻周一)→ `--price-freshness-mode intraday_prior_settled` 容忍最新 bar=前一交易日,故不 FATAL;
#   真·过去回放(as_of<run_date)仍严格 strict_as_of + 须显式 -L3Mode pit/neutralize。
#   确认依据节前的标志:日志出现 `daily_basic <周一> 无数据，回退至 <最近交易日>`。
#   滚动边界:周一**收盘(15:00)后**再跑 → canonical 滚到周二(此时周一已收盘、实际在为周二决策);你的
#   窗口止于周一收盘,不会触发。显式 -AsOf <非交易日> 仍被 egs_main 拒(请省略 -AsOf 自动解析,或传交易日)。

param(
    [ValidatePattern('^(\d{8})?$')]
    [string]$AsOf = $null,
    [ValidateSet('sina', 'em')]
    [string]$CanarySource = 'sina',
    [ValidateSet('pit', 'today', 'neutralize')]
    [string]$L3Mode = $null,
    [ValidateSet('enabled', 'disabled')]
    [string]$CachePolicy = 'enabled',
    [string]$PythonExe = '',
    [string]$Account = $null,
    [string]$RegulatoryConfirmations = $null,
    [string]$HoldingRegulatoryConfirmations = $null,
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
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
[Environment]::SetEnvironmentVariable('PYTHONIOENCODING', 'utf-8', 'Process')
[Environment]::SetEnvironmentVariable('PYTHONUTF8', '1', 'Process')
$ProjectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $ProjectRoot '.tools\Resolve-AshortPython.ps1')
try {
    $PythonExe = Resolve-AshortPython -Requested $PythonExe
} catch {
    Write-Host "[FATAL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
function Write-M67FailureReceipt {
    param([string]$Directory, [string]$Reason, [int]$ExitCode, [string]$FailureDetailRef = '', [string]$AnalysisInput = $null)
    $ErrorActionPreference = 'Stop'
    New-Item -ItemType Directory -Force -Path $Directory -ErrorAction Stop | Out-Null
    $Receipt = Join-Path $Directory 'weekly_m67.receipt.json'
    $Tmp = "$Receipt.tmp"
    $Payload = [ordered]@{
        schema_name = 'a_short_weekly_publish_receipt'
        schema_version = '1.0.0'
        as_of = $AsOf
        stage_status = 'failed'
        failure_reason = $Reason
        exit_code = $ExitCode
    }
    if (-not [string]::IsNullOrWhiteSpace($FailureDetailRef)) {
        $Payload['failure_detail_ref'] = $FailureDetailRef
    }
    if ($AnalysisInput -and (Test-Path -LiteralPath $AnalysisInput -PathType Leaf)) {
        try {
            $Attempt = Get-Content -Raw -Encoding UTF8 -LiteralPath $AnalysisInput | ConvertFrom-Json
            $Identity = $Attempt.source.run_identity
            if ($Identity.run_id -and $Identity.candidate_digest) {
                $Payload['run_id'] = [string]$Identity.run_id
                $Payload['candidate_digest'] = [string]$Identity.candidate_digest
            }
        } catch {
            # The failed receipt remains honest without fabricated identity.
        }
    }
    # Stage the failed receipt first. Then unlink the old complete receipt BEFORE touching JSON/Markdown,
    # so any later filesystem failure leaves the official reader fail-closed (missing receipt), never stale-complete.
    $Payload | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $Tmp -Encoding utf8 -ErrorAction Stop
    if (Test-Path -LiteralPath $Receipt) {
        Remove-Item -LiteralPath $Receipt -Force -ErrorAction Stop
    }
    foreach ($Leaf in @('weekly_m67.json', 'weekly_m67.md')) {
        $Stale = Join-Path $Directory $Leaf
        if (Test-Path -LiteralPath $Stale) {
            Remove-Item -LiteralPath $Stale -Force -ErrorAction Stop
        }
    }
    Move-Item -LiteralPath $Tmp -Destination $Receipt -Force -ErrorAction Stop
}
function Write-KnownM67FailureReceipt {
    param([string]$Reason, [int]$ExitCode)
    if ($SkipSemanticRisk -or [string]::IsNullOrWhiteSpace($AsOf)) { return }
    $Directory = if ($Account) {
        Join-Path $ProjectRoot "state\a_short\weekly_private\$AsOf"
    } else {
        Join-Path $ProjectRoot "research\results\a_short\$AsOf"
    }
    Write-M67FailureReceipt -Directory $Directory -Reason $Reason -ExitCode $ExitCode
}
# 刀3: dependency preflight runs BEFORE the canonical resolver, provider, or private-state access.
$PreflightScript = Join-Path $ProjectRoot 'runners\a_short_preflight.py'
& $PythonExe $PreflightScript
$PreflightExit = $LASTEXITCODE
if ($null -eq $PreflightExit -or $PreflightExit -ne 0) {
    Write-KnownM67FailureReceipt -Reason 'preflight_failed' -ExitCode 2
    Write-Host "[FATAL] A-short preflight failed before canonical resolution, provider, or private-state access." -ForegroundColor Red
    exit 2
}
if (-not (Test-Path (Join-Path $ProjectRoot 'A-EGS\egs_main.py') -PathType Leaf)) {
    Write-KnownM67FailureReceipt -Reason 'entrypoint_missing' -ExitCode 1
    Write-Host "[FATAL] expected A-EGS\egs_main.py (as a file) under $ProjectRoot." -ForegroundColor Red
    exit 1
}
$MarketNow = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId(
    [System.DateTimeOffset]::UtcNow,
    'China Standard Time'
)
$RunDate = $MarketNow.ToString('yyyyMMdd', [System.Globalization.CultureInfo]::InvariantCulture)
if ([string]::IsNullOrWhiteSpace($AsOf)) {
    # --- 省略 -AsOf → 解析 canonical 决策日（拉 trade_cal，需网络/TUSHARE_TOKEN）---
    # 窗口内任意时刻(周五盘后→周一盘前)运行都收敛到「即将到来/当前未收盘的交易日」(正常周=即将到来的周一),
    # 避免多次跑用不同 as_of 把 forward_tracker/regime/overlay 灌水。canonical 恒为真交易日且 live。
    $ResolveScript = Join-Path $ProjectRoot 'runners\resolve_canonical_asof.py'
    $ResolveOut = Join-Path $env:TEMP "a_short_canonical_asof_$PID.json"
    & $PythonExe $ResolveScript '--out' $ResolveOut | Out-Null
    $ResolveExit = $LASTEXITCODE
    if ($ResolveExit -ne 0 -or -not (Test-Path $ResolveOut)) {
        Write-Host "[FATAL] canonical as_of resolution failed (resolve_canonical_asof.py exit $ResolveExit); check network / TUSHARE_TOKEN, or pass -AsOf <trading-day> explicitly." -ForegroundColor Red
        exit 1
    }
    $Resolved = Get-Content -Raw -Encoding UTF8 $ResolveOut | ConvertFrom-Json
    Remove-Item -Force $ResolveOut -ErrorAction SilentlyContinue
    $AsOf = [string]$Resolved.as_of
    $PriceAsOf = [string]$Resolved.last_settled
    $IsHistoricalAsOf = $false   # canonical = 即将到来/当前未收盘的交易日,按定义恒 live(as_of>=run_date)
    if ([string]::IsNullOrWhiteSpace($AsOf)) {
        Write-Host "[FATAL] canonical resolver returned an empty as_of." -ForegroundColor Red
        exit 1
    }
    if ([string]::IsNullOrWhiteSpace($PriceAsOf)) {
        Write-Host "[FATAL] canonical resolver returned no officially settled price date." -ForegroundColor Red
        exit 1
    }
    Write-Host "[CANONICAL] as_of=$AsOf (resolved)  run_date=$RunDate  mode=live  last_settled=$($Resolved.last_settled)" -ForegroundColor Cyan
} else {
    # --- 显式 -AsOf → 纯日期比较分类（无需网络）---
    # as_of < 今天 = historical(真·过去回放,须显式 -L3Mode pit/neutralize);as_of >= 今天 = live(今日/前瞻交易日)。
    # as_of 交易日有效性由 egs_main.set_asof 兜底(拒非交易日);与 egs/pipeline 的 as_of>=run_date live 判据一致。
    $IsHistoricalAsOf = ([string]::Compare([string]$AsOf, [string]$RunDate, [System.StringComparison]::Ordinal) -lt 0)
    $PriceAsOf = $AsOf
}
$EffectiveL3Mode = $L3Mode

# P4: de-identified per-run manifests for the post-run health companion.
$LauncherSidecarOutcomes = @()
function Add-SidecarOutcome {
    param(
        [string]$Name,
        [bool]$Expected,
        [bool]$Attempted,
        [ValidateSet('succeeded','failed','skipped','not_due','not_configured')]
        [string]$ExecutionStatus,
        [ValidateSet('advanced','already_current','stalled','not_applicable','unavailable')]
        [string]$ProgressStatus,
        [string]$ErrorCode = $null,
        [string]$SkipReason = $null,
        [string]$ExpectedDataThrough = $null,
        [string]$ObservedDecisionAsOf = $null,
        [string]$ObservedDataThrough = $null
    )
    $script:LauncherSidecarOutcomes += [ordered]@{
        name = $Name; expected = $Expected; attempted = $Attempted
        execution_status = $ExecutionStatus; progress_status = $ProgressStatus
        expected_data_through = $ExpectedDataThrough
        observed_decision_as_of = $ObservedDecisionAsOf
        observed_data_through = $ObservedDataThrough
        error_code = $ErrorCode; skip_reason = $SkipReason
    }
}

if ([string]::IsNullOrWhiteSpace($EffectiveL3Mode)) {
    if ($IsHistoricalAsOf) {
        Write-KnownM67FailureReceipt -Reason 'historical_l3_mode_missing' -ExitCode 1
        Write-Host "[FATAL] Historical -AsOf $AsOf is not the current run date $RunDate." -ForegroundColor Red
        Write-Host "        Pass -L3Mode pit or -L3Mode neutralize explicitly; default --l3-mode=today is blocked for historical official-output runs." -ForegroundColor Red
        exit 1
    }
    $EffectiveL3Mode = 'today'
}

if ($IsHistoricalAsOf -and $EffectiveL3Mode -eq 'today') {
    Write-KnownM67FailureReceipt -Reason 'historical_l3_mode_invalid' -ExitCode 1
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
    Write-KnownM67FailureReceipt -Reason 'historical_overwrite_blocked' -ExitCode 1
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

# --- Stage 1: egs_main (the HiThink L3 graph is fetched and verified in-process) ---
$EgsArgs = @('A-EGS\egs_main.py', '--as-of', $AsOf, '--price-as-of', $PriceAsOf, '--l3-mode', $EffectiveL3Mode, '--cache-policy', $CachePolicy)
if ($EffectiveL3Mode -eq 'pit') {
    $EgsArgs += '--l3-pit-strict'
}

Write-Host "[1/4] Running $PythonExe $($EgsArgs -join ' ') ..." -ForegroundColor Yellow
& $PythonExe @EgsArgs
$EgsExitCode = $LASTEXITCODE
if ($null -eq $EgsExitCode) { $EgsExitCode = 1 }

if ($EgsExitCode -ne 0) {
    Write-KnownM67FailureReceipt -Reason 'egs_failed' -ExitCode $EgsExitCode
    Write-Host ""
    Write-Host "[SKIP] egs_main exit $EgsExitCode -> skipping canary + tracker + semantic (no fresh candidates)" -ForegroundColor Red
    exit $EgsExitCode
}

# --- Stage 2: data_canary ---
if ($SkipCanary) {
    Add-SidecarOutcome -Name 'data_canary' -Expected $false -Attempted $false -ExecutionStatus 'skipped' -ProgressStatus 'not_applicable' -SkipReason 'skip_canary'
    Write-Host ""
    Write-Host "[2/4] -SkipCanary set, canary not run" -ForegroundColor DarkGray
} else {
    $CanaryExitCode = 1
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
    $CanaryProgress = if ($CanaryExitCode -eq 0 -and (Test-Path $CanaryLog)) { 'advanced' } else { 'unavailable' }
    Add-SidecarOutcome -Name 'data_canary' -Expected $true -Attempted $true -ExecutionStatus $(if($CanaryExitCode -eq 0){'succeeded'}else{'failed'}) -ProgressStatus $CanaryProgress -ErrorCode $(if($CanaryExitCode -eq 0){$null}else{'process_failed'}) -ObservedDecisionAsOf $AsOf
}

# --- Stage 3: forward_tracker capture ---
# The theme comparator runs after capture/backfill as an audit-only sidecar.
if ($SkipTracker) {
    Add-SidecarOutcome -Name 'forward_tracker_capture' -Expected $false -Attempted $false -ExecutionStatus 'skipped' -ProgressStatus 'not_applicable' -SkipReason 'skip_tracker'
    Add-SidecarOutcome -Name 'forward_tracker_backfill' -Expected $false -Attempted $false -ExecutionStatus 'skipped' -ProgressStatus 'not_applicable' -SkipReason 'skip_tracker'
    Add-SidecarOutcome -Name 'theme_forward_comparison' -Expected $false -Attempted $false -ExecutionStatus 'skipped' -ProgressStatus 'not_applicable' -SkipReason 'skip_tracker'
    Write-Host ""
    Write-Host "[3/4] -SkipTracker set, forward tracker not run" -ForegroundColor DarkGray
} else {
    $TrackerBackfillExitCode = 1
    Write-Host ""
    Write-Host "[3/4] Running runners\forward_tracker.py capture --as-of $AsOf ..." -ForegroundColor Yellow
    & $PythonExe runners\forward_tracker.py capture --as-of $AsOf
    $TrackerExitCode = $LASTEXITCODE
    if ($null -eq $TrackerExitCode) { $TrackerExitCode = 1 }

    if ($TrackerExitCode -ne 0) {
        # tracker capture 失败不影响主流程退出码（旁路约束）。
        # 失败原因通常是 analysis_input.json 缺失或 Python 异常，不是数据问题。
        Write-Host "[WARN] forward_tracker exit $TrackerExitCode (check logs/forward_tracker.csv)" -ForegroundColor Yellow
        Add-SidecarOutcome -Name 'forward_tracker_capture' -Expected $true -Attempted $true -ExecutionStatus 'failed' -ProgressStatus 'unavailable' -ErrorCode 'process_failed' -ObservedDecisionAsOf $AsOf
        Add-SidecarOutcome -Name 'forward_tracker_backfill' -Expected $false -Attempted $false -ExecutionStatus 'not_due' -ProgressStatus 'not_applicable' -SkipReason 'capture_failed'
        Add-SidecarOutcome -Name 'theme_forward_comparison' -Expected $false -Attempted $false -ExecutionStatus 'not_due' -ProgressStatus 'not_applicable' -SkipReason 'capture_failed'
    } else {
        # P1 Cut2 consumes only this existing tracker. Backfill is cache-only: it never asks the
        # weekly runner to download extra market data, and a cache gap remains advisory.
        Write-Host "[3/4] Cache-only forward_tracker backfill (P1 candidate-effect sidecar input) ..." -ForegroundColor Yellow
        & $PythonExe runners\forward_tracker.py backfill --windows 5,10,20
        $TrackerBackfillExitCode = $LASTEXITCODE
        if ($null -eq $TrackerBackfillExitCode) { $TrackerBackfillExitCode = 1 }
        if ($TrackerBackfillExitCode -ne 0) {
            Write-Host "[WARN] forward_tracker cache-only backfill exit $TrackerBackfillExitCode; P1 remains pending and EGS/M6.7 continue unchanged." -ForegroundColor Yellow
        }
        Add-SidecarOutcome -Name 'forward_tracker_capture' -Expected $true -Attempted $true -ExecutionStatus 'succeeded' -ProgressStatus 'advanced' -ObservedDecisionAsOf $AsOf
        Add-SidecarOutcome -Name 'forward_tracker_backfill' -Expected $true -Attempted $true -ExecutionStatus $(if($TrackerBackfillExitCode -eq 0){'succeeded'}else{'failed'}) -ProgressStatus $(if($TrackerBackfillExitCode -eq 0){'not_applicable'}else{'unavailable'}) -ErrorCode $(if($TrackerBackfillExitCode -eq 0){$null}else{'process_failed'})
        if ($IsHistoricalAsOf) {
            Add-SidecarOutcome -Name 'theme_forward_comparison' -Expected $false -Attempted $false -ExecutionStatus 'not_due' -ProgressStatus 'not_applicable' -SkipReason 'historical_replay'
        } else {
            Write-Host "[3a/4] Running audit-only theme forward comparison sidecar ..." -ForegroundColor Yellow
            & $PythonExe runners\a_short_theme_forward_comparison.py `
                --tracker (Join-Path $ProjectRoot 'logs\forward_tracker.csv') `
                --out (Join-Path $ProjectRoot 'research\results\a_short_theme_forward_comparison.json') `
                --private-root (Join-Path $ProjectRoot 'state\a_short\theme_forward_comparison_private\v1')
            $ThemeComparisonExitCode = $LASTEXITCODE
            if ($null -eq $ThemeComparisonExitCode) { $ThemeComparisonExitCode = 1 }
            if ($ThemeComparisonExitCode -ne 0) {
                Write-Host "[WARN] theme forward comparison exit $ThemeComparisonExitCode (audit-only sidecar; does NOT block the weekly)" -ForegroundColor Yellow
            }
            Add-SidecarOutcome -Name 'theme_forward_comparison' -Expected $true -Attempted $true -ExecutionStatus $(if($ThemeComparisonExitCode -eq 0){'succeeded'}else{'failed'}) -ProgressStatus $(if($ThemeComparisonExitCode -eq 0){'not_applicable'}else{'unavailable'}) -ErrorCode $(if($ThemeComparisonExitCode -eq 0){$null}else{'process_failed'})
        }
    }
}

# --- Stage 3b: crash-veto 5d/10d comparison tracker ---
# 只在 live 周跑冻结新批次；历史回放不得污染 forward 账本。失败只让本周周报不带该小节，绝不影响 EGS/M6.7。
$CrashVetoSummary = Join-Path $ProjectRoot 'logs\a_short_crash_veto_summary.json'
$CrashVetoSummaryReady = $false
if ($IsHistoricalAsOf) {
    Add-SidecarOutcome -Name 'crash_veto' -Expected $false -Attempted $false -ExecutionStatus 'not_due' -ProgressStatus 'not_applicable' -SkipReason 'historical_replay'
    Write-Host "[3b/4] Historical replay: crash-veto forward tracker skipped" -ForegroundColor DarkGray
} else {
    Write-Host "[3b/4] Updating crash-veto 5/10-trading-day comparison ..." -ForegroundColor Yellow
    & $PythonExe runners\a_short_crash_veto_tracker.py update --as-of $AsOf --rule-confirmed-days 5 --confirm-fetch-authorized
    $CrashVetoExitCode = $LASTEXITCODE
    if ($null -eq $CrashVetoExitCode) { $CrashVetoExitCode = 1 }
    if ($CrashVetoExitCode -eq 0 -and (Test-Path $CrashVetoSummary)) {
        $CrashVetoSummaryReady = $true
        Write-Host "[ADVISORY] crash-veto comparison ready -> $CrashVetoSummary (selection unchanged)" -ForegroundColor Yellow
    } else {
        Write-Host "[WARN] crash-veto comparison unavailable (exit $CrashVetoExitCode); formal selection/M6.7 continues unchanged." -ForegroundColor Yellow
    }
    Add-SidecarOutcome -Name 'crash_veto' -Expected $true -Attempted $true -ExecutionStatus $(if($CrashVetoExitCode -eq 0 -and (Test-Path $CrashVetoSummary)){'succeeded'}else{'failed'}) -ProgressStatus $(if($CrashVetoExitCode -eq 0 -and (Test-Path $CrashVetoSummary)){'advanced'}else{'unavailable'}) -ErrorCode $(if($CrashVetoExitCode -eq 0 -and (Test-Path $CrashVetoSummary)){$null}else{'process_failed'}) -ObservedDecisionAsOf $(if($CrashVetoExitCode -eq 0){$AsOf}else{$null})
}

# --- Stage 4: M6.7 authoritative operation weekly report (Slice 3b-2: replaces the standalone semantic-risk summary
#     sidecar; ONE Friday entry now also runs the M6.7 pipeline with semantic [cninfo official + DeepSeek
#     web] rendered inline). semantic 证据本身 advisory-only；但 requested M6.7 失败必须写 failed receipt + 非零退出；落 research 非生产
#     lane(禁 result/a_short)。真取数:IV options + 前复权价 + cninfo + em 资讯(web 源)+ DeepSeek。web 源 = em(取代失效 sina);run-path 见契约 §web_llm 产出路径。
if ($SkipSemanticRisk) {
    Write-Host ""
    Write-Host "[4/4] -SkipSemanticRisk set, M6.7 operation report not run" -ForegroundColor DarkGray
} else {
    Write-Host ""
    $SemAnalysisInput = Join-Path $ProjectRoot "result\a_short\$AsOf\analysis_input.json"
    if (-not (Test-Path $SemAnalysisInput)) {
        $M67Dir = if ($Account) { Join-Path $ProjectRoot "state\a_short\weekly_private\$AsOf" } else { Join-Path $ProjectRoot "research\results\a_short\$AsOf" }
        Write-M67FailureReceipt -Directory $M67Dir -Reason 'analysis_input_missing' -ExitCode 21
        Write-Host "[FATAL] M6.7 requested but analysis_input is missing: $SemAnalysisInput" -ForegroundColor Red
        exit 21
    } else {
        # 持仓恒列入隐私护栏(固化):带 -Account 的周报含真实持仓(代码/成本/止损)→ 落 gitignored 私密目录
        # state\a_short\weekly_private\<as_of>\(.gitignore: state/*/weekly_private/),绝不入 git 追踪的 research lane。
        # 无 -Account(observation-only、无持仓)→ 仍落标准 research\results\a_short\<as_of>\(可留作证据)。
        # pipeline 侧另有同口径硬护栏,直接调用绕过本脚本也拦得住。
        if ($Account) {
            $M67Dir = Join-Path $ProjectRoot "state\a_short\weekly_private\$AsOf"
        } else {
            $M67Dir = Join-Path $ProjectRoot "research\results\a_short\$AsOf"
        }
        $IvFeed = Join-Path $ProjectRoot "research\results\a_short\iv_feed_$AsOf\iv_feed.json"
        # A PID can be recycled. Clear this run's detail path before invoking the
        # builder; the builder repeats the ownership guard before any fetch.
        $IvFailureReceipt = Join-Path $M67Dir "iv_feed_failure_$PID.json"
        if (Test-Path -LiteralPath $IvFailureReceipt -PathType Leaf) {
            Remove-Item -LiteralPath $IvFailureReceipt -Force -ErrorAction Stop
        }
        $M67Out = Join-Path $M67Dir "weekly_m67.json"
        $OverlayPath = Join-Path $ProjectRoot "result\a_short\$AsOf\overlay.json"
        Write-Host "[4/4] Building market IV feed: runners\a_short_iv_feed_build.py --as-of $AsOf ..." -ForegroundColor Yellow
        & $PythonExe runners\a_short_iv_feed_build.py --as-of $AsOf --out $IvFeed --failure-receipt-out $IvFailureReceipt --confirm-fetch-authorized
        $IvExitCode = $LASTEXITCODE
        if ($null -eq $IvExitCode) { $IvExitCode = 1 }
        if ($IvExitCode -ne 0 -or -not (Test-Path $IvFeed)) {
            $IvFailureDetailRef = if (Test-Path $IvFailureReceipt) { [System.IO.Path]::GetFileName($IvFailureReceipt) } else { '' }
            Write-M67FailureReceipt -Directory $M67Dir -Reason 'iv_feed_failed' -ExitCode 22 -FailureDetailRef $IvFailureDetailRef -AnalysisInput $SemAnalysisInput
            Write-Host "[FATAL] M6.7 requested but IV feed build failed (exit $IvExitCode)" -ForegroundColor Red
            exit 22
        } else {
            $M67Args = @('runners\a_short_weekly_pipeline.py', '--as-of', $AsOf, '--price-as-of', $PriceAsOf, '--run-date', $RunDate, '--analysis-input', $SemAnalysisInput, '--iv-feed', $IvFeed, '--out', $M67Out, '--confirm-fetch-authorized')
            if ($CrashVetoSummaryReady) { $M67Args += @('--crash-veto-summary', $CrashVetoSummary) }
            if (-not $IsHistoricalAsOf) {
                # live 运行(as_of>=运行日:今日 或 前瞻 canonical 周一):as_of 当日 EOD 盘中/盘前尚未发布 → 显式启用
                # 价格门 intraday tolerance(容忍最新已结算 bar=前一交易日);真·过去回放(as_of<运行日)保持默认
                # strict_as_of。实际价格时钟记进 weekly_m67 lineage。
                $M67Args += @('--price-freshness-mode', 'intraday_prior_settled')
                # One bounded private cache serves v2/P5/P2/P3. The existing P0 writer remains the sole provider
                # seam; it loads cached rows before applying the reviewed budget: v2 first, then P5, then P2/P3.
                # Any failure leaves only comparison evidence unavailable; M6.7 remains authoritative.
                $FactorComparisonV2Root = Join-Path $ProjectRoot 'state\a_short\factor_comparison_private\v2'
                $FactorComparisonV2Cache = Join-Path $FactorComparisonV2Root 'daily_cache.json'
                $OverlayAdjudicationRoot = Join-Path $ProjectRoot 'state\a_short\overlay_adjudication_private\v1'
                $OverlayAdjudicationStage3 = Join-Path $ProjectRoot "result\a_short\$AsOf\stage3_selection_snapshot.json"
                $OverlayAdjudicationSource = Join-Path $ProjectRoot "result\a_short\$AsOf\stage3_overlay_score.json"
                $OverlayAdjudicationMarker = Join-Path $ProjectRoot "result\a_short\$AsOf\official_publish.json"
                $OverlayAdjudicationPublicJson = Join-Path $ProjectRoot 'research\results\a_short\overlay_adjudication_summary.json'
                $OverlayAdjudicationPublicMarkdown = Join-Path $ProjectRoot 'research\results\a_short\overlay_adjudication_summary.md'
                $IndustryWeightP5Root = Join-Path $ProjectRoot 'state\a_short\industry_weight_comparison_private\v1'
                $IndustryWeightSource = Join-Path $ProjectRoot "result\a_short\$AsOf\egs_weight_comparison.json"
                $TargetPolicyLedger = Join-Path $ProjectRoot 'logs\a_short_target_policy_comparison.json'
                $FinalActionLedger = Join-Path $ProjectRoot 'logs\a_short_final_action_validation.json'
                $OfficialOperationEvidenceRoot = Join-Path $ProjectRoot 'state\a_short\operation_evidence_private\v1'
                Write-Host "[ADVISORY] Updating bounded A-short shared private cache ..." -ForegroundColor Yellow
                & $PythonExe runners\a_short_factor_comparison_v2_cache_build.py --root $FactorComparisonV2Root --run-date $RunDate --industry-weight-root $IndustryWeightP5Root --target-policy-root $TargetPolicyLedger --final-action-validation-root $FinalActionLedger --official-operation-evidence-root $OfficialOperationEvidenceRoot --overlay-adjudication-root $OverlayAdjudicationRoot
                $FactorComparisonCacheExitCode = $LASTEXITCODE
                if ($null -eq $FactorComparisonCacheExitCode) { $FactorComparisonCacheExitCode = 1 }
                if ($FactorComparisonCacheExitCode -ne 0) {
                    Write-Host "[WARN] A-short shared comparison cache unavailable (exit $FactorComparisonCacheExitCode); M6.7/V14.3/overlay continue unchanged." -ForegroundColor Yellow
                }
                Add-SidecarOutcome -Name 'shared_cache_build' -Expected $true -Attempted $true -ExecutionStatus $(if($FactorComparisonCacheExitCode -eq 0){'succeeded'}else{'failed'}) -ProgressStatus $(if($FactorComparisonCacheExitCode -eq 0){'not_applicable'}else{'unavailable'}) -ErrorCode $(if($FactorComparisonCacheExitCode -eq 0){$null}else{'process_failed'})
                # Freeze the normalized live decision only after M6.7 publishes its matching bundle.
                $M67Args += @('--factor-comparison-v2-root', $FactorComparisonV2Root,
                              '--factor-comparison-v2-daily-cache', $FactorComparisonV2Cache,
                              '--factor-comparison-v2-forward')
                # P5a reuses the same cache but has an independent private ledger and public
                # de-identified progress summary.  Its failure is a sidecar outage only.
                $M67Args += @('--industry-weight-comparison-root', $IndustryWeightP5Root,
                               '--industry-weight-comparison-daily-cache', $FactorComparisonV2Cache,
                               '--industry-weight-comparison-source', $IndustryWeightSource,
                               '--industry-weight-comparison-forward')
                # P2/P3 freeze only after the matching M6.7 publishes. They read the same cache projection;
                # neither runner owns a fetcher or a second cache, and their ledgers/verdicts remain separate.
                $M67Args += @('--target-policy-root', $TargetPolicyLedger,
                              '--target-policy-daily-cache', $FactorComparisonV2Cache,
                              '--target-policy-forward')
                $ForwardTracker = Join-Path $ProjectRoot 'logs\forward_tracker.csv'
                $M67Args += @('--final-action-validation-root', $FinalActionLedger,
                              '--final-action-validation-daily-cache', $FactorComparisonV2Cache,
                              '--final-action-validation-tracker', $ForwardTracker,
                              '--final-action-validation-forward')
                # Freeze the formal, account-constrained M6.7 display only after the weekly
                # bundle/receipt publish. Its result sidecar consumes that same P5a cache and
                # only keeps decision-level progress; it never becomes a simulated account.
                $M67Args += @('--official-operation-evidence-root', $OfficialOperationEvidenceRoot,
                               '--official-operation-evidence-daily-cache', $FactorComparisonV2Cache)
                # P4a shares the existing P0 daily cache and binds the live
                # capture to this same as_of/result bucket. It is advisory only.
                $M67Args += @('--overlay-adjudication-root', $OverlayAdjudicationRoot,
                               '--overlay-adjudication-daily-cache', $FactorComparisonV2Cache,
                               '--overlay-adjudication-stage3-snapshot', $OverlayAdjudicationStage3,
                               '--overlay-adjudication-overlay-source', $OverlayAdjudicationSource,
                               '--overlay-adjudication-egs-publish-marker', $OverlayAdjudicationMarker,
                               '--overlay-adjudication-public-json', $OverlayAdjudicationPublicJson,
                               '--overlay-adjudication-public-markdown', $OverlayAdjudicationPublicMarkdown,
                               '--overlay-adjudication-forward')
            }
            if (Test-Path $OverlayPath) { $M67Args += @('--overlay', $OverlayPath) }
            if (-not [string]::IsNullOrWhiteSpace($RegulatoryConfirmations)) {
                $M67Args += @('--regulatory-confirmations', $RegulatoryConfirmations)
            }
            if (-not [string]::IsNullOrWhiteSpace($HoldingRegulatoryConfirmations)) {
                $M67Args += @('--holding-regulatory-confirmations', $HoldingRegulatoryConfirmations)
            }
            $RunM67 = $true
            if ($Account) {
                if (Test-Path $Account) {
                    $M67Args += @('--account', $Account)
                } else {
                    # bad -Account path: fail the requested M6.7; never emit a misleading sizing-less artifact.
                    Write-M67FailureReceipt -Directory $M67Dir -Reason 'account_path_missing' -ExitCode 23 -AnalysisInput $SemAnalysisInput
                    Write-Host "[FATAL] M6.7 requested but -Account path was not found: $Account" -ForegroundColor Red
                    exit 23
                }
            } else {
                Write-Host "[WARN] M6.7 no -Account: observation-only (no position sizing/holding-state). The weekly_m67 artifact is marked sizing_mode=observation_only_no_account - 建仓 candidates render as 观察 (sizing artifact, NOT a real avoid signal). Pass -Account <a_short_account_bundle JSON generated by a_short_account_state_from_manual_tables.py> for real sizing and holding-state decisions." -ForegroundColor Yellow
            }
            if ($RunM67) {
                Write-Host "[4/4] Running M6.7 pipeline: runners\a_short_weekly_pipeline.py --as-of $AsOf ..." -ForegroundColor Yellow
                & $PythonExe @M67Args
                $M67ExitCode = $LASTEXITCODE
                if ($null -eq $M67ExitCode) { $M67ExitCode = 1 }
                if ($M67ExitCode -ne 0) {
                    # requested M6.7 是本次正式运维产物；失败必须显式传播，不能返回选股成功假象。
                    Write-M67FailureReceipt -Directory $M67Dir -Reason 'weekly_pipeline_failed' -ExitCode $M67ExitCode -AnalysisInput $SemAnalysisInput
                    Write-Host "[FATAL] M6.7 requested and weekly pipeline failed (exit $M67ExitCode)" -ForegroundColor Red
                    exit $M67ExitCode
                } else {
                    Write-Host "[OPERATION] authoritative M6.7 weekly report -> $M67Out. Older analysis reports remain research-only inputs." -ForegroundColor Yellow
                }
            }
        }
    }
}

# --- Stage 5: V14.3 regime comparison ledger (旁路 sidecar;comparison-only 非生产,V14.2 仍冻结;失败绝不阻断
#     周报)。只在 live 运行(as_of>=运行日:今日 或 前瞻 canonical 周一)跑——regime ledger 是 forward 累积的
#     已结算交易日证据,真·过去回放(as_of<运行日,$IsHistoricalAsOf)不该推进它。
#     无 ledger→一次性 --bootstrap(252日回填,首跑数分钟)、有→increment(秒级)。runner 把 as_of 收敛到最新已结算
#     交易日(盘中周一→上周五),复用本次已建的 IV feed(有则传)。egs 成功才会走到这(egs 失败已在上面 exit)。
if ($SkipRegime) {
    Add-SidecarOutcome -Name 'regime_daily' -Expected $false -Attempted $false -ExecutionStatus 'skipped' -ProgressStatus 'not_applicable' -SkipReason 'skip_regime'
    Add-SidecarOutcome -Name 'regime_action' -Expected $false -Attempted $false -ExecutionStatus 'skipped' -ProgressStatus 'not_applicable' -SkipReason 'skip_regime'
    Write-Host ""
    Write-Host "[regime] -SkipRegime set, V14.3 regime comparison not run" -ForegroundColor DarkGray
} elseif ($IsHistoricalAsOf) {
    Add-SidecarOutcome -Name 'regime_daily' -Expected $false -Attempted $false -ExecutionStatus 'not_due' -ProgressStatus 'not_applicable' -SkipReason 'historical_replay'
    Add-SidecarOutcome -Name 'regime_action' -Expected $false -Attempted $false -ExecutionStatus 'not_due' -ProgressStatus 'not_applicable' -SkipReason 'historical_replay'
    Write-Host ""
    Write-Host "[regime] historical -AsOf $AsOf -> skipping V14.3 regime ledger (only live runs advance the forward regime evidence)" -ForegroundColor DarkGray
} else {
    Write-Host ""
    $RegimeLedger = Join-Path $ProjectRoot "research\results\a_short\regime_daily_ledger.json"
    $RegimeIvFeed = Join-Path $ProjectRoot "research\results\a_short\iv_feed_$AsOf\iv_feed.json"
    # The comparison baseline must use the same effective V14.2 state as M6.7. EGS currently emits
    # unknown in its frozen slot; production resolves that to shock, so never compare V14.3 to literal
    # unknown while the actual weekly posture is shock.
    $EffectiveV142Regime = 'shock'
    $RawV142Regime = 'unknown'
    try {
        $RawV142Regime = (Get-Content -Raw -Encoding UTF8 $SemAnalysisInput | ConvertFrom-Json).market_context.market_regime.status
        if ($RawV142Regime -in @('attack', 'shock', 'defense', 'contraction')) {
            $EffectiveV142Regime = $RawV142Regime
        }
    } catch {
        Write-Host "[regime] unable to read production regime from analysis_input; using fail-closed effective shock" -ForegroundColor Yellow
    }
    $RegimeArgs = @('runners\a_short_regime_comparison_runner.py', '--as-of', $AsOf,
                    '--v14_2-regime', $EffectiveV142Regime,
                    '--v14_2-raw-regime', $RawV142Regime,
                    '--m67-report', $M67Out,
                    '--confirm-fetch-authorized')
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
    $RegimeStatus = if($RegimeExitCode -eq 0){'succeeded'}else{'failed'}
    $RegimeProgress = if($RegimeExitCode -eq 0){'advanced'}else{'unavailable'}
    $RegimeError = if($RegimeExitCode -eq 0){$null}else{'process_failed'}
    Add-SidecarOutcome -Name 'regime_daily' -Expected $true -Attempted $true -ExecutionStatus $RegimeStatus -ProgressStatus $RegimeProgress -ErrorCode $RegimeError -ExpectedDataThrough $PriceAsOf -ObservedDataThrough $(if($RegimeExitCode -eq 0){$PriceAsOf}else{$null})
    Add-SidecarOutcome -Name 'regime_action' -Expected $true -Attempted $true -ExecutionStatus $RegimeStatus -ProgressStatus $RegimeProgress -ErrorCode $RegimeError -ObservedDecisionAsOf $(if($RegimeExitCode -eq 0){$AsOf}else{$null})
}

 # P4: health is a separate post-run companion.  The already-published M6.7
 # JSON/Markdown/receipt are intentionally not rewritten here.
$HealthDir = if ($Account) {
    Join-Path $ProjectRoot "state\a_short\weekly_private\$AsOf"
} else {
    Join-Path $ProjectRoot "research\results\a_short\$AsOf"
}
$PipelineExpected = @()
if (-not $SkipSemanticRisk -and -not $IsHistoricalAsOf) {
    $PipelineExpected = @(
        'official_operation_capture', 'official_operation_settlement', 'factor_v2_capture',
        'industry_weight_capture', 'industry_weight_settlement', 'target_policy_capture',
        'final_action_capture', 'overlay_adjudication_capture', 'overlay_adjudication_settlement'
    )
}
$ManifestExpected = @($LauncherSidecarOutcomes | ForEach-Object { [string]$_.name }) + $PipelineExpected | Select-Object -Unique
$LauncherManifestPath = Join-Path $HealthDir 'launcher_sidecar_outcomes.json'
$LauncherManifest = [ordered]@{
    schema_name = 'a_short_weekly_sidecar_outcomes'
    schema_version = '1.0.0'
    as_of = [string]$AsOf
    run_id = $null
    candidate_digest = $null
    expected_sidecars = @($ManifestExpected)
    sidecars = @($LauncherSidecarOutcomes)
}
$ReceiptForHealth = Join-Path $HealthDir 'weekly_m67.receipt.json'
$M67StatusForHealth = if ($SkipSemanticRisk) { 'skipped' } elseif (Test-Path -LiteralPath $ReceiptForHealth) { 'complete' } else { 'not_run' }
if (Test-Path -LiteralPath (Join-Path $HealthDir 'weekly_m67.json')) {
    try {
        $WeeklyForHealth = Get-Content -Raw -Encoding UTF8 (Join-Path $HealthDir 'weekly_m67.json') | ConvertFrom-Json
        $LauncherManifest.run_id = [string]$WeeklyForHealth.run_lineage.run_id
        $LauncherManifest.candidate_digest = [string]$WeeklyForHealth.run_lineage.candidate_digest
    } catch { }
}
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
New-Item -ItemType Directory -Force -Path $HealthDir | Out-Null
[System.IO.File]::WriteAllText($LauncherManifestPath, ($LauncherManifest | ConvertTo-Json -Depth 8) + "`n", $Utf8NoBom)
$PipelineManifestPath = Join-Path $HealthDir 'weekly_m67.pipeline_sidecar_outcomes.json'
$HealthArgs = @(
    'runners\a_short_weekly_sidecar_health.py', '--as-of', $AsOf,
    '--project-root', $ProjectRoot, '--out-dir', $HealthDir,
    '--launcher-outcomes', $LauncherManifestPath,
    '--pipeline-outcomes', $PipelineManifestPath,
    '--m67-status', $M67StatusForHealth
)
if (Test-Path -LiteralPath $ReceiptForHealth) { $HealthArgs += @('--weekly-receipt', $ReceiptForHealth) }
& $PythonExe @HealthArgs
$HealthExitCode = $LASTEXITCODE
if ($null -eq $HealthExitCode) { $HealthExitCode = 1 }
if ($HealthExitCode -ne 0) {
    Write-Host "[sidecar-health] UNAVAILABLE (health companion failed; M6.7/selection unchanged)" -ForegroundColor Red
}
Write-Host "=== Pipeline done ===" -ForegroundColor Cyan
exit 0
