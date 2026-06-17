from django.db import migrations, models


def backfill_is_bot(apps, schema_editor):
    """Existing robot-tagged sessions predate the is_bot flag; mark them."""
    Session = apps.get_model("analytics", "Session")
    Session.objects.filter(device_type="ROBOT").update(
        is_bot=True, bot_reason="ua-library"
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0010_auto_20220624_0744"),
    ]

    operations = [
        migrations.AddField(
            model_name="session",
            name="is_bot",
            field=models.BooleanField(
                db_index=True, default=False, verbose_name="Is bot"
            ),
        ),
        migrations.AddField(
            model_name="session",
            name="bot_reason",
            field=models.CharField(
                blank=True, default="", max_length=32, verbose_name="Bot reason"
            ),
        ),
        migrations.RunPython(backfill_is_bot, noop_reverse),
    ]
