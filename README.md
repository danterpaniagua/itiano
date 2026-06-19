# Itiano

Soft-ITIL ticket management platform. Supports Incidents and Service Requests with a shared state machine, role-based permissions, and a modular Django architecture.

## Quick start (Docker)

```bash
cp .env.example .env
# Edit .env: set SECRET_KEY, DB_PASSWORD, ALLOWED_HOSTS
docker compose up --build
```

App runs at `http://localhost:8000`.

```bash
# Create superuser
docker compose exec app python manage.py createsuperuser
```

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env: point DB_HOST to your local PostgreSQL instance

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Running tests

Tests require PostgreSQL. Run inside the container:

```bash
docker compose exec app python manage.py test itsm jira_integration json_sandbox automations clipboard vault notes contacts timetracking settings_hub
```

Single test:

```bash
docker compose exec app python manage.py test itsm.tests.TestClassName.test_method_name
```

## Environment variables

| Variable | Description | Example |
|---|---|---|
| `SECRET_KEY` | Django secret key | long random string |
| `DEBUG` | Debug mode | `False` |
| `ALLOWED_HOSTS` | Allowed hosts | `localhost,127.0.0.1` |
| `DB_NAME` | Database name | `itiano` |
| `DB_USER` | PostgreSQL user | `itiano` |
| `DB_PASSWORD` | PostgreSQL password | — |
| `DB_HOST` | PostgreSQL host | `db` (Docker) / `localhost` (local) |
| `DB_PORT` | PostgreSQL port | `5432` |
| `JIRA_WEBHOOK_SECRET` | HMAC secret for Jira webhook validation | random string |

## Architecture

| App | Responsibility |
|---|---|
| `core` | Auth, `UserProfile` with role, dashboard with Jira In Progress time, base templates |
| `itsm` | Ticket models, state machine, views, permissions, attachments, Jira metadata tab |
| `jira_integration` | Jira webhook ingestion, event history, parent/child relationships, label and status filters |
| `json_sandbox` | Interactive JSONPath expression evaluator (staff only) |
| `automations` | Automation engine: Triggers with JSONPath filters fire Actions that create tickets |
| `clipboard` | Per-user encrypted clipboard, accessible from any page |
| `vault` | Encrypted credential store with versioning, KeePass import, per-user PBKDF2 key derivation |
| `notes` | Private notebooks per user with Markdown support and note sharing |
| `contacts` | Contact directory with configurable HTTP notification channels |
| `timetracking` | Jira time tracking per user: In Progress Gantt timeline, custom date range report, ticket activity drill-down with Jira comments |
| `settings_hub` | App settings (Tags, Categories — staff only) and user settings (schedule, timezone, Jira username) |

See `.claude/architecture.md` for full architecture detail.

## Roles

| Role | Access |
|---|---|
| `requester` | Creates and views their own tickets |
| `agent` | Handles assigned and unassigned tickets |
| `manager` | Full access, can reassign and cancel |
| `admin` | Full control including configuration |

## Version

The active version is read from the `VERSION` file at the project root and shown in the app footer.

## Logs

Gunicorn access and error logs are written to `logs/` (bind-mounted from the host).

## Media files

Files attached to tickets are stored in `media/` (bind-mounted from the host, created automatically). In development (`DEBUG=True`) Django serves them directly at `/media/`. In production a front-end web server (nginx or equivalent) is required to serve `MEDIA_ROOT`.
