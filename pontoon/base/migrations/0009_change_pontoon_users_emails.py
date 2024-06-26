# Generated by Django 2.2.13 on 2020-08-28 08:49
from django.db import migrations


def update_system_user_email(apps, schema_editor):
    User = apps.get_model("auth", "User")
    User.objects.filter(email="pontoon-sync@mozilla.com").update(
        email="pontoon-sync@example.com"
    )
    User.objects.filter(email="pontoon-gt@mozilla.com").update(
        email="pontoon-gt@example.com"
    )
    User.objects.filter(email="pontoon-tm@mozilla.com").update(
        email="pontoon-tm@example.com"
    )


def revert_system_user_email(apps, schema_editor):
    User = apps.get_model("auth", "User")
    User.objects.filter(email="pontoon-sync@example.com").update(
        email="pontoon-sync@mozilla.com"
    )
    User.objects.filter(email="pontoon-gt@example.com").update(
        email="pontoon-gt@mozilla.com"
    )
    User.objects.filter(email="pontoon-tm@example.com").update(
        email="pontoon-tm@mozilla.com"
    )


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("base", "0008_add_systran_locales"),
    ]

    operations = [
        migrations.RunPython(
            code=update_system_user_email,
            reverse_code=revert_system_user_email,
        ),
    ]
