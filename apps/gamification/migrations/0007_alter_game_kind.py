from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gamification", "0006_gamescore_integrity"),
    ]

    operations = [
        migrations.AlterField(
            model_name="game",
            name="kind",
            field=models.CharField(
                choices=[
                    ("reflex", "Phản xạ"),
                    ("memory", "Ghi nhớ"),
                    ("listening", "Nghe hiểu"),
                    ("speaking", "Luyện nói"),
                ],
                max_length=10,
            ),
        ),
    ]
