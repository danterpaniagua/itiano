from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='AppSetting',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=100, unique=True)),
                ('value', models.CharField(blank=True, max_length=500)),
            ],
            options={
                'verbose_name': 'App Setting',
                'verbose_name_plural': 'App Settings',
                'ordering': ['key'],
            },
        ),
    ]
