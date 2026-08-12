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
#                                                                     # 价格基准与省略 -AsOf 时**完全相同**:恒取严格早于决策日的那个交易日
#                                                                     # (prior_settled)。显式 -AsOf 不再改变价格基准;因此这条路径现在也要拉
#                                                                     # 一次 trade_cal(需网络/TUSHARE_TOKEN)——离开日历算不出「上一个已收盘交易日」。
#   .\runners\weekly_screening.ps1 -AsOf 20260522 -PriceBasis close   # 仅**真·过去回放**(as_of < 运行日)研究用:取决策日当日收盘。
#                                                                     # live 决策日(含「今天、已收盘」)、未来日、盘中、非交易日一律拒绝启动——
#                                                                     # 在 live 日取当日收盘正是被删掉的那第二种行为,不许用开关装回来。
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
    # 价格基准口径。生产恒为 prior_settled（严格早于决策日的那个交易日）；close 只给显式
    # 历史研究用，且解析器只在该决策日确已收盘时才给，否则 fail-closed。**主路径不再存在
    # 第二种行为**：以前省略 -AsOf 取 last_settled、显式 -AsOf 取 as_of 本身，同一决策日
    # 两条入口两个价格。
    [ValidateSet('prior_settled', 'close')]
    [string]$PriceBasis = 'prior_settled',
    [ValidateSet('enabled', 'disabled')]
    [string]$CachePolicy = 'enabled',
    [string]$PythonExe = '',
    [string]$Account = $null,
    [string]$RegulatoryConfirmations = $null,
    [string]$HoldingRegulatoryConfirmations = $null,
    [ValidatePattern('^[0-9a-f]{32}$')]
    [string]$RunRevisionId = $null,
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
# V5-A: allocate the opaque physical-run key before any guard can publish a
# failure receipt.  The key is still passed unchanged to every later writer.
if ([string]::IsNullOrWhiteSpace($RunRevisionId)) {
    $RunRevisionId = [guid]::NewGuid().ToString('N')
}
function Write-M67Utf8NoBom {
    param([string]$LiteralPath, [string]$Text)
    # Every artifact written through this door is sha-pinned and kept at LF by
    # .gitattributes, but ConvertTo-Json emits CRLF on Windows.  Callers append
    # a bare LF terminator, so without this the file lands mixed-ending and
    # breaks its own pin the moment someone tracks it.  Normalising here covers
    # all three callers instead of each remembering.
    $Normalised = $Text -replace "`r`n", "`n"
    $Encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($LiteralPath, $Normalised, $Encoding)
}
function Invalidate-M67Artifact {
    param([string]$LiteralPath)
    if (-not (Test-Path -LiteralPath $LiteralPath)) { return $true }
    try {
        Remove-Item -LiteralPath $LiteralPath -Force -ErrorAction Stop
        return $true
    } catch {
        # A failed delete must not leave a schema-valid old success surface.
        # Overwrite fallback is deliberately schema-invalid for JSON/receipt
        # and visibly unavailable for Markdown.
        $Tombstone = if ($LiteralPath.EndsWith('.md', [System.StringComparison]::OrdinalIgnoreCase)) {
            "# unavailable: superseded by a failed M6.7 invocation`n"
        } else {
            "{}`n"
        }
        try {
            Write-M67Utf8NoBom -LiteralPath $LiteralPath -Text $Tombstone
            return $true
        } catch {
            Write-Host "[WARN] unable to invalidate stale M6.7 artifact: $([System.IO.Path]::GetFileName($LiteralPath))" -ForegroundColor Yellow
            return $false
        }
    }
}

function Get-DesignCompletionAuthorized {
    # The Python epoch module is the single authority for this gate.  Keep the
    # PowerShell wrapper as a fail-closed transport only; it must not duplicate
    # the registry's status/directive interpretation.
    $Probe = "from engine.a_short_evidence_epoch_mode import design_completion_authorized; print('1' if design_completion_authorized() else '0')"
    try {
        $ProbeOutput = & $PythonExe -c $Probe 2>$null
        $ProbeExitCode = $LASTEXITCODE
        if ($ProbeExitCode -ne 0) { return $false }
        return (($ProbeOutput | Select-Object -Last 1).ToString().Trim() -eq '1')
    } catch {
        return $false
    }
}

function Write-M67FailureReceipt {
    param([string]$Directory, [string]$Reason, [int]$ExitCode, [string]$FailureDetailRef = '', [string]$AnalysisInput = $null,
          [object]$AttemptedBeforeEgs = $null, [string]$FeedRef = '', [string]$FeedSha256 = '',
          [string]$IvFeedStatus = 'not_requested', [switch]$DeferHealth)
    $ErrorActionPreference = 'Stop'
    New-Item -ItemType Directory -Force -Path $Directory -ErrorAction Stop | Out-Null
    $Receipt = Join-Path $Directory 'weekly_m67.receipt.json'
    $Tmp = "$Receipt.tmp"
    $Payload = [ordered]@{
        schema_name = 'a_short_weekly_publish_receipt'
        schema_version = '1.1.0'
        as_of = $AsOf
        stage_status = 'failed'
        failure_reason = $Reason
        exit_code = $ExitCode
        iv_feed_status = $IvFeedStatus
    }
    # Record the price clock even on a failed run: a receipt that leaves the basis
    # implicit is exactly what let two entry points disagree unnoticed.
    if (-not [string]::IsNullOrWhiteSpace($script:PriceBasis)) {
        $Payload['price_basis'] = [string]$script:PriceBasis
    }
    if (-not [string]::IsNullOrWhiteSpace($script:PriceAsOf)) {
        $Payload['price_as_of'] = [string]$script:PriceAsOf
    }
    if (-not [string]::IsNullOrWhiteSpace($FailureDetailRef)) {
        $Payload['failure_detail_ref'] = $FailureDetailRef
    }
    if ($null -ne $AttemptedBeforeEgs) {
        $Payload['attempted_before_egs'] = [bool]$AttemptedBeforeEgs
    }
    if (-not [string]::IsNullOrWhiteSpace($FeedRef)) {
        $Payload['feed_ref'] = $FeedRef
    }
    if (-not [string]::IsNullOrWhiteSpace($FeedSha256)) {
        $Payload['feed_sha256'] = $FeedSha256
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
    # Cut every trust root and visible old surface BEFORE the first fallible
    # failed-receipt write.  Each item is independent: a delete failure falls
    # back to an invalid tombstone instead of aborting before later health
    # surfaces are invalidated.
    $InvalidationFailures = @()
    foreach ($Leaf in @(
        'weekly_m67.receipt.json',
        'sidecar_health.receipt.json',
        'weekly_m67.json',
        'weekly_m67.md',
        'sidecar_health.json',
        'sidecar_health.md',
        'weekly_m67.pipeline_sidecar_outcomes.json',
        'launcher_sidecar_outcomes.json'
    )) {
        if (-not (Invalidate-M67Artifact -LiteralPath (Join-Path $Directory $Leaf))) {
            $InvalidationFailures += $Leaf
        }
    }
    if ($InvalidationFailures.Count -gt 0) {
        throw "unable to invalidate $($InvalidationFailures.Count) stale M6.7 artifact(s)"
    }
    Write-M67Utf8NoBom -LiteralPath $Tmp -Text (
        ($Payload | ConvertTo-Json -Depth 4) + "`n"
    )
    Move-Item -LiteralPath $Tmp -Destination $Receipt -Force -ErrorAction Stop
    if ($DeferHealth) {
        # Post-EGS failures still have independent pre-M6.7 outcomes to close out.
        # Leave health publication to the single finalizer after Stage 5 so it can
        # retain those outcomes instead of publishing an empty intermediate view.
        return
    }
    $FailureHealthScript = Join-Path $ProjectRoot 'runners\a_short_weekly_sidecar_health.py'
    if (Test-Path -LiteralPath $FailureHealthScript -PathType Leaf) {
        $FailureHealthArgs = @(
            $FailureHealthScript,
            '--as-of', [string]$AsOf,
            '--project-root', $ProjectRoot,
            '--out-dir', $Directory,
            '--m67-invocation', 'requested'
        )
        & $PythonExe @FailureHealthArgs
        $FailureHealthExit = $LASTEXITCODE
        if ($null -eq $FailureHealthExit) { $FailureHealthExit = 1 }
        $FailureHealthComplete = (
            $FailureHealthExit -eq 0 -and
            (Test-Path -LiteralPath (Join-Path $Directory 'sidecar_health.json') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $Directory 'sidecar_health.md') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $Directory 'sidecar_health.receipt.json') -PathType Leaf)
        )
        if (-not $FailureHealthComplete) {
            $HealthInvalidationFailures = @()
            foreach ($Leaf in @(
                'sidecar_health.receipt.json',
                'sidecar_health.json',
                'sidecar_health.md'
            )) {
                if (-not (Invalidate-M67Artifact -LiteralPath (Join-Path $Directory $Leaf))) {
                    $HealthInvalidationFailures += $Leaf
                }
            }
            if ($HealthInvalidationFailures.Count -gt 0) {
                throw "unable to invalidate $($HealthInvalidationFailures.Count) partial health artifact(s)"
            }
            Write-Host "[WARN] failed M6.7 receipt published but failure health was unavailable (exit $FailureHealthExit); stale health remains invalidated." -ForegroundColor Yellow
        }
    } else {
        Write-Host "[WARN] failed M6.7 receipt published but health companion is missing; stale health remains invalidated." -ForegroundColor Yellow
    }
}
function Set-M67Failure {
    param([string]$Reason, [int]$ExitCode, [string]$FailureDetailRef = '', [string]$AnalysisInput = $null,
          [object]$AttemptedBeforeEgs = $null, [string]$FeedRef = '', [string]$FeedSha256 = '',
          [string]$IvFeedStatus = 'not_requested', [string]$Directory)
    if ($script:M67InvocationState -eq 'failed') { return }
    if ([string]::IsNullOrWhiteSpace($Directory)) { throw 'M6.7 failure closeout directory is required' }
    $script:M67InvocationState = 'failed'
    $script:M67FailureReason = $Reason
    $script:M67FailureCode = $ExitCode
    if ($script:FinalExitCode -eq 0) {
        $script:FinalExitCode = $ExitCode
    }
    Write-M67FailureReceipt -Directory $Directory -Reason $Reason -ExitCode $ExitCode `
        -FailureDetailRef $FailureDetailRef -AnalysisInput $AnalysisInput `
        -AttemptedBeforeEgs $AttemptedBeforeEgs -FeedRef $FeedRef -FeedSha256 $FeedSha256 `
        -IvFeedStatus $IvFeedStatus -DeferHealth
    Write-Host "[FATAL] M6.7 requested: $Reason (exit $ExitCode); continuing independent closeout" -ForegroundColor Red
}
function Write-KnownM67FailureReceipt {
    param([string]$Reason, [int]$ExitCode)
    if ($SkipSemanticRisk -or [string]::IsNullOrWhiteSpace($AsOf)) { return }
    $KnownIvFeedStatus = [string]$script:IvFeedStatus
    if ([string]::IsNullOrWhiteSpace($KnownIvFeedStatus)) {
        $KnownIvFeedStatus = 'not_requested'
    }
    $Directory = if ($RunRevisionId) {
        if ($Account) {
            Join-Path $ProjectRoot "state\a_short\weekly_private\weeks\$AsOf\revisions\$RunRevisionId"
        } else {
            Join-Path $ProjectRoot "research\results\a_short\$AsOf\revisions\$RunRevisionId"
        }
    } elseif ($Account) {
        Join-Path $ProjectRoot "state\a_short\weekly_private\$AsOf"
    } else {
        Join-Path $ProjectRoot "research\results\a_short\$AsOf"
    }
    Write-M67FailureReceipt -Directory $Directory -Reason $Reason -ExitCode $ExitCode `
        -AttemptedBeforeEgs $script:IvFeedAttemptedBeforeEgs `
        -FeedRef $script:IvFeedRef -FeedSha256 $script:IvFeedSha256 `
        -IvFeedStatus $KnownIvFeedStatus
}
function Invoke-HistoricalInputGuards {
    param([string]$RequestedL3Mode)

    # These guards only inspect parameters and official output paths.  The
    # explicit -AsOf caller invokes them before price-basis resolution so a
    # missing provider credential cannot mask the intended guardrail result.
    $EffectiveL3Mode = $RequestedL3Mode
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

    return $EffectiveL3Mode
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
    & $PythonExe $ResolveScript '--price-basis' $PriceBasis '--out' $ResolveOut | Out-Null
    $ResolveExit = $LASTEXITCODE
    if ($ResolveExit -ne 0 -or -not (Test-Path $ResolveOut)) {
        Write-Host "[FATAL] canonical as_of resolution failed (resolve_canonical_asof.py exit $ResolveExit); check network / TUSHARE_TOKEN, or pass -AsOf <trading-day> explicitly." -ForegroundColor Red
        exit 1
    }
    $Resolved = Get-Content -Raw -Encoding UTF8 $ResolveOut | ConvertFrom-Json
    Remove-Item -Force $ResolveOut -ErrorAction SilentlyContinue
    $AsOf = [string]$Resolved.as_of
    $PriceAsOf = [string]$Resolved.price_as_of
    $IsHistoricalAsOf = $false   # canonical = 即将到来/当前未收盘的交易日,按定义恒 live(as_of>=run_date)
    if ([string]::IsNullOrWhiteSpace($AsOf)) {
        Write-Host "[FATAL] canonical resolver returned an empty as_of." -ForegroundColor Red
        exit 1
    }
    if ([string]::IsNullOrWhiteSpace($PriceAsOf)) {
        Write-Host "[FATAL] canonical resolver returned no officially settled price date." -ForegroundColor Red
        exit 1
    }
    Write-Host "[CANONICAL] as_of=$AsOf (resolved)  run_date=$RunDate  mode=live  price_basis=$PriceBasis  price_as_of=$PriceAsOf" -ForegroundColor Cyan
    $EffectiveL3Mode = Invoke-HistoricalInputGuards -RequestedL3Mode $L3Mode
} else {
    # --- 显式 -AsOf → live/historical 仍用纯日期比较分类（无需网络）---
    # as_of < 今天 = historical(真·过去回放,须显式 -L3Mode pit/neutralize);as_of >= 今天 = live(今日/前瞻交易日)。
    # as_of 交易日有效性由 egs_main.set_asof 兜底(拒非交易日);与 egs/pipeline 的 as_of>=run_date live 判据一致。
    $IsHistoricalAsOf = ([string]::Compare([string]$AsOf, [string]$RunDate, [System.StringComparison]::Ordinal) -lt 0)
    # Historical -AsOf parameter guards must run before explicit price-basis resolution.
    $EffectiveL3Mode = Invoke-HistoricalInputGuards -RequestedL3Mode $L3Mode
    # --- 但价格基准必须与 canonical 同源：走同一个解析器（需 trade_cal，故需网络）---
    # 这里以前是 `$PriceAsOf = $AsOf`，即显式入口用「决策日当日收盘」、canonical 入口用
    # 「上一个已收盘交易日」，同一决策日两个价格。删掉那条分支是本刀的核心；代价是显式
    # -AsOf 路径从此也需要拉一次 trade_cal——「上一个已收盘交易日」离开日历算不出来，
    # 给它留一条离线近似就等于把第二种行为装回来。
    $ResolveScript = Join-Path $ProjectRoot 'runners\resolve_canonical_asof.py'
    $ResolveOut = Join-Path $env:TEMP "a_short_price_asof_$PID.json"
    & $PythonExe $ResolveScript '--price-as-of-for' $AsOf '--price-basis' $PriceBasis '--out' $ResolveOut | Out-Null
    $ResolveExit = $LASTEXITCODE
    if ($ResolveExit -ne 0 -or -not (Test-Path $ResolveOut)) {
        Write-Host "[FATAL] price basis resolution failed for -AsOf $AsOf (exit $ResolveExit); check network / TUSHARE_TOKEN. -PriceBasis close is refused unless -AsOf is a true past replay (as_of < run_date); on a live decision day it would re-create the retired same-day-close behaviour." -ForegroundColor Red
        exit 1
    }
    $ResolvedPrice = Get-Content -Raw -Encoding UTF8 $ResolveOut | ConvertFrom-Json
    Remove-Item -Force $ResolveOut -ErrorAction SilentlyContinue
    $PriceAsOf = [string]$ResolvedPrice.price_as_of
    if ([string]::IsNullOrWhiteSpace($PriceAsOf)) {
        Write-Host "[FATAL] price basis resolver returned no price date for -AsOf $AsOf." -ForegroundColor Red
        exit 1
    }
    Write-Host "[EXPLICIT] as_of=$AsOf  run_date=$RunDate  mode=$(if($IsHistoricalAsOf){'historical'}else{'live'})  price_basis=$PriceBasis  price_as_of=$PriceAsOf" -ForegroundColor Cyan
}
# O24: inspect only the existing private ratchet envelope before this run.
# A same/future-date envelope means formal state already exists and the
# selector must not switch official; a malformed envelope blocks fail-closed.
$FormalStateCommitted = $false
if ($Account) {
    $RatchetStatePath = Join-Path $ProjectRoot 'state\a_short\holding_ratchet\ratchet_state.json'
    if (Test-Path -LiteralPath $RatchetStatePath -PathType Leaf) {
        try {
            $PriorRatchet = Get-Content -Raw -Encoding UTF8 -LiteralPath $RatchetStatePath | ConvertFrom-Json
            $PriorRatchetAsOf = [string]$PriorRatchet.as_of
            $FormalStateCommitted = (-not [string]::IsNullOrWhiteSpace($PriorRatchetAsOf)) -and
                ([string]::Compare($PriorRatchetAsOf, [string]$AsOf, [System.StringComparison]::Ordinal) -ge 0)
        } catch {
            $FormalStateCommitted = $true
            Write-Host "[FATAL] existing holding-ratchet state is unreadable; official selection is blocked." -ForegroundColor Red
        }
    }
}
# V5-A: this key was allocated before preflight/guard failures so every
# revision-scoped writer below receives the exact same value.
Write-Host "run revision:  $RunRevisionId" -ForegroundColor DarkGray
# P4: de-identified per-run manifests for the post-run health companion.
$LauncherSidecarOutcomes = @()
$script:IvFeedAttemptedBeforeEgs = $false
$script:IvFeedStatus = 'not_requested'
$script:IvFeedRef = $null
$script:IvFeedSha256 = $null
$script:IvFeedFailureDetailRef = ''
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
        [string]$ErrorDetail = $null,
        [string]$SkipReason = $null,
        [string]$ExpectedDataThrough = $null,
        [string]$ObservedDecisionAsOf = $null,
        [string]$ObservedDataThrough = $null,
        [object]$AttemptedBeforeEgs = $null,
        [string]$FeedRef = $null,
        [string]$FeedSha256 = $null,
        [string]$IvFeedStatus = $null
    )
    $Outcome = [ordered]@{
        name = $Name; expected = $Expected; attempted = $Attempted
        execution_status = $ExecutionStatus; progress_status = $ProgressStatus
        expected_data_through = $ExpectedDataThrough
        observed_decision_as_of = $ObservedDecisionAsOf
        observed_data_through = $ObservedDataThrough
        error_code = $ErrorCode; error_detail = $ErrorDetail; skip_reason = $SkipReason
    }
    if ($null -ne $AttemptedBeforeEgs) { $Outcome['attempted_before_egs'] = [bool]$AttemptedBeforeEgs }
    if (-not [string]::IsNullOrWhiteSpace($IvFeedStatus)) { $Outcome['iv_feed_status'] = $IvFeedStatus }
    if (-not [string]::IsNullOrWhiteSpace($FeedRef)) { $Outcome['feed_ref'] = $FeedRef }
    if (-not [string]::IsNullOrWhiteSpace($FeedSha256)) { $Outcome['feed_sha256'] = $FeedSha256 }
    $script:LauncherSidecarOutcomes += $Outcome
}
function New-SharedCacheOutcomeReadResult {
    param([bool]$Valid, [string]$ErrorCode = $null, [object]$Outcome = $null)
    return [pscustomobject]@{
        valid = $Valid
        error_code = $ErrorCode
        outcome = $Outcome
    }
}
function Read-SharedCacheBuildOutcome {
    param([string]$Path, [string]$ExpectedRunDate)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return New-SharedCacheOutcomeReadResult -Valid $false -ErrorCode 'cache_outcome_missing'
    }
    try {
        $Outcome = Get-Content -Raw -Encoding UTF8 -LiteralPath $Path -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    } catch {
        return New-SharedCacheOutcomeReadResult -Valid $false -ErrorCode 'cache_outcome_invalid_json'
    }
    if ($null -eq $Outcome -or $Outcome -is [System.Array]) {
        return New-SharedCacheOutcomeReadResult -Valid $false -ErrorCode 'cache_outcome_invalid_json'
    }
    $Required = @(
        'schema_name', 'schema_version', 'run_date', 'status', 'provider_calls',
        'deferred_symbols_by_consumer', 'production_unchanged'
    )
    $Allowed = @($Required + @('error_code', 'error_detail'))
    foreach ($RequiredName in $Required) {
        if ($null -eq $Outcome.PSObject.Properties[$RequiredName]) {
            return New-SharedCacheOutcomeReadResult -Valid $false -ErrorCode 'cache_outcome_schema_invalid'
        }
    }
    foreach ($Property in $Outcome.PSObject.Properties) {
        if ($Allowed -notcontains [string]$Property.Name) {
            return New-SharedCacheOutcomeReadResult -Valid $false -ErrorCode 'cache_outcome_schema_invalid'
        }
    }
    if ([string]$Outcome.schema_name -ne 'a_short_shared_cache_build_outcome' -or
        [string]$Outcome.schema_version -ne '1.1.0' -or
        [string]$Outcome.run_date -notmatch '^\d{8}$' -or
        $Outcome.production_unchanged -ne $true) {
        return New-SharedCacheOutcomeReadResult -Valid $false -ErrorCode 'cache_outcome_schema_invalid'
    }
    if ([string]$Outcome.run_date -ne [string]$ExpectedRunDate) {
        return New-SharedCacheOutcomeReadResult -Valid $false -ErrorCode 'cache_outcome_wrong_run_date'
    }
    $Statuses = @(
        'no_frozen_v2_captures', 'no_frozen_consumer_captures', 'cache_current',
        'deferred_due_to_budget', 'cache_updated', 'cache_updated_with_deferrals', 'failed'
    )
    $Status = [string]$Outcome.status
    if ($Statuses -notcontains $Status) {
        return New-SharedCacheOutcomeReadResult -Valid $false -ErrorCode 'cache_outcome_unknown_status'
    }
    if ($Status -eq 'failed') {
        $FailureCode = [string]$Outcome.error_code
        $FailureDetail = [string]$Outcome.error_detail
        if ([string]::IsNullOrWhiteSpace($FailureCode) -or $FailureCode -notmatch '^[a-z0-9_]+$' -or
            $FailureCode.Length -gt 128 -or [string]::IsNullOrWhiteSpace($FailureDetail) -or
            $FailureDetail.Length -gt 512 -or $FailureDetail -match '[\r\n]') {
            return New-SharedCacheOutcomeReadResult -Valid $false -ErrorCode 'cache_outcome_schema_invalid'
        }
    }
    if ($null -eq $Outcome.provider_calls -or $Outcome.provider_calls -is [string]) {
        return New-SharedCacheOutcomeReadResult -Valid $false -ErrorCode 'cache_outcome_schema_invalid'
    }
    $ProviderCalls = 0.0
    try { $ProviderCalls = [double]$Outcome.provider_calls } catch {
        return New-SharedCacheOutcomeReadResult -Valid $false -ErrorCode 'cache_outcome_schema_invalid'
    }
    if ($Outcome.provider_calls -is [bool] -or [double]::IsNaN($ProviderCalls) -or
        [double]::IsInfinity($ProviderCalls) -or $ProviderCalls -lt 0 -or
        [math]::Truncate($ProviderCalls) -ne $ProviderCalls) {
        return New-SharedCacheOutcomeReadResult -Valid $false -ErrorCode 'cache_outcome_schema_invalid'
    }
    $Deferred = $Outcome.deferred_symbols_by_consumer
    if ($null -eq $Deferred -or $Deferred -is [System.Array] -or $Deferred -is [string] -or
        $Deferred -is [ValueType]) {
        return New-SharedCacheOutcomeReadResult -Valid $false -ErrorCode 'cache_outcome_invalid'
    }
    $DeferredTotal = 0.0
    foreach ($Property in $Deferred.PSObject.Properties) {
        if ($null -eq $Property.Value -or $Property.Value -is [string]) {
            return New-SharedCacheOutcomeReadResult -Valid $false -ErrorCode 'cache_outcome_schema_invalid'
        }
        $Count = 0.0
        try { $Count = [double]$Property.Value } catch {
            return New-SharedCacheOutcomeReadResult -Valid $false -ErrorCode 'cache_outcome_schema_invalid'
        }
        if ($Property.Value -is [bool] -or [double]::IsNaN($Count) -or
            [double]::IsInfinity($Count) -or $Count -lt 0 -or
            [math]::Truncate($Count) -ne $Count) {
            return New-SharedCacheOutcomeReadResult -Valid $false -ErrorCode 'cache_outcome_invalid'
        }
        $DeferredTotal += $Count
    }
    if (($Status -like 'no_frozen_*' -and ($ProviderCalls -ne 0 -or $DeferredTotal -ne 0)) -or
        ($Status -notlike 'no_frozen_*' -and $Status -ne 'failed' -and $ProviderCalls -lt 1) -or
        ($Status -in @('cache_current', 'cache_updated') -and $DeferredTotal -ne 0) -or
        ($Status -in @('deferred_due_to_budget', 'cache_updated_with_deferrals') -and $DeferredTotal -le 0)) {
        return New-SharedCacheOutcomeReadResult -Valid $false -ErrorCode 'cache_outcome_schema_invalid'
    }
    return New-SharedCacheOutcomeReadResult -Valid $true -Outcome $Outcome
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

# --- Stage 1: build the one IV feed, then pass that exact artifact into egs_main ---
# The canonical resolver has already fixed AsOf/PriceAsOf above.  A failed build
# never makes EGS read an older file at the same path.
$script:FinalExitCode = 0
$script:M67InvocationState = if ($SkipSemanticRisk) { 'skipped' } else { 'requested' }
$script:M67FailureReason = $null
$script:M67FailureCode = 0
$script:IvFeedReady = $false
$script:IvFeedAttemptedBeforeEgs = $false
$script:IvFeedStatus = 'not_requested'
$script:IvFeedSha256 = $null
$script:IvFeedFailureDetailRef = ''
$PublicRevisionDir = Join-Path $ProjectRoot "result\a_short\$AsOf\revisions\$RunRevisionId"
$ResearchRevisionDir = Join-Path $ProjectRoot "research\results\a_short\$AsOf\revisions\$RunRevisionId"
# All active V5-A writers and P4 readers resolve the revision directory above.
$PrivateRevisionDir = Join-Path $ProjectRoot "state\a_short\weekly_private\weeks\$AsOf\revisions\$RunRevisionId"
$M67Dir = if ($Account) { $PrivateRevisionDir } else { $ResearchRevisionDir }
$SemAnalysisInput = Join-Path $PublicRevisionDir 'analysis_input.json'
$IvFeed = Join-Path $ResearchRevisionDir 'iv_feed.json'
$Phase4ReportDir = Join-Path $PublicRevisionDir 'reports'
# IV failure evidence is public/de-identified and must share the IV revision
# root even when M6.7's successful output is private under -Account.
$IvFailureReceipt = Join-Path $ResearchRevisionDir "iv_feed_failure_$PID.json"
$IvFailureDetailRef = ''
$M67Out = Join-Path $M67Dir "weekly_m67.json"
$OverlayPath = Join-Path $PublicRevisionDir 'overlay.json'
$script:IvFeedRef = "research/results/a_short/$AsOf/revisions/$RunRevisionId/iv_feed.json"

if (-not $SkipSemanticRisk) {
    $script:IvFeedAttemptedBeforeEgs = $true
    if (Test-Path -LiteralPath $IvFailureReceipt -PathType Leaf) {
        Remove-Item -LiteralPath $IvFailureReceipt -Force -ErrorAction Stop
    }
    Write-Host "[0/4] Building market IV feed before EGS: runners\a_short_iv_feed_build.py --as-of $AsOf ..." -ForegroundColor Yellow
    & $PythonExe runners\a_short_iv_feed_build.py --as-of $AsOf --price-data-through $PriceAsOf --out $IvFeed --failure-receipt-out $IvFailureReceipt --run-revision-id $RunRevisionId --confirm-fetch-authorized
    $IvExitCode = $LASTEXITCODE
    if ($null -eq $IvExitCode) { $IvExitCode = 1 }
    if ($IvExitCode -eq 23) {
        $script:IvFeedStatus = 'clock_mismatch'
        $script:IvFeedFailureDetailRef = if (Test-Path -LiteralPath $IvFailureReceipt -PathType Leaf) { [System.IO.Path]::GetFileName($IvFailureReceipt) } else { '' }
        $IvFailureDetailRef = $script:IvFeedFailureDetailRef
        Write-Host "[WARN] IV feed clock mismatch; EGS will emit explicit unknown volatility and M6.7 will fail closed." -ForegroundColor Yellow
    } elseif ($IvExitCode -eq 0 -and (Test-Path -LiteralPath $IvFeed -PathType Leaf)) {
        try {
            $script:IvFeedSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $IvFeed -ErrorAction Stop).Hash.ToLowerInvariant()
            $script:IvFeedReady = $true
            $script:IvFeedStatus = 'ready'
        } catch {
            $script:IvFeedStatus = 'digest_failed'
            Write-Host "[WARN] IV feed digest could not be computed; EGS will emit explicit unknown volatility and M6.7 will fail closed." -ForegroundColor Yellow
        }
    } else {
        $script:IvFeedStatus = 'build_failed'
        $script:IvFeedFailureDetailRef = if (Test-Path -LiteralPath $IvFailureReceipt -PathType Leaf) { [System.IO.Path]::GetFileName($IvFailureReceipt) } else { '' }
        $IvFailureDetailRef = $script:IvFeedFailureDetailRef
        Write-Host "[WARN] IV feed build failed or produced no fresh artifact (exit $IvExitCode); EGS will emit explicit unknown volatility and M6.7 will fail closed." -ForegroundColor Yellow
    }
} else {
    $script:IvFeedStatus = 'not_requested'
    Write-Host "[0/4] -SkipSemanticRisk set, IV feed not requested; EGS volatility will be explicit unknown" -ForegroundColor DarkGray
}

# --- Stage 1: egs_main (the HiThink L3 graph is fetched and verified in-process) ---
$EgsArgs = @('A-EGS\egs_main.py', '--as-of', $AsOf, '--price-as-of', $PriceAsOf, '--l3-mode', $EffectiveL3Mode, '--cache-policy', $CachePolicy, '--run-revision-id', $RunRevisionId)
$EgsArgs += @('--iv-feed-status', $script:IvFeedStatus)
if ($EffectiveL3Mode -eq 'pit') {
    $EgsArgs += '--l3-pit-strict'
}
if ($script:IvFeedReady) {
    $EgsArgs += @('--iv-feed', $IvFeed)
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
    & $PythonExe runners\forward_tracker.py capture --as-of $AsOf --run-revision-id $RunRevisionId
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
        & $PythonExe runners\forward_tracker.py backfill --windows 5,10,20 --run-revision-id $RunRevisionId --official-project-root $ProjectRoot
        $TrackerBackfillExitCode = $LASTEXITCODE
        if ($null -eq $TrackerBackfillExitCode) { $TrackerBackfillExitCode = 1 }
        # Exit 3 = the process was fine but the shared forward_daily cache kept a matured
        # cohort from settling. The console banner vanishes with the terminal, so record
        # it as `stalled` instead of `succeeded` and let the health artifact carry it.
        if ($TrackerBackfillExitCode -eq 3) {
            Write-Host "[WARN] forward_tracker backfill ran, but the shared forward_daily cache is stale: the candidate-effect ledger did NOT advance. Refresh it (see the banner above); EGS/M6.7 continue unchanged." -ForegroundColor Yellow
        } elseif ($TrackerBackfillExitCode -ne 0) {
            Write-Host "[WARN] forward_tracker cache-only backfill exit $TrackerBackfillExitCode; P1 remains pending and EGS/M6.7 continue unchanged." -ForegroundColor Yellow
        }
        Add-SidecarOutcome -Name 'forward_tracker_capture' -Expected $true -Attempted $true -ExecutionStatus 'succeeded' -ProgressStatus 'advanced' -ObservedDecisionAsOf $AsOf
        if ($TrackerBackfillExitCode -eq 3) {
            Add-SidecarOutcome -Name 'forward_tracker_backfill' -Expected $true -Attempted $true -ExecutionStatus 'succeeded' -ProgressStatus 'stalled' -ErrorCode 'forward_daily_cache_stale'
        } else {
            Add-SidecarOutcome -Name 'forward_tracker_backfill' -Expected $true -Attempted $true -ExecutionStatus $(if($TrackerBackfillExitCode -eq 0){'succeeded'}else{'failed'}) -ProgressStatus $(if($TrackerBackfillExitCode -eq 0){'not_applicable'}else{'unavailable'}) -ErrorCode $(if($TrackerBackfillExitCode -eq 0){$null}else{'process_failed'})
        }
        if ($IsHistoricalAsOf) {
            Add-SidecarOutcome -Name 'theme_forward_comparison' -Expected $false -Attempted $false -ExecutionStatus 'not_due' -ProgressStatus 'not_applicable' -SkipReason 'historical_replay'
        } else {
            Write-Host "[3a/4] Running audit-only theme forward comparison sidecar ..." -ForegroundColor Yellow
            & $PythonExe runners\a_short_theme_forward_comparison.py `
                --tracker (Join-Path $ProjectRoot 'logs\forward_tracker.csv') `
                --out (Join-Path $ProjectRoot 'research\results\a_short_theme_forward_comparison.json') `
                --private-root (Join-Path $ProjectRoot 'state\a_short\theme_forward_comparison_private\v1') `
                --run-revision-id $RunRevisionId --official-project-root $ProjectRoot
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
    & $PythonExe runners\a_short_crash_veto_tracker.py update --as-of $AsOf --rule-confirmed-days 5 --run-revision-id $RunRevisionId --official-project-root $ProjectRoot --confirm-fetch-authorized
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
    Add-SidecarOutcome -Name 'iv_feed' -Expected $false -Attempted $false -ExecutionStatus 'skipped' -ProgressStatus 'not_applicable' -SkipReason 'skip_semantic_risk' -AttemptedBeforeEgs $false -IvFeedStatus $script:IvFeedStatus
    Write-Host ""
    Write-Host "[4/4] -SkipSemanticRisk set, M6.7 operation report not run" -ForegroundColor DarkGray
} else {
    Write-Host ""
    if (-not (Test-Path $SemAnalysisInput)) {
        Add-SidecarOutcome -Name 'iv_feed' -Expected $true -Attempted $true -ExecutionStatus 'failed' -ProgressStatus 'unavailable' -ErrorCode 'analysis_input_missing' -AttemptedBeforeEgs $script:IvFeedAttemptedBeforeEgs -FeedRef $script:IvFeedRef -FeedSha256 $script:IvFeedSha256 -IvFeedStatus $script:IvFeedStatus
        Set-M67Failure -Reason 'analysis_input_missing' -ExitCode 21 `
            -AttemptedBeforeEgs $script:IvFeedAttemptedBeforeEgs -FeedRef $script:IvFeedRef -FeedSha256 $script:IvFeedSha256 `
            -IvFeedStatus $script:IvFeedStatus -Directory $M67Dir
    } else {
        # 持仓恒列入隐私护栏(固化):带 -Account 的周报含真实持仓(代码/成本/止损)→ 落 gitignored 私密目录
        # state\a_short\weekly_private\<as_of>\(.gitignore: state/*/weekly_private/),绝不入 git 追踪的 research lane。
        # 无 -Account(observation-only、无持仓)→ 仍落标准 research\results\a_short\<as_of>\(可留作证据)。
        # pipeline 侧另有同口径硬护栏,直接调用绕过本脚本也拦得住。
        if (-not $script:IvFeedReady) {
            Add-SidecarOutcome -Name 'iv_feed' -Expected $true -Attempted $true -ExecutionStatus 'failed' -ProgressStatus 'unavailable' -ErrorCode 'process_failed' -AttemptedBeforeEgs $script:IvFeedAttemptedBeforeEgs -FeedRef $script:IvFeedRef -FeedSha256 $script:IvFeedSha256 -IvFeedStatus $script:IvFeedStatus
            Set-M67Failure -Reason 'iv_feed_failed' -ExitCode 22 -FailureDetailRef $IvFailureDetailRef -AnalysisInput $SemAnalysisInput `
                -AttemptedBeforeEgs $script:IvFeedAttemptedBeforeEgs -FeedRef $script:IvFeedRef -FeedSha256 $script:IvFeedSha256 `
                -IvFeedStatus $script:IvFeedStatus -Directory $M67Dir
        } else {
            Add-SidecarOutcome -Name 'iv_feed' -Expected $true -Attempted $true -ExecutionStatus 'succeeded' -ProgressStatus 'advanced' -ObservedDecisionAsOf $AsOf -AttemptedBeforeEgs $script:IvFeedAttemptedBeforeEgs -FeedRef $script:IvFeedRef -FeedSha256 $script:IvFeedSha256 -IvFeedStatus $script:IvFeedStatus
            $M67Args = @('runners\a_short_weekly_pipeline.py', '--as-of', $AsOf, '--price-as-of', $PriceAsOf, '--run-date', $RunDate, '--run-revision-id', $RunRevisionId, '--official-project-root', $ProjectRoot, '--analysis-input', $SemAnalysisInput, '--iv-feed-status', $script:IvFeedStatus, '--iv-feed', $IvFeed, '--out', $M67Out, '--phase4-report-dir', $Phase4ReportDir, '--confirm-fetch-authorized')
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
                $SharedCacheOutcomePath = Join-Path $M67Dir 'shared_cache_build.outcome.json'
                $MarginOverheatCashControlRoot = Join-Path $ProjectRoot 'state\a_short\margin_overheat_cash_control_private\v1'
                $OverlayAdjudicationRoot = Join-Path $ProjectRoot 'state\a_short\overlay_adjudication_private\v1'
                $OverlayAdjudicationStage3 = Join-Path $PublicRevisionDir 'stage3_selection_snapshot.json'
                $OverlayAdjudicationSource = Join-Path $PublicRevisionDir 'stage3_overlay_score.json'
                $OverlayAdjudicationMarker = Join-Path $PublicRevisionDir 'official_publish.json'
                $OverlayAdjudicationPublicJson = Join-Path $ProjectRoot 'research\results\a_short\overlay_adjudication_summary.json'
                $OverlayAdjudicationPublicMarkdown = Join-Path $ProjectRoot 'research\results\a_short\overlay_adjudication_summary.md'
                $IndustryWeightP5Root = Join-Path $ProjectRoot 'state\a_short\industry_weight_comparison_private\v1'
                $IndustryWeightSource = Join-Path $PublicRevisionDir 'egs_weight_comparison.json'
                $TargetPolicyLedger = Join-Path $ProjectRoot 'logs\a_short_target_policy_comparison.json'
                $TargetPolicyPublicJson = Join-Path $ProjectRoot 'research\results\a_short\target_policy_comparison_summary.json'
                $TargetPolicyPublicMarkdown = Join-Path $ProjectRoot 'research\results\a_short\target_policy_comparison_summary.md'
                $FinalActionLedger = Join-Path $ProjectRoot 'logs\a_short_final_action_validation.json'
                $OfficialOperationEvidenceRoot = Join-Path $ProjectRoot 'state\a_short\operation_evidence_private\v1'
                Write-Host "[ADVISORY] Updating bounded A-short shared private cache ..." -ForegroundColor Yellow
                # A same-path old receipt can describe a prior successful run.  Remove it
                # before invoking the writer; a failed process must never inherit that
                # success-looking status through the sidecar health chain.
                $SharedCacheInvalidated = Invalidate-M67Artifact -LiteralPath $SharedCacheOutcomePath
                if (-not $SharedCacheInvalidated) {
                    Write-Host "[WARN] A-short shared cache outcome receipt could not be invalidated; refusing to start the writer." -ForegroundColor Yellow
                    $FactorComparisonCacheExitCode = 1
                } else {
                    & $PythonExe runners\a_short_factor_comparison_v2_cache_build.py --root $FactorComparisonV2Root --run-date $RunDate --outcome-json $SharedCacheOutcomePath --industry-weight-root $IndustryWeightP5Root --target-policy-root $TargetPolicyLedger --final-action-validation-root $FinalActionLedger --official-operation-evidence-root $OfficialOperationEvidenceRoot --overlay-adjudication-root $OverlayAdjudicationRoot
                    $FactorComparisonCacheExitCode = $LASTEXITCODE
                }
                if ($null -eq $FactorComparisonCacheExitCode) { $FactorComparisonCacheExitCode = 1 }
                $SharedCacheExecutionStatus = 'failed'
                $SharedCacheProgressStatus = 'unavailable'
                $SharedCacheErrorCode = 'process_failed'
                $SharedCacheErrorDetail = $null
                $SharedCacheRead = Read-SharedCacheBuildOutcome -Path $SharedCacheOutcomePath -ExpectedRunDate $RunDate
                if ($FactorComparisonCacheExitCode -eq 0) {
                    if ($SharedCacheRead.valid) {
                        switch ([string]$SharedCacheRead.outcome.status) {
                            { $_ -like 'no_frozen_*' } {
                                $SharedCacheExecutionStatus = 'succeeded'
                                $SharedCacheProgressStatus = 'not_applicable'
                                $SharedCacheErrorCode = $null
                            }
                            'cache_current' {
                                $SharedCacheExecutionStatus = 'succeeded'
                                $SharedCacheProgressStatus = 'already_current'
                                $SharedCacheErrorCode = $null
                            }
                            'cache_updated' {
                                $SharedCacheExecutionStatus = 'succeeded'
                                $SharedCacheProgressStatus = 'advanced'
                                $SharedCacheErrorCode = $null
                            }
                            'cache_updated_with_deferrals' {
                                $SharedCacheExecutionStatus = 'succeeded'
                                $SharedCacheProgressStatus = 'stalled'
                                $SharedCacheErrorCode = 'cache_partial_due_to_budget'
                            }
                            'deferred_due_to_budget' {
                                $SharedCacheExecutionStatus = 'succeeded'
                                $SharedCacheProgressStatus = 'stalled'
                                $SharedCacheErrorCode = 'cache_deferred_due_to_budget'
                            }
                            'failed' {
                                $SharedCacheErrorCode = [string]$SharedCacheRead.outcome.error_code
                                $SharedCacheErrorDetail = [string]$SharedCacheRead.outcome.error_detail
                            }
                        }
                    } else {
                        $SharedCacheErrorCode = [string]$SharedCacheRead.error_code
                    }
                } elseif ($SharedCacheRead.valid -and [string]$SharedCacheRead.outcome.status -eq 'failed') {
                    $SharedCacheErrorCode = [string]$SharedCacheRead.outcome.error_code
                    $SharedCacheErrorDetail = [string]$SharedCacheRead.outcome.error_detail
                }
                if ($SharedCacheExecutionStatus -eq 'failed') {
                    Write-Host "[WARN] A-short shared comparison cache unavailable ($SharedCacheErrorCode; exit $FactorComparisonCacheExitCode); M6.7/V14.3/overlay continue unchanged." -ForegroundColor Yellow
                }
                Add-SidecarOutcome -Name 'shared_cache_build' -Expected $true -Attempted $true -ExecutionStatus $SharedCacheExecutionStatus -ProgressStatus $SharedCacheProgressStatus -ErrorCode $SharedCacheErrorCode -ErrorDetail $SharedCacheErrorDetail
                # Freeze the normalized live decision only after M6.7 publishes its matching bundle.
                $M67Args += @('--factor-comparison-v2-root', $FactorComparisonV2Root,
                              '--factor-comparison-v2-daily-cache', $FactorComparisonV2Cache,
                              '--factor-comparison-v2-forward')
                # Margin-overheat is comparison-only at this stage: reuse the
                # same approved cache, but do not mark the capture forward-eligible.
                $M67Args += @('--margin-overheat-cash-control-root', $MarginOverheatCashControlRoot,
                              '--margin-overheat-cash-control-daily-cache', $FactorComparisonV2Cache)
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
                              '--target-policy-public-summary', $TargetPolicyPublicJson,
                              '--target-policy-public-markdown', $TargetPolicyPublicMarkdown,
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
                    $RunM67 = $false
                    Write-Host "[FATAL] M6.7 requested but -Account path was not found: $Account" -ForegroundColor Red
                    Set-M67Failure -Reason 'account_path_missing' -ExitCode 23 -AnalysisInput $SemAnalysisInput -IvFeedStatus $script:IvFeedStatus -Directory $M67Dir
                }
            } else {
                Write-Host "[WARN] M6.7 no -Account: observation-only (no position sizing/holding-state). The weekly_m67 artifact is marked sizing_mode=observation_only_no_account - 建仓 candidates render as 观察 (sizing artifact, NOT a real avoid signal). Pass -Account <a_short_account_bundle JSON generated by a_short_account_state_from_manual_tables.py> for real sizing and holding-state decisions." -ForegroundColor Yellow
            }
            if ($RunM67 -and $M67InvocationState -eq 'requested') {
                Write-Host "[4/4] Running M6.7 pipeline: runners\a_short_weekly_pipeline.py --as-of $AsOf ..." -ForegroundColor Yellow
                & $PythonExe @M67Args
                $M67ExitCode = $LASTEXITCODE
                if ($null -eq $M67ExitCode) { $M67ExitCode = 1 }
                if ($M67ExitCode -ne 0) {
                    # requested M6.7 是本次正式运维产物；失败必须显式传播，不能返回选股成功假象。
                    Set-M67Failure -Reason 'weekly_pipeline_failed' -ExitCode $M67ExitCode -AnalysisInput $SemAnalysisInput -IvFeedStatus $script:IvFeedStatus -Directory $M67Dir
                } else {
                    $OperationLoaderCode = @'
import json
import sys

sys.path.insert(0, sys.argv[1])
from runners.a_short_weekly_pipeline import validate_published_weekly_operation_bundle

bundle = validate_published_weekly_operation_bundle(sys.argv[2])
stage = str(bundle.receipt.get("stage_status") or "")
if stage not in {"complete", "degraded_no_new_entries", "partial_holdings_only"}:
    raise SystemExit(f"invalid operation stage: {stage!r}")
print(json.dumps({
    "stage_status": stage,
    "weekly_path": str(bundle.weekly_path),
    "markdown_path": str(bundle.markdown_path),
}, ensure_ascii=False))
'@
                    $OperationLoaderOutput = & $PythonExe -c $OperationLoaderCode $ProjectRoot $M67Out
                    $OperationLoaderExitCode = $LASTEXITCODE
                    if ($null -eq $OperationLoaderExitCode) { $OperationLoaderExitCode = 1 }
                    try {
                        if ($OperationLoaderExitCode -ne 0) {
                            throw "operation loader exited $OperationLoaderExitCode"
                        }
                        $OperationRecord = ($OperationLoaderOutput -join "`n") | ConvertFrom-Json
                        $OperationStage = [string]$OperationRecord.stage_status
                        if ($OperationStage -notin @('complete', 'degraded_no_new_entries', 'partial_holdings_only')) {
                            throw "operation loader returned invalid stage $OperationStage"
                        }
                    } catch {
                        Set-M67Failure -Reason 'weekly_operation_bundle_invalid' -ExitCode 24 -AnalysisInput $SemAnalysisInput -IvFeedStatus $script:IvFeedStatus -Directory $M67Dir
                    }
                    if ($script:M67InvocationState -ne 'failed') {
                        $script:M67InvocationState = $OperationStage
                        $OperationMarkdown = Join-Path $M67Dir 'weekly_m67.md'
                        Write-Host "[OPERATION] stage=$OperationStage JSON=$M67Out Markdown=$OperationMarkdown. Older analysis reports remain research-only inputs." -ForegroundColor Yellow
                    }
                }
            }
        }
    }
}

# --- Stage 5: V14.3 regime comparison ledger (旁路 sidecar; comparison-only 非生产,V14.2 仍冻结;失败绝不阻断
#     周报)。Stage 5 的 live daily 证据独立于 M6.7；只有 M6.7 complete 才绑定 raw regime + weekly report，
#     失败/跳过状态绝不伪造 D2 source binding。真·过去回放(as_of<运行日,$IsHistoricalAsOf)不推进 forward ledger。
#     无 ledger→一次性 --bootstrap(252日回填,首跑数分钟)、有→increment(秒级)。
if ($SkipRegime) {
    Add-SidecarOutcome -Name 'regime_daily' -Expected $false -Attempted $false -ExecutionStatus 'skipped' -ProgressStatus 'not_applicable' -SkipReason 'skip_regime'
    Add-SidecarOutcome -Name 'regime_action' -Expected $false -Attempted $false -ExecutionStatus 'skipped' -ProgressStatus 'not_applicable' -SkipReason 'skip_regime'
    Add-SidecarOutcome -Name 'candidate_effect' -Expected $false -Attempted $false -ExecutionStatus 'skipped' -ProgressStatus 'not_applicable' -SkipReason 'skip_regime'
    Write-Host ""
    Write-Host "[regime] -SkipRegime set, V14.3 regime comparison not run" -ForegroundColor DarkGray
} elseif ($IsHistoricalAsOf) {
    Add-SidecarOutcome -Name 'regime_daily' -Expected $false -Attempted $false -ExecutionStatus 'not_due' -ProgressStatus 'not_applicable' -SkipReason 'historical_replay'
    Add-SidecarOutcome -Name 'regime_action' -Expected $false -Attempted $false -ExecutionStatus 'not_due' -ProgressStatus 'not_applicable' -SkipReason 'historical_replay'
    Add-SidecarOutcome -Name 'candidate_effect' -Expected $false -Attempted $false -ExecutionStatus 'not_due' -ProgressStatus 'not_applicable' -SkipReason 'historical_replay'
    Write-Host ""
    Write-Host "[regime] historical -AsOf $AsOf -> skipping V14.3 regime ledger (only live runs advance the forward regime evidence)" -ForegroundColor DarkGray
} else {
    Write-Host ""
    $RegimeLedger = Join-Path $ProjectRoot "research\results\a_short\regime_daily_ledger.json"
    $RegimeIvFeed = $IvFeed
    # The daily comparison baseline is fail-closed shock. A complete M6.7 run may
    # additionally bind the raw analysis-input regime and published weekly bundle.
    $EffectiveV142Regime = 'shock'
    $RawV142Regime = 'unknown'
    $DesignCompletionAuthorized = Get-DesignCompletionAuthorized
    $RegimeArgs = @('runners\a_short_regime_comparison_runner.py', '--as-of', $AsOf,
                    '--v14_2-regime', $EffectiveV142Regime)
    if ($M67InvocationState -eq 'complete' -and $DesignCompletionAuthorized) {
        try {
            $RawV142Regime = (Get-Content -Raw -Encoding UTF8 $SemAnalysisInput | ConvertFrom-Json).market_context.market_regime.status
            if ($RawV142Regime -in @('attack', 'shock', 'defense', 'contraction')) {
                $EffectiveV142Regime = $RawV142Regime
                $RegimeArgs[4] = $EffectiveV142Regime
            }
        } catch {
            Write-Host "[regime] unable to read production regime from analysis_input; using fail-closed effective shock" -ForegroundColor Yellow
        }
        # D2 and candidate-effect are source-bound to this same complete bundle.
        $RegimeArgs += @('--v14_2-raw-regime', $RawV142Regime, '--m67-report', $M67Out)
    } elseif ($M67InvocationState -eq 'complete') {
        Write-Host "[regime] design completion is not authorized; running daily-only audit and not freezing D2/candidate-effect evidence" -ForegroundColor DarkGray
    } elseif ($M67InvocationState -in @('degraded_no_new_entries', 'partial_holdings_only')) {
        Write-Host "[regime] M6.7 stage=$M67InvocationState; running daily-only regime evidence without M6.7-dependent action/effect binding" -ForegroundColor Yellow
    } elseif ($M67InvocationState -eq 'failed') {
        Write-Host "[regime] M6.7 failed; running daily-only regime evidence without raw regime or M6.7 report binding" -ForegroundColor Yellow
    } else {
        Write-Host "[regime] M6.7 not requested; running independent daily-only regime evidence" -ForegroundColor DarkGray
    }
    if (-not (Test-Path $RegimeLedger)) {
        Write-Host "[regime] no existing ledger -> one-time --bootstrap (252-day backfill; may take several minutes)" -ForegroundColor Yellow
        $RegimeArgs += '--bootstrap'
    } else {
        Write-Host "[regime] existing ledger found -> incremental append (settled trading days since last)" -ForegroundColor Yellow
    }
    if ($script:IvFeedReady -and (Test-Path -LiteralPath $RegimeIvFeed -PathType Leaf)) {
        $RegimeArgs += @('--iv-feed', $RegimeIvFeed)
    }
    $RegimeArgs += '--confirm-fetch-authorized'
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
    if ($M67InvocationState -eq 'complete' -and -not $DesignCompletionAuthorized) {
        # The M6.7 bundle is complete, but the user has not yet declared the
        # A-short design complete. D2 and candidate-effect remain unstarted,
        # rather than looking like a failed or countable weekly observation.
        Add-SidecarOutcome -Name 'regime_action' -Expected $false -Attempted $false -ExecutionStatus 'skipped' -ProgressStatus 'not_applicable' -SkipReason 'design_not_complete'
        Add-SidecarOutcome -Name 'candidate_effect' -Expected $false -Attempted $false -ExecutionStatus 'skipped' -ProgressStatus 'not_applicable' -SkipReason 'design_not_complete'
    } elseif ($M67InvocationState -in @('degraded_no_new_entries', 'partial_holdings_only')) {
        Add-SidecarOutcome -Name 'regime_action' -Expected $false -Attempted $false -ExecutionStatus 'not_due' -ProgressStatus 'not_applicable' -SkipReason 'stage_not_complete'
        Add-SidecarOutcome -Name 'candidate_effect' -Expected $false -Attempted $false -ExecutionStatus 'not_due' -ProgressStatus 'not_applicable' -SkipReason 'stage_not_complete'
    } elseif ($M67InvocationState -eq 'failed') {
        # The daily-only invocation cannot produce a D2 action or candidate-effect
        # record. Keep both expectations visible as failed, unattempted dependencies.
        Add-SidecarOutcome -Name 'regime_action' -Expected $true -Attempted $false -ExecutionStatus 'failed' -ProgressStatus 'unavailable' -ErrorCode 'm67_failed'
        Add-SidecarOutcome -Name 'candidate_effect' -Expected $true -Attempted $false -ExecutionStatus 'failed' -ProgressStatus 'unavailable' -ErrorCode 'm67_failed'
    } elseif ($M67InvocationState -eq 'skipped') {
        Add-SidecarOutcome -Name 'regime_action' -Expected $false -Attempted $false -ExecutionStatus 'skipped' -ProgressStatus 'not_applicable' -SkipReason 'skip_semantic_risk'
        Add-SidecarOutcome -Name 'candidate_effect' -Expected $false -Attempted $false -ExecutionStatus 'skipped' -ProgressStatus 'not_applicable' -SkipReason 'skip_semantic_risk'
    } else {
        Add-SidecarOutcome -Name 'regime_action' -Expected $true -Attempted $true -ExecutionStatus $RegimeStatus -ProgressStatus $RegimeProgress -ErrorCode $RegimeError -ObservedDecisionAsOf $(if($RegimeExitCode -eq 0){$AsOf}else{$null})
        $CandidateEffectOutcome = Join-Path $ProjectRoot 'research\results\a_short\candidate_effect_outcome.json'
        $CandidateEffectStatus = 'failed'
        $CandidateEffectProgress = 'unavailable'
        $CandidateEffectError = 'candidate_effect_outcome_missing_or_invalid'
        $CandidateEffectObserved = $null
        # The receipt writer validates status/reason_code against
        # schemas/a_short_regime_candidate_effect_outcome.schema.json and refuses to write a
        # mismatched pair, so the launcher deliberately does NOT re-implement that enum table or
        # pin the schema version: one contract, one place. It checks identity and field shape
        # only, and the Python health observer stays authoritative for the real evidence clock.
        if ($RegimeExitCode -eq 0 -and (Test-Path -LiteralPath $CandidateEffectOutcome -PathType Leaf)) {
            try {
                $CandidateEffectReceipt = Get-Content -Raw -Encoding UTF8 $CandidateEffectOutcome | ConvertFrom-Json
                $CandidateEffectReceiptStatus = [string]$CandidateEffectReceipt.status
                $CandidateEffectReceiptReason = [string]$CandidateEffectReceipt.reason_code
                $CandidateEffectObservedCandidate = [string]$CandidateEffectReceipt.observed_as_of
                $CandidateEffectObservedValid = (
                    [string]::IsNullOrWhiteSpace($CandidateEffectObservedCandidate) -or
                    $CandidateEffectObservedCandidate -match '^[0-9]{8}$'
                )
                if ([string]$CandidateEffectReceipt.schema_name -eq 'a_short_regime_candidate_effect_outcome' -and
                    [string]$CandidateEffectReceipt.as_of -eq [string]$AsOf -and
                    $CandidateEffectReceiptStatus -match '^[a-z0-9_]+$' -and
                    $CandidateEffectReceiptReason -match '^[a-z0-9_]+$' -and
                    $CandidateEffectObservedValid) {
                    $CandidateEffectStatus = 'succeeded'
                    $CandidateEffectObserved = $CandidateEffectObservedCandidate
                    $CandidateEffectProgress = if ($CandidateEffectReceiptStatus -eq 'updated') { 'advanced' } elseif ([string]::IsNullOrWhiteSpace($CandidateEffectObserved)) { 'unavailable' } else { 'stalled' }
                    $CandidateEffectError = if ($CandidateEffectReceiptStatus -eq 'updated') { $null } else { $CandidateEffectReceiptReason }
                }
            } catch { }
        } elseif ($RegimeExitCode -ne 0) {
            $CandidateEffectError = 'process_failed'
        }
        Add-SidecarOutcome -Name 'candidate_effect' -Expected $true -Attempted $true -ExecutionStatus $CandidateEffectStatus -ProgressStatus $CandidateEffectProgress -ErrorCode $CandidateEffectError -ObservedDecisionAsOf $CandidateEffectObserved
    }
}

 # P4: health is a separate post-run companion.  The already-published M6.7
 # JSON/Markdown/receipt are intentionally not rewritten here.  V5-A keeps
 # this bundle inside the same revision root as IV and M6.7.
$HealthDir = $M67Dir
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
    run_revision_id = [string]$RunRevisionId
    run_id = $null
    candidate_digest = $null
    expected_sidecars = @($ManifestExpected)
    sidecars = @($LauncherSidecarOutcomes)
}
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$PipelineManifestPath = Join-Path $HealthDir 'weekly_m67.pipeline_sidecar_outcomes.json'
$LauncherManifestWritten = $false
try {
    New-Item -ItemType Directory -Force -Path $HealthDir -ErrorAction Stop | Out-Null
    $LauncherManifestTmp = "$LauncherManifestPath.tmp.$PID"
    Write-M67Utf8NoBom -LiteralPath $LauncherManifestTmp -Text (($LauncherManifest | ConvertTo-Json -Depth 8) + "`n")
    Move-Item -LiteralPath $LauncherManifestTmp -Destination $LauncherManifestPath -Force -ErrorAction Stop
    $LauncherManifestWritten = $true
} catch {
    Invalidate-M67Artifact -LiteralPath $LauncherManifestPath | Out-Null
    Write-Host "[sidecar-health] UNAVAILABLE (launcher outcome manifest closeout failed; M6.7/selection unchanged)" -ForegroundColor Red
}

if ($LauncherManifestWritten) {
    # A failed companion must never leave a previous valid health bundle visible.
    foreach ($Leaf in @('sidecar_health.receipt.json', 'sidecar_health.json', 'sidecar_health.md')) {
        Invalidate-M67Artifact -LiteralPath (Join-Path $HealthDir $Leaf) | Out-Null
    }
    $HealthArgs = @(
        'runners\a_short_weekly_sidecar_health.py', '--as-of', $AsOf,
        '--project-root', $ProjectRoot, '--out-dir', $HealthDir,
        '--launcher-outcomes', $LauncherManifestPath,
        '--run-revision-id', $RunRevisionId,
        '--m67-invocation', $(if ($SkipSemanticRisk) { 'skipped' } else { 'requested' }),
        '--iv-feed', $IvFeed
    )
    if (-not $SkipSemanticRisk) {
        $HealthArgs += @('--pipeline-outcomes', $PipelineManifestPath)
    }
    & $PythonExe @HealthArgs
    $HealthExitCode = $LASTEXITCODE
    if ($null -eq $HealthExitCode) { $HealthExitCode = 1 }
    $HealthComplete = ($HealthExitCode -eq 0)
    foreach ($Leaf in @('sidecar_health.receipt.json', 'sidecar_health.json', 'sidecar_health.md')) {
        $HealthPath = Join-Path $HealthDir $Leaf
        if (-not (Test-Path -LiteralPath $HealthPath -PathType Leaf)) {
            $HealthComplete = $false
        } elseif ((Get-Item -LiteralPath $HealthPath).Length -le 0) {
            $HealthComplete = $false
        }
    }
    if (-not $HealthComplete) {
        foreach ($Leaf in @('sidecar_health.receipt.json', 'sidecar_health.json', 'sidecar_health.md')) {
            Invalidate-M67Artifact -LiteralPath (Join-Path $HealthDir $Leaf) | Out-Null
        }
        Write-Host "[sidecar-health] UNAVAILABLE (health companion failed or returned an incomplete JSON/Markdown/receipt trio; M6.7/selection unchanged)" -ForegroundColor Red
    }
}

# V5-A closeout: only a structurally complete EGS/M6.7/IV/health bundle can
# create the immutable revision manifest.  Pointer and selection receipt are
# committed together through the Python rollback boundary; a failed selection
# leaves the previous pointer untouched and makes the run non-zero.
if ($EgsExitCode -eq 0 -and $M67InvocationState -eq 'complete' -and $HealthComplete) {
    $RevisionManifestPath = Join-Path $ResearchRevisionDir 'revision_manifest.json'
    $OfficialPointerPath = Join-Path $ProjectRoot "research\results\a_short\$AsOf\official_revision.json"
    $SelectionReceiptPath = Join-Path $ProjectRoot "research\results\a_short\$AsOf\official_selection_receipt.json"
    $RevisionTransactionDir = Join-Path $ProjectRoot "state\a_short\revision_transactions\$AsOf"
    $RevisionRoles = [ordered]@{
        analysis_input = $SemAnalysisInput
        egs_data_health = (Join-Path $PublicRevisionDir 'data_health.json')
        egs_official_publish = (Join-Path $PublicRevisionDir 'official_publish.json')
        iv_feed = $IvFeed
        weekly_m67 = $M67Out
        weekly_m67_receipt = (Join-Path $M67Dir 'weekly_m67.receipt.json')
        phase4_reports_manifest = (Join-Path $PublicRevisionDir 'phase4_reports_manifest.json')
        launcher_sidecar_outcomes = $LauncherManifestPath
        pipeline_sidecar_outcomes = $PipelineManifestPath
        sidecar_health = (Join-Path $HealthDir 'sidecar_health.json')
        sidecar_health_markdown = (Join-Path $HealthDir 'sidecar_health.md')
        sidecar_health_receipt = (Join-Path $HealthDir 'sidecar_health.receipt.json')
    }
    try {
        $ReportsIndexArgs = @(
            '-m', 'engine.a_short_run_revision', 'write-reports-index',
            '--project-root', $ProjectRoot, '--decision-as-of', $AsOf,
            '--run-revision-id', $RunRevisionId
        )
        & $PythonExe @ReportsIndexArgs
        $ReportsIndexExitCode = $LASTEXITCODE
        if ($null -eq $ReportsIndexExitCode) { $ReportsIndexExitCode = 1 }
        if ($ReportsIndexExitCode -ne 0) { throw "Phase-4 reports index writer exit $ReportsIndexExitCode" }
    } catch {
        $script:FinalExitCode = if ($script:FinalExitCode -eq 0) { 1 } else { $script:FinalExitCode }
        Write-Host "[revision] UNAVAILABLE ($($_.Exception.Message)); official pointer unchanged" -ForegroundColor Red
    }
    $MissingRevisionRoles = @($RevisionRoles.GetEnumerator() | Where-Object { -not (Test-Path -LiteralPath $_.Value -PathType Leaf) })
    if ($MissingRevisionRoles.Count -gt 0) {
        $script:FinalExitCode = if ($script:FinalExitCode -eq 0) { 1 } else { $script:FinalExitCode }
        Write-Host "[revision] UNAVAILABLE (formal role missing; official pointer unchanged)" -ForegroundColor Red
    } else {
        try {
            $AnalysisPayload = Get-Content -Raw -Encoding UTF8 -LiteralPath $SemAnalysisInput | ConvertFrom-Json
            $RunIdentity = $AnalysisPayload.source.run_identity
            $ManifestArgs = @(
                '-m', 'engine.a_short_run_revision', 'write-manifest',
                '--project-root', $ProjectRoot, '--manifest', $RevisionManifestPath,
                '--decision-as-of', $AsOf, '--run-date', $RunDate,
                '--price-data-through', $PriceAsOf, '--run-revision-id', $RunRevisionId,
                '--run-id', [string]$RunIdentity.run_id, '--candidate-digest', [string]$RunIdentity.candidate_digest
            )
            foreach ($Role in $RevisionRoles.GetEnumerator()) {
                $ManifestArgs += @('--role', "$($Role.Key)=$($Role.Value)")
            }
            & $PythonExe @ManifestArgs
            $ManifestExitCode = $LASTEXITCODE
            if ($null -eq $ManifestExitCode) { $ManifestExitCode = 1 }
            if ($ManifestExitCode -ne 0) { throw "revision manifest writer exit $ManifestExitCode" }
            $SelectArgs = @(
                '-m', 'engine.a_short_run_revision', 'select-official',
                '--pointer', $OfficialPointerPath, '--selection-receipt', $SelectionReceiptPath,
                '--manifest', $RevisionManifestPath, '--transaction-dir', $RevisionTransactionDir,
                '--run-revision-id', $RunRevisionId, '--decision-as-of', $AsOf,
                '--reason', 'normal_weekly'
            )
            # Historical replays are validation-only after the decision cutoff.
            # They still get a revision manifest for audit, but must not ask the
            # selector to switch/choose an official pointer; doing so would turn
            # a valid replay into a hard cutoff failure or mutate current view.
            if ($IsHistoricalAsOf) {
                $SelectionStatus = 'validation_only'
                Write-Host "[revision] historical replay retained validation-only; official pointer unchanged" -ForegroundColor DarkGray
            } else {
                if ($FormalStateCommitted) { $SelectArgs += '--formal-state-committed' }
                $SelectionRaw = & $PythonExe @SelectArgs
                $SelectionExitCode = $LASTEXITCODE
                if ($null -eq $SelectionExitCode) { $SelectionExitCode = 1 }
                if ($SelectionExitCode -ne 0) { throw "official revision selector exit $SelectionExitCode" }
                try {
                    $SelectionResult = (($SelectionRaw -join "`n") | ConvertFrom-Json -ErrorAction Stop)
                } catch {
                    throw "official revision selector returned invalid status JSON"
                }
                $SelectionStatus = [string]$SelectionResult.status
            }
            if ($SelectionStatus -in @('selected', 'already_current')) {
                $SettlementArgs = @(
                    'runners\a_short_official_settlement.py', '--project-root', $ProjectRoot,
                    '--as-of', $AsOf, '--run-revision-id', $RunRevisionId
                )
                if ($IsHistoricalAsOf) { $SettlementArgs += '--skip-forward' }
                & $PythonExe @SettlementArgs
                $OfficialSettlementExitCode = $LASTEXITCODE
                if ($null -eq $OfficialSettlementExitCode) { $OfficialSettlementExitCode = 1 }
                if ($OfficialSettlementExitCode -ne 0) {
                    throw "official settlement runner exit $OfficialSettlementExitCode"
                }
                Write-Host "[revision] manifest + official pointer + post-selector settlement committed for $RunRevisionId" -ForegroundColor Yellow
            } elseif ($SelectionStatus -in @('equivalent_replay', 'validation_only')) {
                Write-Host "[revision] non-official replay retained audit-only; official pointer unchanged" -ForegroundColor DarkGray
            } else {
                throw "official revision selector returned unexpected status: $SelectionStatus"
            }
        } catch {
            $script:FinalExitCode = if ($script:FinalExitCode -eq 0) { 1 } else { $script:FinalExitCode }
            Write-Host "[revision] UNAVAILABLE ($($_.Exception.Message)); official pointer unchanged" -ForegroundColor Red
        }
    }
}
Write-Host "=== Pipeline done ===" -ForegroundColor Cyan
exit $FinalExitCode
