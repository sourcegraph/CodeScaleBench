```markdown
# PaletteStream ETL Canvas  
## Deployment Guide

This document describes **end-to-end deployment** of the PaletteStream ETL Canvas across the following environments:

* Local developer workstation (Docker Compose)
* Preview / QA (single-node Kubernetes via `kind`)
* Production (managed Kubernetes: AKS / EKS / GKE)
* Disaster-recovery strategy (multi-region cold-stand-by)

> NOTE  
> All shell commands assume **bash/zsh**. Replace `$(pwd)` and `${VAR}` syntax accordingly if you are on Powershell or Fish.

---

## 1. Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| .NET SDK | 8.0 LTS | Build & run micro-services |
| Docker | 24.x | Local container execution |
| kubectl | ≥ 1.28 | Cluster management |
| Helm | ≥ 3.12 | Manifest templating |
| kind (optional) | ≥ 0.20 | Local single-node k8s |
| PostgreSQL | 15 | Metadata repository |
| Kafka | 3.x | Event streaming backbone |
| Azure CLI / AWS CLI (optional) | current | Cloud provisioning |

---

## 2. Environment Variables

The ETL micro-services share a **strongly-typed** configuration contract defined in  
`data_etl/Shared/Options/InfrastructureOptions.cs`.

```csharp
namespace PaletteStream.ETL.Shared.Options;

/// <summary>
/// Infrastructure wide settings.  Values are resolved via:
/// 1. appsettings*.json
/// 2. Environment variables (e.g. Canvas__Kafka__BootstrapServers)
/// 3. Secret providers (Azure KeyVault, AWS Secrets Manager, Hashicorp Vault)
/// </summary>
public sealed record InfrastructureOptions
{
    public required KafkaOptions Kafka { get; init; }
    public required PostgresOptions Postgres { get; init; }
    public required MonitoringOptions Monitoring { get; init; }
}

public sealed record KafkaOptions
{
    public required string BootstrapServers { get; init; }
    public required string SchemaRegistryUrl { get; init; }
    public required string Username { get; init; }
    public required string Password { get; init; }
}

public sealed record PostgresOptions
{
    public required string Host { get; init; }
    public required int Port { get; init; } = 5432;
    public required string Database { get; init; }
    public required string Username { get; init; }
    public required string Password { get; init; }
}

public sealed record MonitoringOptions
{
    public required string PrometheusEndpoint { get; init; }
    public required string GrafanaUrl { get; init; }
}
```

### 2.1 Minimal `.env`

```env
# Kafka
CANVAS__KAFKA__BOOTSTRAPSERVERS=kafka:29092
CANVAS__KAFKA__SCHEMAREGISTRYURL=http://schema-registry:8081
CANVAS__KAFKA__USERNAME=kafka_user
CANVAS__KAFKA__PASSWORD=change_me

# Postgres
CANVAS__POSTGRES__HOST=postgres
CANVAS__POSTGRES__DATABASE=palette_stream
CANVAS__POSTGRES__USERNAME=etl
CANVAS__POSTGRES__PASSWORD=secret

# Monitoring
CANVAS__MONITORING__PROMETHEUSENDPOINT=http://prometheus:9090
CANVAS__MONITORING__GRAFANAURL=http://grafana:3000
```

---

## 3. Local Development (Docker Compose)

Spin up all dependencies plus a single ETL instance.

```bash
docker compose -f docker-compose.local.yml up --build
```

File: `docker-compose.local.yml`

```yaml
version: "3.9"

services:
  etl-api:
    build:
      context: ..
      dockerfile: ./src/PaletteStream.ETL.Api/Dockerfile
    env_file:
      - ../.env
    ports:
      - "8080:8080"
    depends_on:
      - kafka
      - postgres

  kafka:
    image: confluentinc/cp-kafka:7.5.0
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:29092
    ports:
      - "29092:29092"
    depends_on:
      - zookeeper

  zookeeper:
    image: confluentinc/cp-zookeeper:7.5.0
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: palette_stream
      POSTGRES_USER: etl
      POSTGRES_PASSWORD: secret
    ports:
      - "5432:5432"

  prometheus:
    image: prom/prometheus:v2.47.0
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana:10.1.0
    ports:
      - "3000:3000"
```

### 3.1 Hot-Reload

```bash
dotnet watch --project src/PaletteStream.ETL.Api run
```

> All micro-services reference a shared `Directory.Build.props` file which optimizes build times and enforces Roslyn analyzers.

---

## 4. Database Migrations

The solution uses **EF Core** migrations that run automatically on startup if  
`--schema-migrate` is passed (see Program.cs snippet below).

```bash
dotnet run --project src/PaletteStream.ETL.Api --schema-migrate
```

```csharp
// Program.cs (excerpt)
public static class Program
{
    public static async Task Main(string[] args)
    {
        var host = CreateHostBuilder(args).Build();

        if (args.Contains("--schema-migrate", StringComparer.OrdinalIgnoreCase))
        {
            using var scope = host.Services.CreateScope();
            var dbContext = scope.ServiceProvider.GetRequiredService<CanvasDbContext>();
            await dbContext.Database.MigrateAsync();
        }

        await host.RunAsync();
    }

    // omitted for brevity …
}
```

---

## 5. Kubernetes Deployment

### 5.1 Local cluster (`kind`)

```bash
kind create cluster --name ps-etl --image kindest/node:v1.28.0
```

Load Docker images into the kind cluster:

```bash
kind load docker-image palettestream/etl-api:local --name ps-etl
```

### 5.2 Helm chart values

File: `deploy/helm/values.yaml`

```yaml
replicaCount: 3

image:
  repository: ghcr.io/palettestream/etl-api
  tag: "1.4.7"
  pullPolicy: IfNotPresent

service:
  type: ClusterIP
  port: 8080

resources:
  limits:
    cpu: "1000m"
    memory: "1024Mi"
  requests:
    cpu: "250m"
    memory: "128Mi"

env:
  - name: CANVAS__KAFKA__BOOTSTRAPSERVERS
    value: "kafka.kafka:9092"
  - name: CANVAS__POSTGRES__HOST
    value: "postgres.database.svc.cluster.local"
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: "http://otel-collector:4317"

autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 10
  targetCPUUtilizationPercentage: 60
```

Install/upgrade release:

```bash
helm upgrade --install etl-canvas ./deploy/helm -n data-etl --create-namespace
```

### 5.3 Blue/Green strategy

The Helm chart exposes a `deploymentStrategy` value.  
Set to `Recreate` for simple environments or to `BlueGreen` for zero-downtime:

```yaml
deploymentStrategy:
  type: BlueGreen
  greenServiceName: etl-canvas-green
  activeServiceName: etl-canvas
```

During upgrade Helm automatically provisions two ReplicaSets (`blue` + `green`)
and toggles the service selector when readiness probes succeed.

---

## 6. Observability

### 6.1 OpenTelemetry

All services ship traces & metrics via the .NET `OpenTelemetry` SDK.

```csharp
builder.Services.AddOpenTelemetry()
    .WithTracing(tracer => tracer
        .AddSource("PaletteStream.*")
        .AddAspNetCoreInstrumentation()
        .AddGrpcClientInstrumentation()
        .SetResourceBuilder(ResourceBuilder
            .CreateDefault()
            .AddService("palette-stream-etl")))
    .WithMetrics(metrics => metrics
        .AddRuntimeInstrumentation()
        .AddPrometheusExporter());
```

### 6.2 Prometheus & Grafana

Prometheus scrapes the `/metrics` endpoint, automatically exposed by  
`PrometheusExporter`. Grafana dashboards are provisioned using JSON models
under `deploy/monitoring/grafana/dashboards`.

---

## 7. CI / CD Pipeline

Below is a truncated GitHub Actions workflow demonstrating the critical stages.

```yaml
name: CI/CD

on:
  push:
    branches: [main]
  pull_request:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up .NET
        uses: actions/setup-dotnet@v4
        with:
          dotnet-version: "8.0.x"
      - name: Build
        run: dotnet build --configuration Release
      - name: Run unit tests
        run: dotnet test --configuration Release --no-build

  docker:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          push: true
          tags: ghcr.io/palettestream/etl-api:${{ github.sha }}

  deploy:
    needs: docker
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: azure/setup-helm@v4
        with:
          version: v3.12.3
      - name: Helm upgrade
        run: |
          helm upgrade --install etl-canvas \
            ./deploy/helm \
            --namespace data-etl \
            --set image.tag=${{ github.sha }}
```

---

## 8. Disaster Recovery

1. PostgreSQL WAL logs streamed to **cloud object storage** (S3/Blob).  
2. Kafka replicated via **MirrorMaker 2** to secondary region.  
3. Nightly Helm release manifests + secrets exported to **Git-tagged** artifacts.  
4. `terraform apply` stands up a *cold* DR cluster in ≤ 15 min.

---

## 9. Security Hardening Checklist

- [x] All containers run as **non-root** user.
- [x] `seccomp` & `AppArmor` profiles bundled with Helm chart.
- [x] TLS enforced (mTLS between micro-services via Linkerd).  
- [x] OWASP Dependency-Check integrated in CI.  
- [x] Secrets exclusively mounted via CSI driver (`azure-keyvault-secrets`).  

---

## 10. Troubleshooting

| Symptom | Resolution |
|---------|------------|
| `System.Net.Sockets.SocketException` when connecting to Kafka | Verify `CANVAS__KAFKA__BOOTSTRAPSERVERS` resolves inside the container (`nslookup kafka`). |
| HTTP 503 after Helm upgrade | Ensure readiness probe (`/health/ready`) succeeds; check pod logs for `MigrationException`. |
| High p99 latency on enrichment stage | Enable **ComputeSharp** GPU path (`--enable-gpu`) and verify GPU node pool autoscaler. |

---

## 11. Additional Resources

* Architecture Decision Records: [`/docs/adr`](../adr)
* Coding guidelines: [`/docs/contributing.md`](../contributing.md)
* SLA & SLO definitions: [`/docs/slo`](../slo)

---

Happy Painting! 🎨🖌️
```