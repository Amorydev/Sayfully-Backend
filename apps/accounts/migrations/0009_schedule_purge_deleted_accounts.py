from django.db import migrations

TASK = "apps.accounts.tasks.purge_deleted_accounts"


def create_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.update_or_create(
        name="purge-deleted-accounts",
        defaults={"func": TASK, "schedule_type": "D", "repeats": -1},
    )


def delete_schedule(apps, schema_editor):
    apps.get_model("django_q", "Schedule").objects.filter(name="purge-deleted-accounts").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0008_premium_tier"),
        ("django_q", "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more"),
    ]

    operations = [migrations.RunPython(create_schedule, delete_schedule)]
