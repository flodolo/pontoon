# Generated by Django 3.2.15 on 2024-02-20 10:51

from django.conf import settings
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("base", "0052_rename_logged_in_users"),
    ]

    operations = [
        migrations.AlterIndexTogether(
            name="translation",
            index_together={
                ("locale", "user", "entity"),
                ("entity", "user", "approved", "pretranslated"),
                ("entity", "locale", "fuzzy"),
                ("date", "locale"),
                ("entity", "locale", "approved"),
                ("entity", "locale", "pretranslated"),
                ("approved_date", "locale"),
            },
        ),
    ]
