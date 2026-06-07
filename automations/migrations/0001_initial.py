import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Action',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('action_type', models.CharField(choices=[('create_ticket', 'Create Ticket')], max_length=50)),
                ('field_mappings', models.JSONField(help_text='Map ticket fields to JSONPath expressions or literal values. Example: {"title": "$.issue.key", "description": "$.issue.fields.description", "type": "incident", "priority": "medium", "category": "Automation"}')),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('system_user', models.ForeignKey(help_text='User set as requester for tickets created by this action.', on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Trigger',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('source', models.CharField(choices=[('jira', 'Jira')], max_length=50)),
                ('event_type', models.CharField(blank=True, help_text='Optional. Match only this Jira event type (e.g. jira:issue_created). Leave blank to match all.', max_length=100)),
                ('filter', models.JSONField(help_text='Structured filter condition tree. Example: {"and": [{"path": "$.issue.fields.project.name", "op": "eq", "value": "GIT"}, {"path": "$.issue.labels", "op": "in", "value": ["Azure", "PROD"]}]}')),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('action', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='triggers', to='automations.action')),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='TriggerLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('payload_snapshot', models.JSONField()),
                ('result', models.CharField(choices=[('matched', 'Matched'), ('skipped', 'Skipped'), ('error', 'Error')], max_length=10)),
                ('detail', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('action', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='logs', to='automations.action')),
                ('trigger', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='logs', to='automations.trigger')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
