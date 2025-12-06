rm job_tracker.db
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
