import datetime

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('timetracking', '0006_alter_workschedule_start_time_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='workschedule',
            name='start_time',
            field=models.TimeField(default=datetime.time(9, 0)),
        ),
        migrations.AlterField(
            model_name='workschedule',
            name='end_time',
            field=models.TimeField(default=datetime.time(18, 0)),
        ),
    ]
