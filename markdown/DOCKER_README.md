# Docker Notes

This quick note supplements the full deployment guide in `markdown/DOCKER_DEPLOYMENT.md`.

Startup behavior:

- The container waits for PostgreSQL before running migrations.
- If PostgreSQL stays unreachable for 30 attempts, the entrypoint exits non-zero with an explicit host/port error.
- Django WSGI and ASGI startup also fail fast if the configured default database cannot be reached.
- Docker Compose sets `DB_ENGINE=postgresql` explicitly so containerized runs continue to use PostgreSQL even though local development now defaults to SQLite.

## Commands to Run the Application within Container

### Docker Compose Commands


```bash
cp credentials.json json/
docker compose exec web python manage.py check
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py ingest_gmail
```

### Docker Exec Commands

```bash
docker exec -it gmailtracker python manage.py check
```
