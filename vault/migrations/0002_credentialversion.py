import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vault', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CredentialVersion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version_number', models.PositiveIntegerField()),
                ('changed_fields', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('name', models.CharField(blank=True, max_length=200)),
                ('credential_type', models.CharField(blank=True, max_length=20)),
                ('visibility', models.CharField(blank=True, max_length=10)),
                ('url', models.CharField(blank=True, max_length=500)),
                ('username', models.CharField(blank=True, max_length=200)),
                ('notes', models.TextField(blank=True)),
                ('public_key', models.TextField(blank=True)),
                ('certificate_pem', models.TextField(blank=True)),
                ('expiry_date', models.DateField(blank=True, null=True)),
                ('encrypted_password', models.TextField(blank=True)),
                ('encrypted_private_key', models.TextField(blank=True)),
                ('encrypted_passphrase', models.TextField(blank=True)),
                ('credential', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='versions', to='vault.credential')),
                ('changed_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-version_number'],
                'unique_together': {('credential', 'version_number')},
            },
        ),
    ]
