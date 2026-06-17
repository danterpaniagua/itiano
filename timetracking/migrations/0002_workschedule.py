from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('timetracking', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='WorkSchedule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mon', models.BooleanField(default=True)),
                ('tue', models.BooleanField(default=True)),
                ('wed', models.BooleanField(default=True)),
                ('thu', models.BooleanField(default=True)),
                ('fri', models.BooleanField(default=True)),
                ('sat', models.BooleanField(default=False)),
                ('sun', models.BooleanField(default=False)),
                ('start_time', models.TimeField(default='08:00')),
                ('end_time', models.TimeField(default='18:00')),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='work_schedule',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
    ]
