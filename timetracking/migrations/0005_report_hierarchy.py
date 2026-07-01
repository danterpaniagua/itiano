import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('timetracking', '0004_workschedule_timezone'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReportProject',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tag_name', models.CharField(max_length=100, unique=True)),
            ],
            options={'ordering': ['tag_name']},
        ),
        migrations.CreateModel(
            name='ReportService',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tag_name', models.CharField(max_length=100)),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='services', to='timetracking.reportproject')),
            ],
            options={'ordering': ['tag_name']},
        ),
        migrations.CreateModel(
            name='ReportEnvironment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tag_name', models.CharField(max_length=100)),
                ('service', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='environments', to='timetracking.reportservice')),
            ],
            options={'ordering': ['tag_name']},
        ),
        migrations.AlterUniqueTogether(
            name='reportservice',
            unique_together={('project', 'tag_name')},
        ),
        migrations.AlterUniqueTogether(
            name='reportenvironment',
            unique_together={('service', 'tag_name')},
        ),
    ]
