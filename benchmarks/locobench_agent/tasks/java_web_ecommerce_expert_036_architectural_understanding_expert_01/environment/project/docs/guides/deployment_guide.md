```markdown
# SprintCart Pro – Deployment Guide
_Effective date: 2024-05-13_

This guide describes how to package, configure, and operate SprintCart Pro in **local**, **staging**, and **production** environments.  
The instructions assume you have:

* JDK 21
* Docker 24+
* Maven 3.9+
* kubectl 1.29+ (for Kubernetes users)
* Access to a PostgreSQL 14 instance (local, Docker, or managed)

---

## 1  Project Build

SprintCart Pro is a standard Maven multi-module project that follows Hexagonal Architecture.  
To produce an optimized, container-ready artifact, simply run:

```bash
# Compile, unit-test, integration-test, and produce a fat JAR
mvn -Pprod -DskipUT -DskipIT=false clean verify
```

Key Maven profiles:
| Profile | Purpose | Notes |
|---------|---------|-------|
| `dev`   | Hot-swap DevTools, H2 in-memory DB, mock gateways | Default when running `mvn spring-boot:run` |
| `test`  | Static analysis (PMD, SpotBugs), unit + component tests | Runs in CI |
| `prod`  | GraalVM optimizations, minimized dependencies | Used by Dockerfile |

---

## 2  Docker Image

A production-grade image is already maintained on GitHub Container Registry (`ghcr.io/sprintcart/sprintcart-pro`).  
To build from source:

```dockerfile
# sprintcart-pro/Dockerfile
FROM eclipse-temurin:21-jre-jammy AS base
LABEL maintainer="devops@sprintcart.io" \
      org.opencontainers.image.source="https://github.com/sprintcart/sprintcart-pro"

ARG JAR_FILE=app/sprintcart-pro-web/target/sprintcart-pro.jar
COPY ${JAR_FILE} /opt/sprintcart/sprintcart-pro.jar

# Non-root user for security
RUN useradd -r -s /bin/false sprintcart
USER sprintcart

ENV JAVA_OPTS="-Xms512m -Xmx2g"
ENTRYPOINT ["sh","-c","exec java $JAVA_OPTS -jar /opt/sprintcart/sprintcart-pro.jar"]
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8080/actuator/health || exit 1
```

Build & push:

```bash
docker build \
  --build-arg JAR_FILE=app/sprintcart-pro-web/target/sprintcart-pro.jar \
  -t ghcr.io/sprintcart/sprintcart-pro:1.8.2 .
docker push ghcr.io/sprintcart/sprintcart-pro:1.8.2
```

---

## 3  Environment Variables

| Variable | Example | Required | Description |
|----------|---------|----------|-------------|
| `SPRING_DATASOURCE_URL`      | `jdbc:postgresql://db:5432/sprintcart` | ✔️ | JDBC URL |
| `SPRING_DATASOURCE_USERNAME` | `sprintcart` | ✔️ | DB user |
| `SPRING_DATASOURCE_PASSWORD` | `super-secret` | ✔️ | DB password |
| `JWT_SECRET`                 | `change-me` | ✔️ | HMAC-SHA512 token secret |
| `SPRING_MAIL_HOST`           | `smtp.postmarkapp.com` |   | SMTP server |
| `LOGGING_LEVEL_ROOT`         | `INFO` |   | Min log level |
| `STORAGE_PROVIDER`           | `s3` |   | One of: `local`, `s3`, `gcs` |

> 🔒 **Tip:** never place secrets in `application-*.yml`. Use Docker secrets, Kubernetes `Secret`, or HashiCorp Vault.

---

## 4  Database Migration (Flyway)

Database schema is versioned in `app/sprintcart-pro-core/src/main/resources/db/migration`.  
Migrations run on startup. To migrate manually:

```bash
mvn -pl app/sprintcart-pro-core flyway:migrate \
  -Dflyway.url=jdbc:postgresql://localhost/sprintcart \
  -Dflyway.user=sprintcart \
  -Dflyway.password=****
```

---

## 5  Running Locally (Docker Compose)

```yaml
# sprintcart-pro/deployments/docker-compose.yaml
version: "3.9"
services:
  db:
    image: postgres:14
    environment:
      POSTGRES_USER: sprintcart
      POSTGRES_PASSWORD: sprintcart
      POSTGRES_DB: sprintcart
    volumes:
      - db_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL","pg_isready -U sprintcart"]
      interval: 10s
      retries: 5

  app:
    image: ghcr.io/sprintcart/sprintcart-pro:1.8.2
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "8080:8080"
    environment:
      SPRING_DATASOURCE_URL: jdbc:postgresql://db:5432/sprintcart
      SPRING_DATASOURCE_USERNAME: sprintcart
      SPRING_DATASOURCE_PASSWORD: sprintcart
      JWT_SECRET: change-me
volumes:
  db_data:
```

Start:

```bash
docker compose up -d
open http://localhost:8080/
```

---

## 6  Kubernetes (Production)

### 6.1 Namespace & Secrets

```bash
kubectl create ns sprintcart
kubectl -n sprintcart create secret generic sprintcart-secrets \
  --from-literal=SPRING_DATASOURCE_URL=jdbc:postgresql://rds.aws.com:5432/sprintcart \
  --from-literal=SPRING_DATASOURCE_USERNAME=sprintcart \
  --from-literal=SPRING_DATASOURCE_PASSWORD=******** \
  --from-literal=JWT_SECRET=********
```

### 6.2 Deployment

```yaml
# sprintcart-pro/deployments/k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sprintcart
  namespace: sprintcart
spec:
  replicas: 3          # scale horizontally
  selector:
    matchLabels:
      app: sprintcart
  template:
    metadata:
      labels:
        app: sprintcart
    spec:
      terminationGracePeriodSeconds: 30
      containers:
        - name: app
          image: ghcr.io/sprintcart/sprintcart-pro:1.8.2
          resources:
            requests:
              cpu: "250m"
              memory: "512Mi"
            limits:
              cpu: "1000m"
              memory: "2Gi"
          envFrom:
            - secretRef:
                name: sprintcart-secrets
          ports:
            - containerPort: 8080
          livenessProbe:
            httpGet:
              path: /actuator/health/liveness
              port: 8080
            initialDelaySeconds: 30
            periodSeconds: 15
          readinessProbe:
            httpGet:
              path: /actuator/health/readiness
              port: 8080
            initialDelaySeconds: 10
            periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: sprintcart
  namespace: sprintcart
spec:
  selector:
    app: sprintcart
  ports:
    - port: 80
      targetPort: 8080
  type: ClusterIP
```

### 6.3 Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: sprintcart
  namespace: sprintcart
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  tls:
    - hosts:
        - shop.example.com
      secretName: sprintcart-tls
  rules:
    - host: shop.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: sprintcart
                port:
                  number: 80
```

---

## 7  Rolling Updates & Zero-Downtime

1. Use Kubernetes `Deployment` strategy `RollingUpdate` (default).  
2. Ensure the app exposes `/actuator/health/readiness`; pods won’t receive traffic until ready.  
3. Background tasks & scheduled jobs use database-level locks (`sp_lock_task`) to ensure at-most-once execution during rollouts.

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1
    maxUnavailable: 0
```

---

## 8  Observability

| Component | Technology | Location |
|-----------|------------|----------|
| Metrics   | Prometheus + Grafana | `/actuator/prometheus` endpoint |
| Logs      | Loki or Elastic Search | STDOUT JSON logs |
| Traces    | OpenTelemetry 1.29 | `OTEL_EXPORTER_OTLP_ENDPOINT` |

Attach sidecars or DaemonSets; no app change needed.

---

## 9  CI/CD with GitHub Actions

```yaml
# .github/workflows/pipeline.yml
name: Build & Deploy

on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up JDK 21
        uses: actions/setup-java@v4
        with:
          java-version: "21"
          distribution: "temurin"
          cache: "maven"

      - name: Build & Test
        run: mvn -B -Pprod clean verify

      - name: Build Image
        uses: docker/build-push-action@v5
        with:
          push: true
          tags: ghcr.io/sprintcart/sprintcart-pro:${{ github.sha }}

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment: production
    steps:
      - name: Configure kubectl
        uses: azure/setup-kubectl@v3
        with:
          version: "latest"

      - name: Deploy
        run: |
          kubectl set image deployment/sprintcart app=ghcr.io/sprintcart/sprintcart-pro:${{ github.sha }} -n sprintcart
          kubectl rollout status deployment/sprintcart -n sprintcart
```

---

## 10  Disaster Recovery

1. **Database Backups** – Use continuous WAL archiving (PostgreSQL) or vendor-provided point-in-time restore.  
2. **Object Storage** – Enable versioning (`S3`, `GCS`) for media uploads.  
3. **Container Registry** – Images are immutable; pin by digest.  
4. **Secrets** – Stored in Git-encrypted SOPS or Vault.

---

## 11  FAQ

**Q: What JVM options are recommended for high-traffic stores?**  
A: Start with `-Xms4g -Xmx4g -XX:+UseG1GC`; monitor GC pauses via `actuator/metrics/jvm.gc.pause`.

**Q: Can I use MySQL instead of PostgreSQL?**  
A: Not officially. Some domain logic relies on Postgres JSONB functions.

---

## 12  Support

• Slack #deployments  
• Email: devops@sprintcart.io  
• SLA: 4 business hours for production-impacting incidents.

---

© 2024 SprintCart LLC. All rights reserved.
```