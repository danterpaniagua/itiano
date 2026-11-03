from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('notes', '0003_notemention'),
    ]

    operations = [
        migrations.AddField(
            model_name='notebook',
            name='parent',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='children', to='notes.notebook'),
        ),
        migrations.AddField(
            model_name='notebook',
            name='key',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='notebook',
            name='is_system',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterUniqueTogether(
            name='notebook',
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name='notebook',
            constraint=models.UniqueConstraint(condition=models.Q(('is_system', False)), fields=('owner', 'name'), name='notes_notebook_owner_name_personal_uniq'),
        ),
        migrations.AddConstraint(
            model_name='notebook',
            constraint=models.UniqueConstraint(condition=models.Q(('key', ''), _negated=True), fields=('key',), name='notes_notebook_key_uniq'),
        ),
        migrations.AddField(
            model_name='note',
            name='key',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AlterModelOptions(
            name='note',
            options={'ordering': ['-updated_at'], 'permissions': [('view_system_prompts', 'Can view system prompts')]},
        ),
        migrations.AddConstraint(
            model_name='note',
            constraint=models.UniqueConstraint(condition=models.Q(('key', ''), _negated=True), fields=('key',), name='notes_note_key_uniq'),
        ),
    ]
