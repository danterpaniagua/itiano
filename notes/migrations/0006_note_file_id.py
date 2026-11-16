from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notes', '0005_system_prompts_viewers_group'),
    ]

    operations = [
        migrations.AddField(
            model_name='note',
            name='file_id',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddConstraint(
            model_name='note',
            constraint=models.UniqueConstraint(condition=models.Q(('file_id', ''), _negated=True), fields=('notebook', 'file_id'), name='notes_note_file_id_per_notebook_uniq'),
        ),
    ]
