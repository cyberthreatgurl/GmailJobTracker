param(
    [switch]$Apply,
    [string]$Preserve = ""
)

Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    Write-Error "Python executable not found at $pythonExe. Adjust the script to point to your venv python.";
    exit 2
}

$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$baseArgs = "manage.py audit_interview_flags --threshold 0.7 --output scripts/audit_interview_report_$ts.json"

if ($Preserve) {
    $baseArgs += " --preserve=$Preserve"
}

if ($Apply) {
    $baseArgs += " --apply"
    Write-Host "Running audit (and applying changes) with preserve: $Preserve"
} else {
    Write-Host "Running audit (dry-run); no changes will be applied. Use -Apply to clear flagged rows."
}

# Run the command
Push-Location $repoRoot
try {
    & $pythonExe $baseArgs
    $exit = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($exit -ne 0) {
    Write-Error "Audit command exited with code $exit"
    exit $exit
}

Write-Host "Done. Reports and backups are written to the scripts/ directory."
