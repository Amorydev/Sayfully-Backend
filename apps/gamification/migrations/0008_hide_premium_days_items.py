from django.db import migrations


def hide_premium_days_items(apps, schema_editor):
    ShopItem = apps.get_model("gamification", "ShopItem")
    ShopItem.objects.filter(effect__has_key="premium_days").update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [("gamification", "0007_alter_game_kind")]
    operations = [migrations.RunPython(hide_premium_days_items, migrations.RunPython.noop)]
