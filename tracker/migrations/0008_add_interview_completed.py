"""Update Application model name in migration state and add interview_completed field.

This migration updates the migration state to use 'ThreadTracking' as the model name
(matching current code) while preserving the existing 'tracker_application' table.
We use SeparateDatabaseAndState to update Django's internal state without touching the DB.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0007_appsetting"),
    ]

    operations = [
        # Update Django's migration state to rename Application -> ThreadTracking
        # AND add interview_completed field, all while operating on tracker_application table
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameModel(
                    old_name="Application",
                    new_name="ThreadTracking",
                ),
                migrations.AddField(
                    model_name="threadtracking",
                    name="interview_completed",
                    field=models.BooleanField(default=False),
                ),
            ],
            database_operations=[
                # Add field to the actual table (which is still called tracker_application)
                migrations.RunSQL(
                    sql="ALTER TABLE tracker_application ADD COLUMN interview_completed BOOL NOT NULL DEFAULT 0",
                    reverse_sql="ALTER TABLE tracker_application DROP COLUMN interview_completed",
                ),
            ],
        ),
    ]
