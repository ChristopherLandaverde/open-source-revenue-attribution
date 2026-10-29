"""M1 import contract: opportunities belong to an account and may lack a contact; touchpoints
keep utm_content/utm_term/referrer; ImportRun records each import's validation report."""

import django.db.models.deletion
from django.db import migrations, models


def backfill_opportunity_account(apps, schema_editor):
    Opportunity = apps.get_model("reports", "Opportunity")
    for opportunity in Opportunity.objects.select_related("contact"):
        opportunity.account_id = opportunity.contact.account_id
        opportunity.save(update_fields=["account"])


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="opportunity",
            name="account",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="opportunities", to="reports.account"),
        ),
        migrations.RunPython(backfill_opportunity_account, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="opportunity",
            name="account",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="opportunities", to="reports.account"),
        ),
        migrations.AlterField(
            model_name="opportunity",
            name="contact",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="opportunities", to="reports.contact"),
        ),
        migrations.AlterField(
            model_name="opportunity",
            name="name",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AlterField(
            model_name="account",
            name="name",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="touchpoint",
            name="content",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="touchpoint",
            name="term",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="touchpoint",
            name="referrer",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.CreateModel(
            name="ImportRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source", models.CharField(max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("lookback_days", models.PositiveIntegerField()),
                ("strict", models.BooleanField(default=False)),
                ("loaded", models.BooleanField(help_text="False when a strict import refused everything.")),
                ("report", models.JSONField()),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
    ]
