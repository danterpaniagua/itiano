# Team moved to core.Team (v5.10.4). Repoints the three FKs that used to
# target the local vault.Team, then removes vault's own state-only record
# of the model (core's 0004_team migration already owns the physical
# table — this DeleteModel is state-only too, no DROP TABLE). See
# .claude/v5.10.4.md.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_team'),
        ('vault', '0007_remove_credential_notes_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='containeraccess',
            name='team',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='container_access_grants', to='core.team'),
        ),
        migrations.AlterField(
            model_name='teamkeywrap',
            name='team',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='key_wraps', to='core.team'),
        ),
        migrations.AlterField(
            model_name='credential',
            name='team',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='credentials', to='core.team'),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.DeleteModel(name='Team'),
            ],
        ),
    ]
