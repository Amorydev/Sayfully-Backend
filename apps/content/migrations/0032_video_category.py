from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0031_topic_icon_url"),
    ]

    operations = [
        migrations.CreateModel(
            name="VideoCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=48, unique=True)),
                ("subtitle", models.CharField(blank=True, max_length=120)),
                ("order", models.PositiveSmallIntegerField(default=0)),
            ],
            options={"ordering": ["order", "name"], "verbose_name_plural": "video categories"},
        ),
    ]
