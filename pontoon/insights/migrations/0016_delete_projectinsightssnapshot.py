# Generated by Django 4.2.17 on 2025-01-17 14:50

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("insights", "0015_fix_projectlocale_insights_data"),
    ]

    operations = [
        migrations.DeleteModel(
            name="ProjectInsightsSnapshot",
        ),
    ]