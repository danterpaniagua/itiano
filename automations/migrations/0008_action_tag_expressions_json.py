from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('automations', '0007_alter_action_description_format_and_more'),
    ]

    operations = [
        # Step 1: convert existing text rows to valid JSON text before type change
        migrations.RunSQL(
            sql="""
                UPDATE automations_action
                SET tag_expressions = COALESCE(
                    (SELECT json_agg(json_build_object('expression', trim(line), 'color', ''))::text
                     FROM unnest(string_to_array(NULLIF(trim(tag_expressions), ''), E'\\n')) AS line
                     WHERE trim(line) != ''),
                    '[]'
                );
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Step 2: cast TEXT → JSONB (data is now valid JSON)
        migrations.RunSQL(
            sql="ALTER TABLE automations_action ALTER COLUMN tag_expressions TYPE jsonb USING tag_expressions::jsonb;",
            reverse_sql="ALTER TABLE automations_action ALTER COLUMN tag_expressions TYPE text USING tag_expressions::text;",
        ),
        # Step 3: add default and not-null constraint via Django state
        migrations.AlterField(
            model_name='action',
            name='tag_expressions',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='List of {expression, color} objects. Each resolved value becomes a colored tag on the ticket.',
            ),
        ),
    ]
