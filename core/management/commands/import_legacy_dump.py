"""One-off import of a PostgreSQL-era `dumpdata` file into MongoDB (v6.0.0).

Export (run on the old PostgreSQL stack):
    python manage.py dumpdata --natural-foreign --natural-primary \
        -e contenttypes -e sessions -e admin.logentry > itiano_data.json

Import (on the MongoDB stack, after `migrate`, into an empty database):
    python manage.py import_legacy_dump itiano_data.json [--dry-run]

Integer primary keys are replaced by new ObjectIds; foreign keys and many-to-many
rows are remapped. Timestamps (auto_now / auto_now_add) are preserved. Sessions are
not imported (users log in again). Passwords and encrypted fields are copied as-is.
"""
import json
from collections import defaultdict

from bson import ObjectId
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

SKIP_MODELS = {'auth.permission'}  # recreated by migrate; referenced by natural key
# Rows seeded by data migrations; the dump carries its own copy, so the seeded ones are replaced.
SEEDED_MODELS = {'auth.group', 'settings_hub.jirastatusconfig'}
BATCH = 500


class Command(BaseCommand):
    help = 'Import a PostgreSQL dumpdata JSON file into MongoDB, remapping integer ids to ObjectIds.'

    def add_arguments(self, parser):
        parser.add_argument('dump_file')
        parser.add_argument('--dry-run', action='store_true', help='Validate and report counts without writing.')

    def handle(self, *args, **opts):
        with open(opts['dump_file'], encoding='utf-8') as fh:
            objects = json.load(fh)

        by_model = defaultdict(list)
        for obj in objects:
            by_model[obj['model']].append(obj)

        models = {}
        for label in by_model:
            if label in SKIP_MODELS:
                continue
            try:
                models[label] = apps.get_model(label)
            except LookupError:
                raise CommandError(f'Unknown model in dump: {label}')

        for label, model in models.items():
            if label not in SEEDED_MODELS and model._base_manager.exists():
                raise CommandError(f'{label} is not empty; import only into a fresh database.')

        # Pass 1: allocate ObjectIds for every object that has an integer pk.
        id_map = {}
        for label in models:
            for obj in by_model[label]:
                if 'pk' in obj and obj['pk'] is not None:
                    id_map[(label, obj['pk'])] = ObjectId()

        perm_cache = {}
        # These use natural primary keys in the dump (no integer pk): referenced by group name / username.
        natural_field = {'auth.group': 'name', 'auth.user': 'username'}
        natural_ids = {}
        for label, field_name in natural_field.items():
            for obj in by_model.get(label, []):
                if obj.get('pk') is None:
                    natural_ids[(label, obj['fields'][field_name])] = ObjectId()

        def permission(natural):
            codename, app_label, model = natural
            key = (codename, app_label, model)
            if key not in perm_cache:
                from django.contrib.auth.models import Permission
                perm_cache[key] = Permission.objects.get(
                    codename=codename, content_type__app_label=app_label, content_type__model=model,
                )
            return perm_cache[key]

        def remap(model_label, value):
            if value is None:
                return None
            if isinstance(value, list):  # natural key
                if model_label == 'auth.permission':
                    return permission(value).pk
                if (model_label, value[0]) in natural_ids:
                    return natural_ids[(model_label, value[0])]
                raise CommandError(f'Unsupported natural key for {model_label}: {value}')
            try:
                return id_map[(model_label, value)]
            except KeyError:
                raise CommandError(f'Dangling reference {model_label} pk={value}')

        if not opts['dry_run']:
            for label in SEEDED_MODELS & set(models):
                deleted, _ = models[label]._base_manager.all().delete()
                self.stdout.write(f'{label}: replaced {deleted} seeded row(s)')

        counts = {}
        m2m_rows = []
        disabled = []
        for label, model in models.items():
            for f in model._meta.concrete_fields:
                if getattr(f, 'auto_now', False) or getattr(f, 'auto_now_add', False):
                    disabled.append((f, f.auto_now, f.auto_now_add))
                    f.auto_now = f.auto_now_add = False

        try:
            for label, model in models.items():
                rows = []
                fields = {f.name: f for f in model._meta.concrete_fields}
                for obj in by_model[label]:
                    kwargs = {}
                    for name, value in obj['fields'].items():
                        f = fields.get(name)
                        if f is None:
                            continue  # M2M handled below, or a removed field
                        if f.is_relation:
                            kwargs[f.attname] = remap(f.related_model._meta.label_lower, value)
                        else:
                            kwargs[f.attname] = f.to_python(value)
                    if 'pk' in obj and obj['pk'] is not None:
                        kwargs[model._meta.pk.attname] = id_map[(label, obj['pk'])]
                    elif label in natural_field:
                        kwargs[model._meta.pk.attname] = natural_ids[(label, obj['fields'][natural_field[label]])]
                    rows.append(model(**kwargs))
                    for m2m in model._meta.many_to_many:
                        if m2m.name in obj['fields']:
                            rel_label = m2m.related_model._meta.label_lower
                            for target in obj['fields'][m2m.name]:
                                m2m_rows.append((m2m, kwargs[model._meta.pk.attname], remap(rel_label, target)))
                counts[label] = len(rows)
                if not opts['dry_run']:
                    for i in range(0, len(rows), BATCH):
                        model._base_manager.bulk_create(rows[i:i + BATCH])
                self.stdout.write(f'{label}: {len(rows)}')

            if not opts['dry_run']:
                grouped = defaultdict(list)
                for m2m, owner_id, target_id in m2m_rows:
                    through = m2m.remote_field.through
                    grouped[through].append(through(**{
                        through._meta.get_field(m2m.m2m_field_name()).attname: owner_id,
                        through._meta.get_field(m2m.m2m_reverse_field_name()).attname: target_id,
                    }))
                for through, rows in grouped.items():
                    for i in range(0, len(rows), BATCH):
                        through._base_manager.bulk_create(rows[i:i + BATCH])
                    self.stdout.write(f'{through._meta.label_lower} (m2m): {len(rows)}')
        finally:
            for f, auto_now, auto_now_add in disabled:
                f.auto_now, f.auto_now_add = auto_now, auto_now_add

        if not opts['dry_run']:
            bad = [(label, n, models[label]._base_manager.count()) for label, n in counts.items()
                   if models[label]._base_manager.count() != n]
            if bad:
                raise CommandError(f'Count mismatch (model, expected, actual): {bad}')
            self.stdout.write(self.style.SUCCESS('Import complete; all counts match.'))
        else:
            self.stdout.write(self.style.WARNING('Dry run: nothing written.'))
