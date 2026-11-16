from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notes', '0006_note_file_id'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='notebook',
            name='notes_notebook_owner_name_personal_uniq',
        ),
        migrations.AddConstraint(
            model_name='notebook',
            constraint=models.UniqueConstraint(condition=models.Q(('is_system', False), ('parent__isnull', True)), fields=('owner', 'name'), name='notes_notebook_owner_name_personal_uniq'),
        ),
        migrations.AddConstraint(
            model_name='notebook',
            constraint=models.UniqueConstraint(condition=models.Q(('is_system', False), ('parent__isnull', False)), fields=('owner', 'parent', 'name'), name='notes_notebook_owner_parent_name_uniq'),
        ),
    ]
