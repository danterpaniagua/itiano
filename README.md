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

### Local HTTPS

Some integrations (e.g. Jira webhooks) require a valid HTTPS endpoint even in local dev. With `DEBUG=True`, `django-extensions` is enabled and `runserver_plus` can serve over HTTPS with a self-signed certificate:

```bash
python manage.py runserver_plus --cert-file certs/dev-cert
```

This generates `certs/dev-cert.crt` / `certs/dev-cert.key` on first run (the `certs/` dir is gitignored) and serves at `https://localhost:8000`. Your browser will warn about the self-signed cert — accept it to proceed.

The Docker Compose `app` service serves HTTPS the same way: when `DEBUG=True` it generates (or reuses) `certs/dev-cert.crt` / `certs/dev-cert.key` on startup and binds gunicorn to them. No extra steps needed — just set `DEBUG=True` in `.env` and `docker compose up`.

## Running tests

Tests require PostgreSQL. Run inside the container:

```bash
docker compose exec app python manage.py test itsm jira_integration json_sandbox automations clipboard vault notes contacts timetracking settings_hub notifications
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
| `JIRA_API_BASE_URL` | Jira Cloud base URL, used by `jira_reconcile` | `https://yourcompany.atlassian.net` |
| `JIRA_API_EMAIL` | Jira account email for Basic Auth, used by `jira_reconcile` | — |
| `JIRA_API_TOKEN` | Jira API token for Basic Auth, used by `jira_reconcile` | — |

## Jira reconciliation

The webhook (`jira_integration`) is the primary source of ticket status history. If the app is
down when Jira sends a webhook, that event is lost — Jira does not retry indefinitely. The
`jira_reconcile` management command polls the Jira REST API for tickets updated since the last
successful run and backfills any missing status transitions from the changelog.

Set `JIRA_API_BASE_URL`, `JIRA_API_EMAIL`, and `JIRA_API_TOKEN`, then run it on a schedule via
host cron (there is no Celery/scheduler in this stack):

```bash
python manage.py jira_reconcile          # same as: jira_reconcile by_time
```

```cron
# /etc/cron.d/itiano-jira-reconcile — hourly
0 * * * * root cd /path/to/itiano && docker compose exec -T app python manage.py jira_reconcile >> /path/to/itiano/logs/jira_reconcile.log 2>&1
```

For a one-off backfill of recent tickets that predate the webhook or were otherwise missed
entirely (not just their status history — the ticket itself), use `last [N]` (defaults to 300):

```bash
python manage.py jira_reconcile last          # last 300 tickets by issue number
python manage.py jira_reconcile last 500      # last 500
```

Unlike `by_time`, `last` creates the local ticket if it doesn't exist yet, and never touches the
`by_time` watermark.

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
| `notifications` | In-app notifications: `notify()` alerts a user or a `core.Team`, surfaced via navbar bell + full list page |

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
