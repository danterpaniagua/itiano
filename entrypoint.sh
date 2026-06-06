#!/bin/bash
set -e

echo "Waiting for database..."
until python -c "
import os, psycopg2
psycopg2.connect(
    dbname=os.environ.get('DB_NAME', 'itiano'),
    user=os.environ.get('DB_USER', 'itiano'),
    password=os.environ.get('DB_PASSWORD', ''),
    host=os.environ.get('DB_HOST', 'db'),
    port=os.environ.get('DB_PORT', '5432'),
    connect_timeout=3,
).close()
" 2>/dev/null; do
  echo "  database not ready, retrying in 2s..."
  sleep 2
done
echo "Database ready."

python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 2 \
  --access-logfile /app/logs/access.log \
  --error-logfile /app/logs/error.log
