from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Contact',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('first_name', models.CharField(max_length=150)),
                ('last_name', models.CharField(max_length=150)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='contact', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['last_name', 'first_name'],
            },
        ),
        migrations.CreateModel(
            name='ContactChannel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('type', models.CharField(choices=[('email', 'Email'), ('post', 'POST'), ('phone', 'Phone')], max_length=10)),
                ('label', models.CharField(blank=True, max_length=100)),
                ('value', models.CharField(blank=True, help_text='Email address or phone number', max_length=500)),
                ('url', models.URLField(blank=True, help_text='POST endpoint URL')),
                ('headers', models.JSONField(blank=True, default=dict, help_text='HTTP headers as key-value pairs')),
                ('body', models.TextField(blank=True, help_text='Request body template. Use {{ ticket.id }}, {{ ticket.title }}, {{ ticket.state }}, {{ contact.first_name }}, {{ contact.last_name }}')),
                ('is_primary', models.BooleanField(default=False)),
                ('contact', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='channels', to='contacts.contact')),
            ],
            options={
                'ordering': ['-is_primary', 'type', 'label'],
            },
        ),
    ]
