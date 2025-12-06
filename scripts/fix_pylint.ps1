#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Quick-start script to fix pylint errors in phases

.DESCRIPTION
    This script automates the pylint error fixing process by running
    automated tools in the correct order.

.PARAMETER Phase
    Which phase to run: phase1, phase2, or all

.PARAMETER DryRun
    Show what would be done without making changes

.EXAMPLE
    .\fix_pylint.ps1 -Phase phase1
    Run automated fixes (formatting, imports, docstrings)

.EXAMPLE
    .\fix_pylint.ps1 -Phase all -DryRun
    Show all fixes that would be applied
#>

param(
    [Parameter()]
    [ValidateSet('phase1', 'phase2', 'all', 'summary')]
    [string]$Phase = 'summary',
    
    [Parameter()]
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host "🔧 GmailJobTracker Pylint Error Fixer" -ForegroundColor Cyan
Write-Host "=" * 70 -ForegroundColor Cyan

function Test-PythonPackage {
    param([string]$Package)
    
    $result = python -c "import importlib; importlib.import_module('$Package')" 2>&1
    return $LASTEXITCODE -eq 0
}

function Install-RequiredTools {
    Write-Host "`n📦 Checking required tools..." -ForegroundColor Yellow
    
    $tools = @('isort', 'autoflake', 'black', 'pylint')
    $missing = @()
    
    foreach ($tool in $tools) {
        if (Test-PythonPackage $tool) {
            Write-Host "  ✓ $tool installed" -ForegroundColor Green
        } else {
            Write-Host "  ✗ $tool missing" -ForegroundColor Red
            $missing += $tool
        }
    }
    
    if ($missing.Count -gt 0) {
        Write-Host "`n⚠️  Missing packages: $($missing -join ', ')" -ForegroundColor Yellow
        $install = Read-Host "Install missing packages? (y/n)"
        
        if ($install -eq 'y') {
            Write-Host "Installing..." -ForegroundColor Yellow
            pip install $missing
        } else {
            Write-Host "❌ Cannot proceed without required tools" -ForegroundColor Red
            exit 1
        }
    }
}

function Show-ErrorSummary {
    Write-Host "`n📊 Current Pylint Error Summary" -ForegroundColor Cyan
    python scripts/fix_pylint_errors.py --category summary
}

function Run-Phase1 {
    param([bool]$DryRun)
    
    Write-Host "`n🚀 PHASE 1: Automated Fixes" -ForegroundColor Cyan
    Write-Host "=" * 70 -ForegroundColor Cyan
    
    # Step 1: Format with Black
    Write-Host "`n1️⃣ Running Black formatter..." -ForegroundColor Yellow
    if ($DryRun) {
        black . --line-length 120 --skip-string-normalization --check --diff
    } else {
        black . --line-length 120 --skip-string-normalization
        Write-Host "  ✓ Code formatted" -ForegroundColor Green
    }
    
    # Step 2: Fix import order with isort
    Write-Host "`n2️⃣ Fixing import order with isort..." -ForegroundColor Yellow
    if ($DryRun) {
        isort . --profile black --line-length 100 --check-only --diff
    } else {
        isort . --profile black --line-length 100
        Write-Host "  ✓ Imports sorted" -ForegroundColor Green
    }
    
    # Step 3: Remove unused imports
    Write-Host "`n3️⃣ Removing unused imports with autoflake..." -ForegroundColor Yellow
    if ($DryRun) {
        autoflake --remove-all-unused-imports --recursive .
    } else {
        autoflake --remove-all-unused-imports --in-place --recursive .
        Write-Host "  ✓ Unused imports removed" -ForegroundColor Green
    }
    
    # Step 4: Fix formatting issues
    Write-Host "`n4️⃣ Fixing trailing whitespace and newlines..." -ForegroundColor Yellow
    if ($DryRun) {
        python scripts/fix_pylint_errors.py --category formatting --dry-run
    } else {
        python scripts/fix_pylint_errors.py --category formatting
    }
    
    # Step 5: Add module docstrings
    Write-Host "`n5️⃣ Adding module docstrings..." -ForegroundColor Yellow
    if ($DryRun) {
        python scripts/fix_pylint_errors.py --category docstrings --dry-run
    } else {
        python scripts/fix_pylint_errors.py --category docstrings
    }
    
    Write-Host "`n✅ Phase 1 Complete!" -ForegroundColor Green
    
    if (-not $DryRun) {
        Write-Host "`n📊 Generating new pylint report..." -ForegroundColor Yellow
        pylint . --output-format=json > scripts/debug/pylint_after_phase1.json
        
        Write-Host "`n📈 Improvement Summary:" -ForegroundColor Cyan
        python scripts/fix_pylint_errors.py --report scripts/debug/pylint_after_phase1.json --category summary
    }
}

function Run-Phase2 {
    Write-Host "`n🚀 PHASE 2: Critical Manual Fixes" -ForegroundColor Cyan
    Write-Host "=" * 70 -ForegroundColor Cyan
    
    Write-Host "`nPhase 2 requires manual intervention. See PYLINT_FIXING_STRATEGY.md" -ForegroundColor Yellow
    Write-Host "`nKey tasks:" -ForegroundColor Yellow
    Write-Host "  1. Fix import errors (15 errors)" -ForegroundColor White
    Write-Host "     - Rename parser.py to email_parser.py if needed" -ForegroundColor Gray
    Write-Host "     - Fix circular imports" -ForegroundColor Gray
    Write-Host "  2. Replace broad exceptions (30 errors)" -ForegroundColor White
    Write-Host "     - Use specific exception types" -ForegroundColor Gray
    Write-Host "  3. Fix redefined outer names (9 errors)" -ForegroundColor White
    Write-Host "  4. Add function docstrings (27 errors)" -ForegroundColor White
    
    Write-Host "`nSee markdown/PYLINT_FIXING_STRATEGY.md for detailed instructions" -ForegroundColor Cyan
}

function Main {
    # Check if we're in the right directory
    if (-not (Test-Path "manage.py")) {
        Write-Host "❌ Must be run from GmailJobTracker root directory" -ForegroundColor Red
        exit 1
    }
    
    switch ($Phase) {
        'summary' {
            Show-ErrorSummary
        }
        'phase1' {
            Install-RequiredTools
            Run-Phase1 -DryRun $DryRun
        }
        'phase2' {
            Run-Phase2
        }
        'all' {
            Install-RequiredTools
            Run-Phase1 -DryRun $DryRun
            if (-not $DryRun) {
                Run-Phase2
            }
        }
    }
    
    if ($DryRun) {
        Write-Host "`n💡 This was a dry run. Run without -DryRun to apply changes." -ForegroundColor Cyan
    } else {
        Write-Host "`n💡 Next steps:" -ForegroundColor Cyan
        Write-Host "  1. Review the changes: git diff" -ForegroundColor White
        Write-Host "  2. Test the application: pytest" -ForegroundColor White
        Write-Host "  3. Run Django tests: python manage.py test" -ForegroundColor White
        Write-Host "  4. Commit changes: git add . && git commit -m 'fix: automated pylint fixes'" -ForegroundColor White
    }
}

Main
