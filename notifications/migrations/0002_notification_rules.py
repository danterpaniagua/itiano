import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_team'),
        ('notifications', '0001_initial'),
        ('vault', '0008_move_team_to_core'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='NotificationRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('is_active', models.BooleanField(default=True)),
                ('filter', models.JSONField(help_text='Condition tree evaluated against a payload rebuilt from the current JiraTicket.')),
                ('grace_minutes', models.PositiveIntegerField(default=15)),
                ('message', models.CharField(max_length=500)),
                ('notify_assignee', models.BooleanField(default=False)),
                ('starts_at', models.DateTimeField(auto_now_add=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('teams', models.ManyToManyField(blank=True, related_name='notification_rules', to='core.team')),
                ('users', models.ManyToManyField(blank=True, related_name='notification_rules', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='NotificationRuleHit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('issue_key', models.CharField(max_length=50)),
                ('notified_at', models.DateTimeField(auto_now_add=True)),
                ('rule', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='hits', to='notifications.notificationrule')),
            ],
            options={
                'unique_together': {('rule', 'issue_key')},
            },
        ),
    ]
