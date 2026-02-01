```markdown
# CrowdPay Connect – Local Setup Guide
Welcome to the **CrowdPay Connect** contributor guide.  
This document walks you through spinning up a **production-parity** development
environment on macOS, Linux, or Windows (WSL2).

---

## 1 . Prerequisites
| Tool | Minimum Version | Purpose |
|------|-----------------|---------|
| [Python](https://www.python.org/) | `3.11` | Application runtime |
| [Poetry](https://python-poetry.org/) | `1.6` | Dependency / venv manager |
| [Docker Desktop](https://www.docker.com/) | `24.x` | Local container orchestration |
| GNU `make` | `4.x` | Task automation (optional but recommended) |
| [pre-commit](https://pre-commit.com/) | `2.20` | Git hook runner |

```bash
# macOS (brew)
brew install python@3.11 poetry docker make pre-commit

# Ubuntu
sudo apt-get install python3.11 python3.11-venv make
curl -sSL https://install.python-poetry.org | python3 -
sudo apt-get install docker.io docker-compose-plugin
pip install --user pre-commit
```

> 📝  *Python <3.11* is **NOT** supported because the platform relies on `taskgroups`
> (PEP -657) and `tomllib`.

---

## 2 . Repository Bootstrap

```bash
# 1. Clone
git clone git@github.com:crowdpay/crowdpay-connect.git
cd crowdpay-connect

# 2. Initialise Git hooks
pre-commit install --install-hooks

# 3. Spin-up the full stack
make up  # wrapper for docker compose up -d --build
```

The first run may take a few minutes while Docker images are built and Poetry
downloads all dependencies into its virtualenv.

---

## 3 . Environment Variables

CrowdPay Connect adheres to the [Twelve-Factor](https://12factor.net/) methodology.
All config is injected via the `./.env` file **only** (never commit secrets!).

```dotenv
# .env.sample  – copy to .env and override as needed
# ────────────────────────────────────────────────────
# Django
DJANGO_SECRET_KEY=changeme
DJANGO_SETTINGS_MODULE=crowdpay_connect.settings.local
DJANGO_DEBUG=1

# Postgres
POSTGRES_USER=crowdpay
POSTGRES_PASSWORD=insecure
POSTGRES_DB=crowdpay_connect
POSTGRES_HOST=db
POSTGRES_PORT=5432

# Redis (event & saga buses)
REDIS_URL=redis://cache:6379/0

# Celery
CELERY_BROKER_URL=${REDIS_URL}
CELERY_RESULT_BACKEND=${REDIS_URL}

# External Integrations (mocked locally)
FX_RATES_ENDPOINT=http://fx:8000/rates
KYC_PROVIDER_BASE=http://kyc:9000
```

---

## 4 . Container Topology

```text
┌─────────────┐  Saga+ES  ┌──────────────┐    Logical   ┌──────────────┐
│  django-api ├──────────►│  postgres    ├─────────────►│  metabase     │
└──────┬──────┘           └──────────────┘              └──────────────┘
       │▲                      ▲  ▲
HTTP   ││                      │  │
       ▼│                      │  │  Streams
┌─────────────┐  CELERY   ┌────┴──┴─────┐  Pub/Sub  ┌──────────────┐
│  front-end  │──────────►│  redis/roq   │──────────►│  fx-service  │
└─────────────┘           └──────────────┘           └──────────────┘
```

All services are orchestrated via a single `docker-compose.yml`, giving you
an **exact** mirror of staging minus PCI-grade secrets.

---

## 5 . Database – Migrations & Seed Data

```bash
# Open an interactive Django shell inside the api container
make shell           # -> docker exec -it api bash

# Apply migrations
python manage.py migrate

# Load initial reference data (currencies, risk-scoring weights, etc.)
python manage.py loaddata fixtures/initial_seed.yaml
```

---

## 6 . Running the Test Suite

The project ships with 1:1 parity between unit, integration, and contract
tests.  All tests run inside an isolated container to guarantee reproducibility.

```bash
make test           # synonym for: docker compose run --rm api pytest -q
```

### 6.1  Selective Test Execution

```bash
# Only saga-layer tests (marked with @pytest.mark.saga)
make test TEST="tests/saga -m saga"

# Watch-mode unit tests (requires pytest-watch)
poetry run ptw tests/unit
```

---

## 7 . Static Analysis & Linting

```bash
make lint           # ruff + mypy + safety
make format         # ruff format
```

A failing hook blocks the commit; fix issues locally or bypass with
`git commit --no-verify` **(avoid in shared branches)**.

---

## 8 . Live-Reload Development Server

```bash
# API (Django + uvicorn ASGI)
make dev

# Front-end (Next.js)
make ui
```

Both commands mount your host code via `:delegated` volumes and reload on file
changes. API hot-reload leverages `watchfiles` for sub-250 ms latency.

---

## 9 . How to Debug Saga Workflows

Enable verbose logging, then tail the service log:

```bash
export LOG_LEVEL=DEBUG
docker compose logs -f api | grep --line-buffered 'SagaEngine'
```

Breakpoints can be set inside the container with `debugpy`:

```python
# anywhere in your code
import debugpy; debugpy.listen(("0.0.0.0", 5678)); debugpy.wait_for_client()
```

Attach from VSCode via the *“Python: Remote Attach”* template.

---

## 10 . Common Pitfalls

| Symptom | Root Cause | Fix |
|---------|-----------|------|
| `django.db.utils.OperationalError: could not connect to server` | Postgres container still booting | `docker compose restart api` (wait 5 s) |
| Celery tasks stuck in *PENDING* | Missing Redis connection / wrong URL | Verify `REDIS_URL` in `.env` |
| DateTime mismatch errors | Local TZ ≠ `UTC` | Set `TZ=UTC` in your shell |

---

## 11 . Teardown

```bash
make down          # docker compose down --volumes --remove-orphans
```

---

## 12 . Contributing Workflow (TL;DR)

1. `git switch -c feat/<ticket-id>-concise-branch-name`
2. Write code & **add/extend tests**
3. `pre-commit run --all-files`
4. `git commit -m "feat: 🎉 add cross-border payout saga"`
5. Open PR → wait for CI to turn green
6. Request peer review (2 approvals min.)

---

## 13 . Semantic Make Targets (Cheat-Sheet)

```make
# Makefile excerpt
up:          ## Build & start core services
down:        ## Stop & remove all containers + volumes
logs:        ## Tail aggregated logs
shell:       ## Bash into api container
dev:         ## Launch Django + uvicorn with autoreload
test:        ## Run pytest (param: TEST for pattern)
lint:        ## Ruff, mypy, safety
format:      ## Black-compatible auto-formatter via Ruff
ui:          ## Next.js dev server (Turbo Pack)
db.psql:     ## psql session inside db container
migrate:     ## Run Django migrations
```

> 💡 Run `make` without arguments to list all targets and descriptions.

---

## 14 . Appendix – Manual Python Runner (No Docker)

Although **Docker is strongly recommended**, you can run services directly on
your host:

```bash
poetry install --with dev
cp .env.sample .env                       # update secrets
psql -c 'CREATE DATABASE crowdpay_connect;'

# Start postgres & redis locally (brew services start ...)
export DJANGO_SETTINGS_MODULE=crowdpay_connect.settings.local
python manage.py migrate
python -Xfrozen_modules=off -m uvicorn crowdpay_connect.asgi:application --reload
```

Expect slight deviations from production behavior (e.g., missing pgvector).

---

Happy hacking! 💸🤝  
Questions? Ping `@core-engineering` on Slack or open a GitHub Discussion.
```