from django.db import migrations


class Migration(migrations.Migration):
    """
    0009_trigger_tags was applied to the DB as an M2M (through table), but the
    migration file was later rewritten to a FK. Django considers 0009 done but
    the tag_id column is missing and the through table still exists.
    This migration reconciles the DB to match the current model state.
    """

    dependencies = [
        ('automations', '0009_trigger_tags'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                'DROP TABLE IF EXISTS automations_trigger_tags;',
                'ALTER TABLE automations_trigger ADD COLUMN IF NOT EXISTS tag_id INTEGER REFERENCES itsm_tag(id) ON DELETE SET NULL;',
            ],
            reverse_sql=[
                'ALTER TABLE automations_trigger DROP COLUMN IF EXISTS tag_id;',
            ],
            state_operations=[],
        ),
    ]
