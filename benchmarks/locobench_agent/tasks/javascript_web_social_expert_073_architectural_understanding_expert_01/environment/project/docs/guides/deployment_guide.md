```markdown
# PulseLearn Campus Hub – Deployment Guide
Transform your repository into a live, production-grade installation using the steps below.  
The snippets are **copy-paste ready**, follow Node.js/Javascript best practices, and embrace *zero-downtime*, *infrastructure-as-code* principles.

---

## 1. Prerequisites

1. **Node.js ≥ 18** – LTS recommended  
2. **Yarn ≥ 3** (PNPM works as well)  
3. **Docker ≥ 24** with *docker compose v2*  
4. **PostgreSQL ≥ 15** (managed service or container)  
5. **Redis ≥ 7** for session & cache back-plane  
6. **NATS ≥ 2.9** or **Kafka ≥ 3** for event backbone  
7. A Linux host (Ubuntu 22.04 LTS) or Kubernetes cluster  
8. Valid SSL/TLS certificates (Let’s Encrypt or custom CA)  

---

## 2. Environment Variables

Create `./.env.production.local` (never commit into VCS):

```properties
# ───────────────────── CORE APP ─────────────────────
NODE_ENV=production
PORT=8080
FRONTEND_URL=https://campus.acme.edu
BACKEND_URL=https://api.campus.acme.edu

# ──────────────────── DATABASE/REDIS ────────────────
DATABASE_URL=postgresql://pl_admin:✱✱✱@db.acme.edu:5432/pulselearn
REDIS_URL=redis://pl_redis:✱✱✱@redis.acme.edu:6379

# ─────────────────── AUTH / SESSION ─────────────────
JWT_SECRET=replace_me_with_a_long_random_string
SESSION_SECRET=replace_me_with_another_long_random_string
SESSION_TTL=1209600        # 14 days in seconds

# ─────────────────── THIRD-PARTY LOGIN ──────────────
OAUTH_GOOGLE_ID=...
OAUTH_GOOGLE_SECRET=...
OAUTH_MICROSOFT_ID=...
OAUTH_MICROSOFT_SECRET=...

# ──────────────────── SSL / SECURITY ────────────────
SSL_CERT_PATH=/etc/letsencrypt/live/campus.acme.edu/fullchain.pem
SSL_KEY_PATH=/etc/letsencrypt/live/campus.acme.edu/privkey.pem
CORS_WHITELIST=https://campus.acme.edu,https://admin.campus.acme.edu

# ───────────────────── MISC / OPS ───────────────────
LOG_LEVEL=info
SENTRY_DSN=https://xxxx@o123.ingest.sentry.io/98765
```

> ℹ️ Use separate `.env.staging.local` for staging with its own credentials.

---

## 3. Building the Production Bundle

```console
# Install exact dependency tree
$ corepack enable && yarn set version stable
$ yarn install --immutable

# Run type-checking, tests and lint in CI/CD
$ yarn typecheck && yarn test && yarn lint

# Build Next.js / React UI and server bundle
$ yarn build          # runs next build && tsc -p tsconfig.server.json

# The output lands in ./dist/
```

---

## 4. Dockerizing PulseLearn

`docker-compose.yml` (excerpt)

```yaml
version: "3.9"

services:
  api:
    build:
      context: .
      dockerfile: Dockerfile
    image: ghcr.io/pulselearn/campus-hub:${GIT_SHA}
    restart: always
    env_file:
      - .env.production.local
    ports:
      - "8080:8080"
    depends_on:
      - db
      - redis
      - nats
    healthcheck:
      test: ["CMD-SHELL", "node ./scripts/healthcheck.js"]
      interval: 30s
      timeout: 10s
      retries: 3

  db:
    image: postgres:15-alpine
    volumes:
      - ./ops/postgres/init:/docker-entrypoint-initdb.d
      - pgdata:/var/lib/postgresql/data
    environment:
      POSTGRES_USER: pl_admin
      POSTGRES_PASSWORD: ✱✱✱
      POSTGRES_DB: pulselearn

  redis:
    image: redis:7-alpine
    command: redis-server --save 60 1 --loglevel warning
    volumes:
      - redisdata:/data

  nats:
    image: nats:2.9-alpine
    command: "-js"

volumes:
  pgdata:
  redisdata:
```

---

### Dockerfile (Multi-Stage)

```Dockerfile
# ────── 1) Build stage ───────────────────────────────────────────────
FROM node:18-alpine AS builder
WORKDIR /app

COPY package.json yarn.lock ./
RUN corepack enable \
 && yarn install --immutable

COPY . .
RUN yarn build

# ────── 2) Production stage ─────────────────────────────────────────
FROM node:18-alpine
WORKDIR /app

# Install production-only deps
COPY package.json yarn.lock ./
RUN corepack enable \
 && yarn workspaces focus --production

COPY --from=builder /app/dist ./dist
COPY ./.env.production.local ./

# Harden container
USER node
EXPOSE 8080
CMD ["node", "dist/server.js"]
```

---

## 5. Deploying to Kubernetes

`helm/values.yaml` (sensible defaults borrowed from env vars)  
`kubectl apply -f k8s/` for raw manifests:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: pulselearn-api
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0        # zero-downtime
      maxSurge: 1
  selector:
    matchLabels:
      app: pulselearn-api
  template:
    metadata:
      labels:
        app: pulselearn-api
    spec:
      containers:
        - name: api
          image: ghcr.io/pulselearn/campus-hub:{{ .Values.image.tag }}
          ports:
            - containerPort: 8080
          envFrom:
            - secretRef:
                name: pulselearn-secrets
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 10
            periodSeconds: 5
      terminationGracePeriodSeconds: 30
```

---

## 6. Zero-Downtime Migration Script (`scripts/migrate.js`)

```js
/**
 * Zero-downtime database migrator invoked at container start-up.
 * 1. Connect via Prisma ORM
 * 2. Run pending migrations
 * 3. Seed essential reference data (idempotent)
 */
import { PrismaClient } from '@prisma/client';
import seed from './seed/index.js';

const prisma = new PrismaClient({
  log: ['info', 'warn', 'error']
});

async function main() {
  console.info('🛠  Running migrations...');
  await prisma.$executeRaw`SELECT 1`; // connectivity check
  await prisma.$transaction(async tx => {
    await tx.$runCommandRaw({ sql: 'BEGIN;' });
    await tx.$runCommandRaw({ sql: 'SET lock_timeout = 15000;' });
    await tx.$runCommandRaw({ sql: "SELECT migrate('latest');" }); // pgmq extension
    await seed(tx);
    await tx.$runCommandRaw({ sql: 'COMMIT;' });
  });
  console.info('✅ Migrations completed successfully');
}

main()
  .catch(err => {
    console.error('❌ Migration failed:', err);
    process.exitCode = 1;
  })
  .finally(async () => prisma.$disconnect());
```

In `Dockerfile` (production stage) append:

```Dockerfile
ENTRYPOINT ["node", "scripts/migrate.js"]
CMD ["node", "dist/server.js"]
```

---

## 7. GitHub Actions – Continuous Delivery (`.github/workflows/cd.yml`)

```yaml
name: CD

on:
  push:
    branches: [ main ]

jobs:
  docker:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 18
          cache: 'yarn'
      - name: Install & Build
        run: |
          corepack enable
          yarn install --immutable
          yarn build
      - name: Run Tests
        run: yarn test
      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Build & Push image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ghcr.io/pulselearn/campus-hub:${{ github.sha }}
      - name: Deploy to K8s
        uses: azure/k8s-set-context@v3
        with:
          method: kubeconfig
          kubeconfig: ${{ secrets.KUBECONFIG }}
      - name: Helm Upgrade
        run: |
          helm upgrade --install campus-hub ./helm \
            --set image.tag=${{ github.sha }}
```

---

## 8. Operational Commands

```console
# View real-time logs from all pods
$ kubectl logs -l app=pulselearn-api -f

# Trigger a blue-green deployment
$ helm upgrade campus-hub ./helm --set image.tag=<new_tag> --atomic

# Roll back to previous release instantly
$ helm rollback campus-hub 1

# Scale horizontally
$ kubectl scale deploy/pulselearn-api --replicas=5
```

---

## 9. Security Hardening Checklist

- ✅ Enforce HTTPS via Ingress with HSTS header (`max-age=63072000; includeSubDomains`).  
- ✅ Rotate `JWT_SECRET` & `SESSION_SECRET` at least every 90 days; use *Vault* or *SSM*.  
- ✅ Enable PostgreSQL TLS & restrict CIDR ranges to VPC only.  
- ✅ Set up automated container image scanning with **Trivy**.  
- ✅ Enable CSP, X-Frame-Options, and `.helmet()` middleware (already in codebase).  

---

## 10. Disaster Recovery

1. Point-in-time recovery for PostgreSQL (WAL-G snapshots, retention 14 days).  
2. Nightly S3 backups for `uploads/` bucket (student submissions).  
3. Redis persistence (`appendonly yes`, off-site rsync).  
4. Multi-AZ NATS cluster (JetStream) with quorum replication.  

---

🏁 **That’s it!** Your PulseLearn Campus Hub is now enterprise-grade, continuously delivered, and battle-tested for production traffic. Questions or improvements? Open a discussion on the repo. Happy deploying!
```