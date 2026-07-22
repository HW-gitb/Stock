function Resolve-AshortPython {
    param([string]$Requested)

    $PinnedPython = 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe'
    if (-not (Test-Path -LiteralPath $PinnedPython -PathType Leaf)) {
        throw "Pinned Stock Python was not found: $PinnedPython"
    }
    $PinnedResolved = (Resolve-Path -LiteralPath $PinnedPython).Path

    # These legacy knobs are validation-only: a non-pinned value must never
    # redirect a Codex run to another interpreter.
    foreach ($item in @(
        @{ label = '-PythonExe'; value = $Requested },
        @{ label = 'STOCK_PYTHON'; value = $env:STOCK_PYTHON },
        @{ label = 'STOCK_TEST_PYTHON'; value = $env:STOCK_TEST_PYTHON }
    )) {
        if ([string]::IsNullOrWhiteSpace($item.value)) { continue }
        if (-not (Test-Path -LiteralPath $item.value -PathType Leaf)) {
            throw "$($item.label) is not the pinned Stock Python: $($item.value)"
        }
        $Resolved = (Resolve-Path -LiteralPath $item.value).Path
        if (-not [string]::Equals($Resolved, $PinnedResolved, [StringComparison]::OrdinalIgnoreCase)) {
            throw "$($item.label) must equal the pinned Stock Python: $PinnedResolved"
        }
    }
    return $PinnedResolved
}
