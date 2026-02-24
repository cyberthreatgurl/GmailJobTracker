from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0032_companyoperatingcity_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="companynews",
            name="hidden_urls",
            field=models.JSONField(
                default=list,
                help_text="URLs the user has explicitly hidden from Recent News",
            ),
        ),
        migrations.AddField(
            model_name="companynews",
            name="user_articles",
            field=models.JSONField(
                default=list,
                help_text="Articles manually added by the user (not from RSS/API)",
            ),
        ),
    ]
