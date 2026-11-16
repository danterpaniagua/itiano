from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('timetracking', '0007_workschedule_time_defaults'),
    ]

    operations = [
        migrations.CreateModel(
            name='GeneratedTimeReport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file_id', models.CharField(max_length=64)),
                ('kind', models.CharField(max_length=10)),
                ('period_start', models.DateField()),
                ('period_end', models.DateField()),
                ('empty', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='generated_time_reports', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-period_end'],
                'unique_together': {('user', 'file_id')},
            },
        ),
    ]
