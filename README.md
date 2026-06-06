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

## Arquitectura

| App | Responsabilidad |
|---|---|
| `core` | Autenticación, `UserProfile` con rol, base templates |
| `itsm` | Modelos de tickets, máquina de estados, vistas, permisos |

Ver `.claude/architecture.md` para detalle completo de la arquitectura.

## Roles

| Rol | Acceso |
|---|---|
| `requester` | Crea y consulta sus propios tickets |
| `agent` | Atiende tickets asignados y sin asignar |
| `manager` | Acceso completo, puede reasignar y cancelar |
| `admin` | Control total incluyendo configuración |

## Logs

Los logs de acceso y errores de gunicorn se generan en `logs/` (bind mount desde el host).
