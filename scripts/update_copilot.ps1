# update_copilot.ps1 — Consolidate all Git repo files into one .txt file for upload

$ErrorActionPreference = "Stop"

# Output file
$outputFile = ".\\scripts\\copilot_upload.txt"

if (Test-Path $outputFile) {
    Remove-Item $outputFile -Force
}

# Get all tracked and untracked-but-not-ignored files
$files = git ls-files --cached --others --exclude-standard

foreach ($file in $files) {
    if (-Not (Test-Path $file)) {
        Write-Warning "Skipping missing file: $file"
        continue
    }

    # Add header for each file
    Add-Content -Path $outputFile -Value "`n`n===== START OF FILE: $file =====`n"

    # Append file content
    Get-Content $file | Add-Content -Path $outputFile

    # Add footer
    Add-Content -Path $outputFile -Value "`n===== END OF FILE: $file =====`n"
}

Write-Host "✅ All repository files consolidated into $outputFile"