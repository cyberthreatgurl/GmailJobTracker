# Docker Notes

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
