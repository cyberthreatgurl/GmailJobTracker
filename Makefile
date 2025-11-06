# Makefile for GmailJobTracker Docker operations

.PHONY: help build up down restart logs shell test clean migrate ingest

help: ## Show this help message
	@echo "GmailJobTracker Docker Management"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

build: ## Build Docker image
	docker-compose build

up: ## Start containers in detached mode
	docker-compose up -d

down: ## Stop and remove containers
	docker-compose down

restart: ## Restart containers
	docker-compose restart

logs: ## View container logs (follow mode)
	docker-compose logs -f web

logs-tail: ## View last 100 lines of logs
	docker-compose logs --tail=100 web

shell: ## Open bash shell in container
	docker-compose exec web bash

python-shell: ## Open Django shell
	docker-compose exec web python manage.py shell

db-shell: ## Open database shell
	docker-compose exec web python manage.py dbshell

test: ## Run tests
	docker-compose exec web pytest

test-coverage: ## Run tests with coverage
	docker-compose exec web pytest --cov=tracker --cov=. --cov-report=html

check: ## Run Django checks
	docker-compose exec web python manage.py check

migrate: ## Run database migrations
	docker-compose exec web python manage.py migrate

makemigrations: ## Create new migrations
	docker-compose exec web python manage.py makemigrations

createsuperuser: ## Create Django superuser
	docker-compose exec web python manage.py createsuperuser

ingest: ## Ingest Gmail messages (last 7 days)
	docker-compose exec web python manage.py ingest_gmail

ingest-30: ## Ingest last 30 days
	docker-compose exec web python manage.py ingest_gmail --days-back 30

ingest-force: ## Force re-ingest
	docker-compose exec web python manage.py ingest_gmail --force

train: ## Train ML model
	docker-compose exec web python train_model.py --verbose

mark-ghosted: ## Mark ghosted applications
	docker-compose exec web python manage.py mark_ghosted

reclassify: ## Reclassify all messages
	docker-compose exec web python manage.py reclassify_messages

backup: ## Backup database and config
	mkdir -p backups/$$(date +%Y%m%d)
	docker-compose exec web sqlite3 /app/db/job_tracker.db ".backup '/app/db/backup.db'"
	cp db/backup.db backups/$$(date +%Y%m%d)/job_tracker.db
	tar -czf backups/$$(date +%Y%m%d)/gmailtracker-backup.tar.gz db/ model/ json/
	@echo "Backup created in backups/$$(date +%Y%m%d)/"

restore: ## Restore from backup (specify DATE=YYYYMMDD)
	@if [ -z "$(DATE)" ]; then echo "Usage: make restore DATE=YYYYMMDD"; exit 1; fi
	docker-compose down
	cp backups/$(DATE)/job_tracker.db db/
	docker-compose up -d
	@echo "Restored from backups/$(DATE)/"

clean: ## Clean up containers, volumes, and caches
	docker-compose down -v
	rm -rf db/*.db logs/*.log model/*.pkl
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

rebuild: ## Rebuild and restart containers
	docker-compose down
	docker-compose build --no-cache
	docker-compose up -d

ps: ## Show container status
	docker-compose ps

stats: ## Show container resource usage
	docker stats gmailtracker

env-check: ## Run environment checks
	docker-compose exec web python check_env.py

health: ## Check application health
	@curl -f http://localhost:8000 && echo "\n✅ Application is healthy" || echo "\n❌ Application is not responding"

install: ## Initial setup - build, start, and initialize
	@echo "🚀 Installing GmailJobTracker..."
	docker-compose build
	docker-compose up -d
	@echo "⏳ Waiting for container to start..."
	sleep 5
	docker-compose exec web python manage.py migrate
	@echo "✅ Installation complete!"
	@echo ""
	@echo "Access the application at: http://localhost:8000"
	@echo "Admin panel: http://localhost:8000/admin"
	@echo ""
	@echo "Create a superuser with: make createsuperuser"

update: ## Update to latest version
	git pull origin main
	docker-compose down
	docker-compose build --no-cache
	docker-compose up -d
	docker-compose exec web python manage.py migrate
	@echo "✅ Update complete!"

dev: ## Start in development mode with live logs
	docker-compose up

prod: ## Start in production mode (set DEBUG=False in .env first)
	@if grep -q "DEBUG=True" .env; then echo "⚠️  WARNING: DEBUG=True in .env. Set DEBUG=False for production!"; exit 1; fi
	docker-compose up -d
	@echo "✅ Production deployment started"
