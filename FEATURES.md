# Bulk Email Platform — Features & Tech Stack

This repo is a bulk email sending platform with a FastAPI backend, a built-in web UI, multi-provider sending (SMTP + email APIs), and PostgreSQL persistence.

## Tech Stack

### Backend
- Language/runtime: Python 3.11
- Web framework: FastAPI (Starlette under the hood)
- Server: Uvicorn
- Validation: Pydantic v2
- ORM: SQLAlchemy 2.x
- Database driver: `psycopg2` via `psycopg2-binary`

### Email & integrations
- SMTP sending: `aiosmtplib`
- API sending: `httpx` (async HTTP client)
- Optional AWS tooling: `boto3` (dependency included)
- Email validation: `email-validator`

### Deliverability tooling
- DNS checks: `dnspython`

### Frontend (built-in web UI)
- Server-side templates: Jinja2 (`templates/*.html`)
- Static assets: vanilla JS + CSS (`static/js/app.js`, `static/css/style.css`)

### Deployment
- Containers: Docker
- Local orchestration: `docker-compose.yml`
- Database container: PostgreSQL 16 (alpine)

## Core Product Features

### Web UI
- Dashboard page (`GET /`) showing totals and recent campaign activity.
- Providers page (`GET /providers`) for viewing configured SMTP/API providers (UI uses API endpoints; add/delete primarily via API).
- Templates page (`GET /templates`) exists as a placeholder.
- Auto-refresh: dashboard periodically reloads stats and campaigns.

### Campaign lifecycle
- Create campaigns with HTML + optional text body.
- Upload recipients via CSV with basic validation and deduplication.
- Start sending as a background task (non-blocking API call).
- Pause a running campaign.
- Real-time progress reporting (sent/failed/total/rate/ETA) during sending.
- Export campaign results as CSV (recipient + status + message_id + errors).

### Personalization
- Subject/body variable substitution using `{{variable}}` placeholders.
- Automatically maps CSV columns into per-recipient personalization data (`email`, `first_name`, `last_name`, plus any additional columns).

### Multi-provider sending

SMTP providers:
- Any SMTP server with TLS/SSL options and credential-based auth.
- Connection test endpoint.
- Retry logic for sends.

API providers (implemented in code):
- SendGrid
- Mailgun
- Postmark
- Mailjet
- Amazon SES (implemented via SES SMTP endpoints)

### Logging, reporting, and exports
- Per-send logging into `SendLog` with provider response/error data.
- Campaign “events” endpoint (paginated).
- Aggregate stats endpoint and a “detailed” provider breakdown endpoint.

### Suppression list management
- Add/list/remove suppressed emails.
- Skips suppressed emails during CSV import.
- Export suppression list as CSV.

### Seed testing (inbox placement spot checks)
- Send a test message to a list of “seed” addresses to manually verify inbox vs spam placement.

## REST API (FastAPI)

Health:
- `GET /api/test`

SMTP accounts:
- `GET /api/smtp-accounts`
- `POST /api/smtp-accounts`
- `POST /api/smtp-accounts/{account_id}/test`
- `DELETE /api/smtp-accounts/{account_id}`

API providers:
- `GET /api/api-providers`
- `POST /api/api-providers`
- `POST /api/api-providers/{provider_id}/test`
- `DELETE /api/api-providers/{provider_id}`

Campaigns:
- `GET /api/campaigns`
- `POST /api/campaigns`
- `GET /api/campaigns/{campaign_id}`
- `POST /api/campaigns/{campaign_id}/upload-recipients`
- `POST /api/campaigns/{campaign_id}/start`
- `POST /api/campaigns/{campaign_id}/pause`
- `GET /api/campaigns/{campaign_id}/progress`
- `GET /api/campaigns/{campaign_id}/events`
- `GET /api/campaigns/{campaign_id}/export`
- `DELETE /api/campaigns/{campaign_id}`

Testing:
- `POST /api/send-test`
- `POST /api/seed-test`

Suppressions:
- `GET /api/suppressions`
- `POST /api/suppressions`
- `DELETE /api/suppressions/{email}`
- `GET /api/suppressions/export`

Stats:
- `GET /api/stats`
- `GET /api/stats/detailed`

## Data Model (PostgreSQL)

Primary tables:
- Providers: `smtp_accounts`, `api_providers`, `imap_accounts`
- Campaigns: `campaigns`, `recipients`, `send_logs`
- Deliverability: `bounces`, `suppressions`
- Templates/config: `templates`, `settings`
- Seed testing: `seed_tests`, `seed_test_results`

## Operations & Migration

### Runtime persistence
- PostgreSQL is the only supported runtime database (configured via `DATABASE_URL`).

### Legacy SQLite migration (one-time)
- CLI: `scripts/migrate_sqlite_to_postgres.py`
- Startup automation: set `MIGRATE_FROM_SQLITE_PATH` (optional `MIGRATE_TRUNCATE_TARGET=1`, `MIGRATE_DELETE_SOURCE=1`).
- Migration marker stored in `settings` to avoid re-running unintentionally.

## Security & Limitations (Current State)

- No authentication/authorization (API is open; CORS is configured to allow all origins).
- Provider secrets (SMTP passwords/API keys) are stored in plaintext in the database.
- “Delivered” counts are optimistic in the current sending loop (successful provider acceptance is treated as delivered until bounce/webhook support exists).
- Bounce processing and open/click tracking helpers exist as library utilities, but there are no `/track/...` routes and no IMAP bounce processing endpoints wired up yet.
- API docs are disabled (`docs_url=None`), even though the API is FastAPI-based.
