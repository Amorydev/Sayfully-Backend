from django.db import migrations, models


def mark_existing_profiles_complete(apps, schema_editor):
    user_profile = apps.get_model("accounts", "UserProfile")
    user_profile.objects.update(onboarding_completed=True)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_userprofile_learning_goal"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="onboarding_completed",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="onboarding_completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(mark_existing_profiles_complete, migrations.RunPython.noop),
    ]
