param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PythonArgs
)

$ErrorActionPreference = 'Stop'

# Codex must use the user's dependency-complete host Python. The Codex
# sandbox runtime is intentionally not a project dependency environment.
$MainPython = 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe'
if (-not (Test-Path -LiteralPath $MainPython -PathType Leaf)) {
    [Console]::Error.WriteLine("The pinned Stock Python was not found: $MainPython")
    exit 1
}

try {
    & $MainPython @PythonArgs
    $PythonExit = $LASTEXITCODE
    if ($null -eq $PythonExit) {
        throw 'Pinned Stock Python did not return an exit code.'
    }
    exit [int]$PythonExit
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
