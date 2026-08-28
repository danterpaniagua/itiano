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

SSL_ARGS=()
if [ "$DEBUG" = "True" ]; then
  mkdir -p /app/certs
  if [ ! -f /app/certs/dev-cert.crt ] || [ ! -f /app/certs/dev-cert.key ]; then
    echo "Generating self-signed dev certificate..."
    python - <<'PYEOF'
import datetime
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
cert = (
    x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime.utcnow())
    .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
    .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
    .sign(key, hashes.SHA256())
)

with open("/app/certs/dev-cert.key", "wb") as f:
    f.write(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))

with open("/app/certs/dev-cert.crt", "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))
PYEOF
  fi
  echo "DEBUG=True, serving HTTPS with dev certificate."
  SSL_ARGS=(--certfile=/app/certs/dev-cert.crt --keyfile=/app/certs/dev-cert.key)
fi

exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 2 \
  --timeout 30 \
  --graceful-timeout 30 \
  --access-logfile /app/logs/access.log \
  --error-logfile /app/logs/error.log \
  "${SSL_ARGS[@]}"
