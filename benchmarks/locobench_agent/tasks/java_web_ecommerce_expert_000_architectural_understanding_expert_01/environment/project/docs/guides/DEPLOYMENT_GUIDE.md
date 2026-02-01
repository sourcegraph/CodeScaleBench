```markdown
# CommerceSphere Enterprise Suite  
## Deployment Guide  

Last updated: 2024-06-19  
Author: DevOps & Release Engineering Team  

---

## Table of Contents
1. Introduction  
2. Supported Topologies  
3. Prerequisites  
4. Quick-Start (TL;DR)  
5. Building & Packaging  
6. Configuration Management  
7. Database Provisioning & Migrations  
8. Deployment Targets  
   * 8.1 Docker Compose  
   * 8.2 Kubernetes  
   * 8.3 Bare-Metal / Systemd  
9. Post-Deployment Validation  
10. Monitoring & Observability  
11. Backup & Disaster Recovery  
12. Rolling Updates & Zero-Downtime Strategy  
13. Security Hardening Checklist  
14. Troubleshooting  
15. FAQ  

---

## 1. Introduction
This document describes **how to deploy CommerceSphere Enterprise Suite** (CSES) into production-grade environments.  
The guide assumes the **monolithic JAR** distribution produced by the `web_ecommerce` Gradle module and covers cloud-native and on-prem strategies.

> NOTE: All examples use the *v3* major release line. For v2 or early adopters of v4/next, consult compatibility notes in the appendix.

---

## 2. Supported Topologies
| Topology | Recommended Scale | Comments |
|----------|------------------|----------|
| Single-Node / PoC | ≤ 100 concurrent sessions | No HA, minimal footprint |
| Active–Passive (2 Nodes) | ≤ 2 000 concurrent sessions | Uses shared RDBMS & Redis for session fail-over |
| Kubernetes Cluster | 2–50 nodes | Horizontal Pod Autoscaling, native probes |
| Hybrid Cloud | 1 Kubernetes + 1 Bare-Metal DR | Split traffic, DR on-prem |

---

## 3. Prerequisites
1. **Java 21 LTS** (Temurin or Oracle).  
2. **PostgreSQL 15+** with UTF-8 encoding.  
3. **Redis 7+** for HTTP session & cache invalidation.  
4. **Flyway 9.x** bundled, no external installation necessary.  
5. **Docker Engine 24.x** *or* containerd runtime for K8s.  
6. Reverse proxy / Ingress controller that supports **HTTP/2** and **TLS 1.3** (e.g., NGINX, Traefik, AWS ALB).  
7. Outbound connectivity to your Artifact Repository (JFrog, Nexus, GitHub Packages).  

---

## 4. Quick-Start (TL;DR)

```bash
# (1) Pull artifact
curl -O https://artifacts.corp.local/cses/web_ecommerce-3.2.1-all.jar

# (2) Prepare .env file
cp ./deploy/sample.env .env && nano .env

# (3) Start via Docker
docker compose -f deploy/compose/docker-compose.yml up -d

# (4) Tail logs
docker compose logs -f app
```

You should see:

```
INFO  2024-06-19T10:33:27  o.c.CommerceSphereApp  : Application started in 42.133 seconds
```

---

## 5. Building & Packaging

### 5.1 Local Build

```bash
git clone ssh://git@github.com/CommerceSphere/EnterpriseSuite.git
cd EnterpriseSuite
./gradlew clean :web_ecommerce:shadowJar
```

The command produces  
`web_ecommerce/build/libs/web_ecommerce-<ver>-all.jar`  
(a fat JAR with shaded dependencies).

### 5.2 CI/CD Pipeline (GitHub Actions)

```yaml
# .github/workflows/build.yml
name: Build & Publish

on:
  push:
    tags: ['v*']

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: 21
      - run: ./gradlew :web_ecommerce:shadowJar
      - uses: jfrog/setup-jfrog-cli@v2
      - run: jfrog rt u "web_ecommerce/build/libs/*-all.jar" cses-maven-prod/
```

---

## 6. Configuration Management

CSES resolves configuration using *Spring Boot’s* layered approach:

1. `application.yml` inside the JAR (defaults).  
2. `${HOME}/.cses/application.yml` (user overrides).  
3. Environment variables (`CSES_*`).  
4. CLI flags (`--key=value`).  

### 6.1 Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `CSES_DB_URL` | JDBC connection string | `jdbc:postgresql://db:5432/cses` |
| `CSES_DB_USER` | Database user | `cses_app` |
| `CSES_DB_PASS` | Database password | `••••` |
| `CSES_REDIS_URI` | Redis endpoint | `redis://redis:6379/0` |
| `CSES_JWT_SECRET` | 256-bit secret for auth tokens | `$(openssl rand -hex 32)` |
| `CSES_ALLOWED_ORIGINS` | CORS whitelist | `https://shop.example.com` |

> Tip: For production, export variables via your orchestrator’s secret store (K8s Secrets, AWS Parameter Store, HashiCorp Vault).

---

## 7. Database Provisioning & Migrations

1. Create a PostgreSQL database:

```sql
CREATE USER cses_app WITH ENCRYPTED PASSWORD 'REPLACE_ME';
CREATE DATABASE cses OWNER cses_app ENCODING 'UTF8';
GRANT ALL PRIVILEGES ON DATABASE cses TO cses_app;
```

2. Run Flyway migrations:

```bash
java -jar web_ecommerce-3.2.1-all.jar \
     --flyway.user=cses_app \
     --flyway.password=$CSES_DB_PASS \
     --flyway.url=jdbc:postgresql://db:5432/cses \
     migrate
```

> Migrations are automatically executed on app start-​up unless `CSES_FLYWAY_ENABLED=false`.

---

## 8. Deployment Targets

### 8.1 Docker Compose

`deploy/compose/docker-compose.yml`

```yaml
version: "3.9"

services:
  app:
    image: ghcr.io/commercesphere/cses:3.2.1
    env_file: .env
    ports:
      - "8080:8080"
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8080/actuator/health || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: cses_app
      POSTGRES_PASSWORD: ${CSES_DB_PASS}
      POSTGRES_DB: cses
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER"]
  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes"]
```

Start: `docker compose up -d`

### 8.2 Kubernetes

Apply manifests:

```bash
kubectl apply -k deploy/k8s/overlays/prod
```

Key resources:

* **Deployment** with `readinessProbe` + `livenessProbe`.  
* **ConfigMap** for non-secret properties.  
* **Secret** holding passwords and JWT keys.  
* **HorizontalPodAutoscaler** scaling 2–12 pods based on CPU ≥ 60 %.  

Excerpt:

```yaml
# deploy/k8s/base/deployment.yml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cses-app
spec:
  replicas: 2
  selector:
    matchLabels:
      app: cses
  template:
    metadata:
      labels:
        app: cses
    spec:
      containers:
        - name: cses
          image: ghcr.io/commercesphere/cses:3.2.1
          resources:
            requests:
              memory: "1024Mi"
              cpu: "500m"
            limits:
              memory: "2Gi"
              cpu: "2"
          envFrom:
            - secretRef:
                name: cses-secrets
            - configMapRef:
                name: cses-config
          readinessProbe:
            httpGet:
              path: /actuator/health/readiness
              port: 8080
            initialDelaySeconds: 30
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /actuator/health/liveness
              port: 8080
            initialDelaySeconds: 60
            periodSeconds: 30
```

### 8.3 Bare-Metal / Systemd

1. Copy artifact and `cses.service` onto host (`/etc/systemd/system`).

```ini
# /etc/systemd/system/cses.service
[Unit]
Description=CommerceSphere Enterprise Suite
After=network.target

[Service]
User=cses
Group=cses
EnvironmentFile=/opt/cses/.env
ExecStart=/usr/bin/java -Xms1G -Xmx2G -jar /opt/cses/web_ecommerce-3.2.1-all.jar
SuccessExitStatus=143
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

2. Reload and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cses
```

---

## 9. Post-Deployment Validation

```bash
curl -s http://<host>:8080/actuator/health | jq
# expect: {"status":"UP","components":{...}}
```

Open Swagger UI: `https://<domain>/api-docs/index.html`

Run synthetic transactions:

```bash
curl -X POST https://<domain>/api/v1/auth/login \
     -d '{"username":"demo@corp","password":"ChangeMe123"}' \
     -H "Content-Type: application/json"
```

Look for HTTP 200 / token issued.

---

## 10. Monitoring & Observability

* **Metrics**: Exposed at `/actuator/prometheus`.  
  * Grafana dashboard ID `18743` (CommerceSphere default).  
* **Logs**: Structured (JSON) to `stdout`.  
  * Shipping via Fluent Bit → OpenSearch.  
* **Tracing**: OpenTelemetry auto-instrumentation; OTLP endpoint configurable via `CSES_OTEL_EXPORTER_URL`.  

---

## 11. Backup & Disaster Recovery

1. **Database**: `pg_dump` every 15 min; WAL archiving to S3 bucket with 7-day retention.  
2. **Redis**: AOF persisted to EBS; snapshot every 30 min.  
3. **Artifact**: Immutable JARs; restore by redeploying same tag.  
4. **Configurations**: Git-ops; restore by re-applying manifests.  

DR Runbook: Promote standby DB, scale app instances, switch DNS (<= 5 min RTO).

---

## 12. Rolling Updates & Zero-Downtime Strategy

1. **Blue/Green** for bare-metal.  
2. **RollingUpdate** (maxUnavailable 1) for K8s.  
3. Sticky session not required (JWT tokens).  
4. Maintain DB backward compatibility for at least one minor release to allow dual-running versions.

---

## 13. Security Hardening Checklist

- [x] Enforce TLS 1.2+ at ingress.  
- [x] Rotate `CSES_JWT_SECRET` quarterly.  
- [x] Enable CSRF protection in admin panel: `CSES_SECURITY_CSRF_ENABLED=true`.  
- [x] Run vulnerability scan (Snyk) on `ghcr.io/commercesphere/cses:*`.  
- [x] Set `readOnlyRootFilesystem: true` in container spec.  

---

## 14. Troubleshooting

| Symptom | Probable Cause | Resolution |
|---------|---------------|------------|
| `org.postgresql.util.PSQLException: FATAL: password authentication failed` | Wrong `CSES_DB_PASS` | Update secret, restart pod |
| HTTP 503 from ALB | App readiness probe failing | Check `/actuator/health`, investigate DB/Redis connectivity |
| Slow product search | ElasticSearch indexing lag | Run `POST /admin/reindex`, check ES cluster health |
| Excessive GC pauses | Heap too small | Increase `JAVA_TOOL_OPTIONS=-Xmx4G` |

---

## 15. FAQ

**Q:** Can I deploy multiple tenants in one database?  
**A:** Yes, enable `CSES_MULTI_TENANT=true` and configure `tenant_id` discriminator.

**Q:** Does the suite run on Java 17?  
**A:** Java 17 is in maintenance mode; run tests against build matrix, but 21 LTS is vendor-supported.

**Q:** Where do I configure payment gateways?  
**A:** `application-payment.yml` or `/admin/payment/providers` UI; values are encrypted with KMS.

---

> © 2024 CommerceSphere, Inc. — All rights reserved.
```