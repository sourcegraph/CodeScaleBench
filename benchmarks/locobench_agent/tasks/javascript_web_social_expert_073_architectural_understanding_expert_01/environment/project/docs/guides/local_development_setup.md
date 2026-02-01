```markdown
# PulseLearn Campus Hub  
### Local Development Setup Guide

> This document walks you through a **from-scratch** setup of the PulseLearn Campus Hub back-end, front-end, and infrastructure services on your local workstation. The steps assume you are comfortable with Node.js tooling and Docker.

---

## 1. Prerequisites

| Tool            | Minimum Version | Purpose                          |
|-----------------|-----------------|----------------------------------|
| Node.js         | `^18.16.0`      | Runtime for all JS/TS services   |
| pnpm            | `^8.6.0`        | Mono-repo package manager        |
| Docker Engine   | `>= 24`         | Container runtime                |
| Docker Compose  | Included        | Orchestrates local services      |
| Git             | `>= 2.40`       | Source-code management           |
| OpenSSL         | n/a             | Self-signed certificates (local) |

```bash
# macOS w/ Homebrew
brew install node pnpm docker git openssl
```

---

## 2. Clone the Repository

```bash
git clone git@github.com:PulseLearn/pulselearn-campus-hub.git
cd pulselearn-campus-hub
git checkout develop   # or feature branch
```

---

## 3. Bootstrap the Mono-repo

The project leverages **pnpm workspaces** to manage packages across services:

```bash
# install all dependencies (hoisted mode disabled for isolation)
pnpm install --frozen-lockfile
```

Available workspace packages:

```
packages/
├── api-gateway/         # Express + JWT + RBAC
├── auth-service/        # OAuth2, social login
├── event-bus/           # Kafka client, NATS wrapper
├── notifications/       # WebSocket + push
├── search-indexer/      # Elastic ingestion
└── web-app/             # Nuxt 3 front-end (SSR)
```

---

## 4. Environment Variables

1. Copy the template:  

   ```bash
   cp .env.example .env
   ```

2. Review & edit values to match your local environment.  

   ```ini
   # .env (excerpt)
   NODE_ENV=development
   PORT=3080

   # DB
   DB_HOST=localhost
   DB_PORT=5544
   DB_USER=pulselearn
   DB_PASS=devpassword
   DB_NAME=pulselearn_hub

   # Kafka
   KAFKA_BROKER=localhost:9092
   KAFKA_CLIENT_ID=pulselearn-dev

   # S3 / MinIO
   MINIO_ENDPOINT=http://localhost:9000
   MINIO_ACCESS_KEY=pl_minio
   MINIO_SECRET_KEY=pl_minio_secret

   # SSL (self-signed)
   SSL_KEY=./certs/localhost-key.pem
   SSL_CERT=./certs/localhost-cert.pem
   ```

---

## 5. Certificates (HTTPS in Development)

HTTPS is mandatory because the application integrates with OAuth providers that **require** a secure origin (even locally).

```bash
# scripts/generate-cert.sh
mkdir -p certs
openssl req \
  -x509 -nodes -days 365 \
  -newkey rsa:2048 \
  -keyout certs/localhost-key.pem \
  -out certs/localhost-cert.pem \
  -subj "/C=US/ST=Local/L=Dev/O=PulseLearn/CN=localhost"
chmod 600 certs/localhost-key.pem certs/localhost-cert.pem
```

```bash
bash scripts/generate-cert.sh
```

Add `localhost` to your browser’s “secure origins” if prompted.

---

## 6. Local Infrastructure (Docker Compose)

All services are defined in [`infra/docker-compose.dev.yml`](../../infra/docker-compose.dev.yml).

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASS}
      POSTGRES_DB: ${DB_NAME}
    ports:
      - "${DB_PORT}:5432"
    volumes:
      - dbdata:/var/lib/postgresql/data

  kafka:
    image: bitnami/kafka:3.5
    environment:
      KAFKA_CFG_LISTENERS: PLAINTEXT://:9092
      KAFKA_CFG_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092
      KAFKA_CFG_ZOOKEEPER_CONNECT: zookeeper:2181
    ports:
      - "9092:9092"
    depends_on:
      - zookeeper

  nats:
    image: nats:2.10-alpine
    ports:
      - "4222:4222"

  minio:
    image: minio/minio:RELEASE.2023-10-07T15-07-38Z
    command: server /data --console-address ":9091"
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY}
    ports:
      - "9000:9000"
      - "9091:9091"

volumes:
  dbdata:
```

Spin everything up:

```bash
docker compose -f infra/docker-compose.dev.yml up -d
```

Verify connectivity before proceeding:

```bash
# Should echo "1"
docker exec -it $(docker compose ps -q postgres) pg_isready -U ${DB_USER}
```

---

## 7. Database Migrations & Seed Data

Each service has its own migration scripts (`drizzle`, `knex`, or `typeorm` depending on package).  
Run them **after** the containers are healthy:

```bash
pnpm --filter "@pulselearn/api-gateway" run db:migrate
pnpm --filter "@pulselearn/auth-service" run db:migrate
pnpm --filter "@pulselearn/*" --parallel run db:seed     # seeds all packages
```

---

## 8. Start the Application Stack

All commands below use [concurrently](https://github.com/open-cli-tools/concurrently) to boot multiple services.

```bash
# Start back-end micro-services with hot-reload
pnpm dev:services

# Start front-end Nuxt app
pnpm --filter "@pulselearn/web-app" dev
```

Open `https://localhost:3000` and log in with the seeded demo user:

```
email: student@pulselearn.dev
password: Password123
```

---

## 9. Test, Lint, Type-Check

```bash
# Unit & integration tests (vitest, jest)
pnpm test

# ESLint + Prettier
pnpm lint

# TypeScript project references
pnpm typecheck
```

Git hooks (managed by Husky) prevent pushing code with failing checks; install them after the first `pnpm install`:

```bash
pnpm dlx husky install
```

---

## 10. Debugging with VS Code

```jsonc
// .vscode/launch.json
{
  "version": "0.2.0",
  "compounds": [
    {
      "name": "Dev-Stack",
      "configurations": ["API", "Auth", "Web"]
    }
  ],
  "configurations": [
    {
      "type": "node",
      "request": "attach",
      "name": "API",
      "port": 9229,
      "restart": true,
      "cwd": "${workspaceFolder}/packages/api-gateway"
    },
    {
      "type": "node",
      "request": "attach",
      "name": "Auth",
      "port": 9230,
      "restart": true,
      "cwd": "${workspaceFolder}/packages/auth-service"
    },
    {
      "type": "chrome",
      "request": "launch",
      "name": "Web",
      "url": "https://localhost:3000",
      "webRoot": "${workspaceFolder}/packages/web-app"
    }
  ]
}
```

Place breakpoints, hit `F5`, and debug away!

---

## 11. Troubleshooting

| Symptom                                   | Possible Cause                                  | Fix                                                                                 |
|-------------------------------------------|-------------------------------------------------|-------------------------------------------------------------------------------------|
| `ECONNREFUSED :9092`                      | Kafka container not ready                       | `docker compose logs -f kafka`, ensure zookeeper is healthy.                       |
| `SSL: CERT_COMMON_NAME_INVALID` in browser| Using `http://` instead of `https://`           | Always use HTTPS; add the self-signed cert to your system’s trust store.           |
| `psql: could not connect`                 | Port collision (`5432` already in use)          | Override `DB_PORT` in `.env` or stop existing postgres.                             |
| `ENOSPC: System limit for # of file watchers reached` | macOS/Linux inotify limit | `echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf && sudo sysctl -p` |

---

## 12. Cleaning Up

```bash
docker compose -f infra/docker-compose.dev.yml down -v --remove-orphans
pnpm exec rimraf "**/dist" "**/.turbo" "**/.next"
rm -rf certs
```

---

## 13. Next Steps

• Review the [Contribution Guidelines](../CONTRIBUTING.md)  
• Explore the [Domain Event Catalog](./event_catalog.md)  
• Join #dev-support on Slack for live assistance

Happy coding! 🚀
```