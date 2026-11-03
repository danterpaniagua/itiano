from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('notes', '0002_note_is_system'),
    ]

    operations = [
        migrations.CreateModel(
            name='NoteMention',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('jira', 'Jira ticket'), ('ticket', 'ITSM ticket'), ('cred', 'Credential')], max_length=10)),
                ('ref', models.CharField(max_length=50)),
                ('note', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mentions', to='notes.note')),
            ],
            options={
                'indexes': [models.Index(fields=['kind', 'ref'], name='notes_mention_kind_ref_idx')],
                'unique_together': {('note', 'kind', 'ref')},
            },
        ),
    ]
