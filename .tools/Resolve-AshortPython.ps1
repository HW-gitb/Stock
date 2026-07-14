function Resolve-AshortPython {
    param([string]$Requested)

    $Candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($Requested)) { $Candidates += $Requested }
    if (-not [string]::IsNullOrWhiteSpace($env:STOCK_PYTHON)) { $Candidates += $env:STOCK_PYTHON }
    if (-not [string]::IsNullOrWhiteSpace($env:STOCK_TEST_PYTHON)) { $Candidates += $env:STOCK_TEST_PYTHON }

    foreach ($Name in @('python', 'python3', 'py')) {
        $Command = Get-Command $Name -ErrorAction SilentlyContinue
        if ($Command) { $Candidates += $Command.Source }
    }
    foreach ($Root in @(
        (Join-Path $HOME 'AppData\Local\Programs\Python'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)}
    )) {
        if ([string]::IsNullOrWhiteSpace($Root) -or -not (Test-Path $Root)) { continue }
        $Candidates += Get-ChildItem $Root -Directory -Filter 'Python*' -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName 'python.exe' }
    }

    foreach ($Candidate in $Candidates | Select-Object -Unique) {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $Candidate).Path
        }
    }
    throw "No Python interpreter found. Install Python 3.10+ or set STOCK_PYTHON / pass -PythonExe."
}
