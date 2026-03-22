# Docker Notes

This quick note supplements the full deployment guide in `markdown/DOCKER_DEPLOYMENT.md`.

Startup behavior:

- The container waits for PostgreSQL before running migrations.
- If PostgreSQL stays unreachable for 30 attempts, the entrypoint exits non-zero with an explicit host/port error.
- Django WSGI and ASGI startup also fail fast if the configured default database cannot be reached.
- Docker Compose uses the same PostgreSQL-backed application configuration as local development and CI.

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
