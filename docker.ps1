#!/usr/bin/env pwsh
# PowerShell version of common Docker operations for Windows users

param(
    [Parameter(Position=0)]
    [string]$Command = "help"
)

function Show-Help {
    Write-Host "GmailJobTracker Docker Management (PowerShell)" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Usage: .\docker.ps1 <command>" -ForegroundColor White
    Write-Host ""
    Write-Host "Commands:" -ForegroundColor Yellow
    Write-Host "  build          - Build Docker image"
    Write-Host "  up             - Start containers"
    Write-Host "  down           - Stop containers"
    Write-Host "  restart        - Restart containers"
    Write-Host "  logs           - View logs (follow mode)"
    Write-Host "  shell          - Open bash shell in container"
    Write-Host "  test           - Run tests"
    Write-Host "  migrate        - Run migrations"
    Write-Host "  ingest         - Ingest Gmail (last 7 days)"
    Write-Host "  train          - Train ML model"
    Write-Host "  backup         - Backup database"
    Write-Host "  clean          - Clean up containers"
    Write-Host "  install        - Initial setup"
    Write-Host "  update         - Update to latest version"
}

function Invoke-Build {
    Write-Host "🔨 Building Docker image..." -ForegroundColor Cyan
    docker-compose build
}

function Invoke-Up {
    Write-Host "🚀 Starting containers..." -ForegroundColor Green
    docker-compose up -d
}

function Invoke-Down {
    Write-Host "🛑 Stopping containers..." -ForegroundColor Yellow
    docker-compose down
}

function Invoke-Restart {
    Write-Host "🔄 Restarting containers..." -ForegroundColor Cyan
    docker-compose restart
}

function Invoke-Logs {
    Write-Host "📋 Viewing logs (Ctrl+C to exit)..." -ForegroundColor Cyan
    docker-compose logs -f web
}

function Invoke-Shell {
    Write-Host "🐚 Opening shell in container..." -ForegroundColor Cyan
    docker-compose exec web bash
}

function Invoke-Test {
    Write-Host "🧪 Running tests..." -ForegroundColor Cyan
    docker-compose exec web pytest
}

function Invoke-Migrate {
    Write-Host "📊 Running migrations..." -ForegroundColor Cyan
    docker-compose exec web python manage.py migrate
}

function Invoke-Ingest {
    Write-Host "📥 Ingesting Gmail messages..." -ForegroundColor Cyan
    docker-compose exec web python manage.py ingest_gmail
}

function Invoke-Train {
    Write-Host "🤖 Training ML model..." -ForegroundColor Cyan
    docker-compose exec web python train_model.py --verbose
}

function Invoke-Backup {
    $date = Get-Date -Format "yyyyMMdd"
    $backupDir = "backups\$date"
    
    Write-Host "💾 Creating backup..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    
    docker-compose exec web sqlite3 /app/db/job_tracker.db ".backup '/app/db/backup.db'"
    Copy-Item "db\backup.db" "$backupDir\job_tracker.db"
    
    # Create tarball (requires tar on Windows 10+)
    tar -czf "$backupDir\gmailtracker-backup.tar.gz" db\ model\ json\
    
    Write-Host "✅ Backup created in $backupDir" -ForegroundColor Green
}

function Invoke-Clean {
    Write-Host "🧹 Cleaning up..." -ForegroundColor Yellow
    docker-compose down -v
    
    if (Test-Path "db\*.db") { Remove-Item "db\*.db" }
    if (Test-Path "logs\*.log") { Remove-Item "logs\*.log" }
    if (Test-Path "model\*.pkl") { Remove-Item "model\*.pkl" }
    
    Write-Host "✅ Cleanup complete" -ForegroundColor Green
}

function Invoke-Install {
    Write-Host "🚀 Installing GmailJobTracker..." -ForegroundColor Cyan
    
    # Check if .env exists
    if (-not (Test-Path ".env")) {
        Write-Host "⚠️  .env file not found. Copying from .env.example..." -ForegroundColor Yellow
        Copy-Item ".env.example" ".env"
        Write-Host "📝 Please edit .env file with your settings" -ForegroundColor Yellow
        Write-Host "Press any key to continue after editing .env..."
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    }
    
    docker-compose build
    docker-compose up -d
    
    Write-Host "⏳ Waiting for container to start..." -ForegroundColor Cyan
    Start-Sleep -Seconds 5
    
    docker-compose exec web python manage.py migrate
    
    Write-Host ""
    Write-Host "✅ Installation complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Access the application at: http://localhost:8000" -ForegroundColor White
    Write-Host "Admin panel: http://localhost:8000/admin" -ForegroundColor White
    Write-Host ""
    Write-Host "Create superuser: docker-compose exec web python manage.py createsuperuser" -ForegroundColor Yellow
}

function Invoke-Update {
    Write-Host "⬆️  Updating to latest version..." -ForegroundColor Cyan
    
    git pull origin main
    docker-compose down
    docker-compose build --no-cache
    docker-compose up -d
    docker-compose exec web python manage.py migrate
    
    Write-Host "✅ Update complete!" -ForegroundColor Green
}

# Main command router
switch ($Command.ToLower()) {
    "help" { Show-Help }
    "build" { Invoke-Build }
    "up" { Invoke-Up }
    "down" { Invoke-Down }
    "restart" { Invoke-Restart }
    "logs" { Invoke-Logs }
    "shell" { Invoke-Shell }
    "test" { Invoke-Test }
    "migrate" { Invoke-Migrate }
    "ingest" { Invoke-Ingest }
    "train" { Invoke-Train }
    "backup" { Invoke-Backup }
    "clean" { Invoke-Clean }
    "install" { Invoke-Install }
    "update" { Invoke-Update }
    default {
        Write-Host "Unknown command: $Command" -ForegroundColor Red
        Write-Host ""
        Show-Help
    }
}
