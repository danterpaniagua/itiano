from django.db import migrations

GROUP = 'System Prompts viewers'


def create_group(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    content_type, _ = ContentType.objects.get_or_create(app_label='notes', model='note')
    permission, _ = Permission.objects.get_or_create(
        content_type=content_type, codename='view_system_prompts',
        defaults={'name': 'Can view system prompts'},
    )
    group, _ = Group.objects.get_or_create(name=GROUP)
    group.permissions.add(permission)


def remove_group(apps, schema_editor):
    apps.get_model('auth', 'Group').objects.filter(name=GROUP).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('notes', '0001_initial'),
        ('auth', '0001_initial'),
        ('contenttypes', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_group, remove_group),
    ]
