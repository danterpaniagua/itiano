# Itiano

Plataforma de gestión de tickets ITIL simplificada. Soporta Incidentes y Solicitudes de Servicio con máquina de estados compartida, permisos por rol y arquitectura modular Django.

## Requisitos

- Docker y Docker Compose
- Python 3.12+ con `python3-venv` (para desarrollo local)

## Inicio rápido (Docker)

```bash
cp .env.example .env
# Editar .env: configurar SECRET_KEY, DB_PASSWORD y ALLOWED_HOSTS
docker compose up --build
```

La app queda disponible en `http://localhost:8000`.

```bash
# Crear superusuario
docker compose exec app python manage.py createsuperuser
```

## Desarrollo local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Editar .env: apuntar DB_HOST a tu instancia local de PostgreSQL

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Ejecutar tests

Los tests requieren la base de datos PostgreSQL. Ejecutar dentro del contenedor:

```bash
docker compose exec app python manage.py test itsm jira_integration json_sandbox automations clipboard vault notes contacts
```

## Variables de entorno

| Variable | Descripción | Ejemplo |
|---|---|---|
| `SECRET_KEY` | Clave secreta Django | cadena aleatoria larga |
| `DEBUG` | Modo debug | `False` |
| `ALLOWED_HOSTS` | Hosts permitidos | `localhost,127.0.0.1` |
| `DB_NAME` | Nombre de la base de datos | `itiano` |
| `DB_USER` | Usuario PostgreSQL | `itiano` |
| `DB_PASSWORD` | Contraseña PostgreSQL | — |
| `DB_HOST` | Host PostgreSQL | `db` (Docker) / `localhost` (local) |
| `DB_PORT` | Puerto PostgreSQL | `5432` |
| `JIRA_WEBHOOK_SECRET` | Secreto HMAC para validar webhooks de Jira | cadena aleatoria |

## Arquitectura

| App | Responsabilidad |
|---|---|
| `core` | Autenticación, `UserProfile` con rol, base templates, footer con versión |
| `itsm` | Modelos de tickets, máquina de estados, vistas, permisos, adjuntos, pestaña de metadatos Jira |
| `jira_integration` | Recepción de webhooks de Jira, historial de eventos por ticket |
| `json_sandbox` | Evaluación interactiva de expresiones JSONPath (solo staff) |
| `automations` | Motor de automatizaciones: Triggers con filtros JSONPath disparan Actions que crean tickets |
| `clipboard` | Portapapeles cifrado por usuario, accesible desde cualquier página |
| `vault` | Almacén de credenciales cifradas con versionado automático e importación KeePass |
| `notes` | Blocs de notas privados por usuario con soporte Markdown |
| `contacts` | Directorio de contactos con canales de notificación HTTP configurables |

Ver `.claude/architecture.md` para detalle completo de la arquitectura.

## Roles

| Rol | Acceso |
|---|---|
| `requester` | Crea y consulta sus propios tickets |
| `agent` | Atiende tickets asignados y sin asignar |
| `manager` | Acceso completo, puede reasignar y cancelar |
| `admin` | Control total incluyendo configuración |

## Versión

La versión activa se lee del archivo `VERSION` en la raíz del proyecto y se muestra en el footer de la aplicación.

## Logs

Los logs de acceso y errores de gunicorn se generan en `logs/` (bind mount desde el host).

## Archivos adjuntos

Los archivos subidos a tickets se almacenan en `media/` (bind mount desde el host, creado automáticamente). En entornos de desarrollo (`DEBUG=True`) Django sirve los archivos directamente en `/media/`. En producción se requiere un servidor de archivos externo (nginx u equivalente) para servir `MEDIA_ROOT`.
