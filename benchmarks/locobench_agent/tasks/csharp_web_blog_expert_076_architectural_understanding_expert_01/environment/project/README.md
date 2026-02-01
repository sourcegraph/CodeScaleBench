```markdown
# TempoScribe Pro – Hexagonal Productivity Blog Suite

[![.NET](https://img.shields.io/badge/.NET-8.0-blue.svg)](https://dotnet.microsoft.com/)
[![CI](https://github.com/TempoScribe/TempoScribePro/actions/workflows/ci.yml/badge.svg)](https://github.com/TempoScribe/TempoScribePro/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=TempoScribe_Pro&metric=coverage)](https://sonarcloud.io/summary/new_code?id=TempoScribe_Pro)

> **TempoScribe Pro** is a high-throughput, premium blogging platform engineered around **time-to-publish**.  
> Modular hexagonal boundaries enable contributors to iterate on infrastructure, UI, and monetization without rewriting the domain or breaking editor workflows.

---

## ✨ Key Capabilities
| Category                      | Highlights                                                                                                  |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Publishing & Workflow         | Scheduled/recurring posts, editorial Kanban, AI-assisted drafts, multi-author collaboration                 |
| Monetization                  | Stripe-powered premium posts, tiered subscriptions, promo codes, pay-per-view                               |
| Analytics & Insight           | Realtime authorship dashboard, latency heatmaps, snapshot performance exporter                              |
| Search & Discovery            | Semantic search shortcuts, bulk tagging, full-text indexing                                                 |
| DevOps & Observability        | OpenTelemetry, NATS event bus hooks, Grafana dashboards, self-healing background workers                    |
| Extensibility                 | Ports & Adapters wiring for SQL, NoSQL, GraphQL, Message Bus, or alternative payment provider               |

---

## 🗂 Solution Layout

```
TempoScribePro/
│
├─ src/
│   ├─ Domain/                    # Pure business logic (technology-agnostic)
│   │   ├─ Entities/              # Post, Comment, WorkSession, EditorialTask, MonetizationRule
│   │   ├─ ValueObjects/
│   │   ├─ Services/              # Domain services
│   │   └─ SharedKernel/
│   ├─ Application/               # Application layer (use-cases) – orchestrates domain + ports
│   ├─ Infrastructure/            # Adapters (SQL, Redis, Stripe, IdentityServer, ...)
│   ├─ Web/                       # MVC + REST controllers (ASP.NET Core 8.0)
│   └─ Worker/                    # Background jobs, scheduled tasks
│
├─ tests/                         # xUnit + FluentAssertions
│
└─ docs/                          # Architecture decision records, sequence diagrams
```

> **Hexagonal Rule**  
> _“Nothing in `Domain` depends on a framework, database, or UI.  
> Everything else depends **on** the `Domain`.”_

---

## 🔌 Ports & Adapters Cheat-Sheet

| Layer          | Port Type        | Interface                                          | Default Adapter                                   |
| -------------- | ---------------- | -------------------------------------------------- | ------------------------------------------------- |
| Application    | **Repository**   | `IPostRepository`, `IEditorialTaskRepository`      | `EfPostRepository` (SQL Server via EF Core)       |
|                | **Service**      | `IPaymentGateway`                                  | `StripeGatewayAdapter`                            |
|                | **Bus**          | `IDomainEventPublisher`                            | `NatsEventPublisher`                              |
| Infrastructure | **Cache**        | `IAppCache`                                        | `RedisCacheAdapter`                               |
| Web            | **Auth**         | `IIdentityProvider`                                | `IdentityServer4Adapter`                          |

---

## 🚀 Getting Started

### Prerequisites
* .NET 8.0 SDK
* Docker (Compose V2)
* Node 18 + PNPM (only for Blazor WASM frontend)
* Local TLS root certificate (dev-only)

### Clone & Bootstrap

```bash
git clone https://github.com/TempoScribe/TempoScribePro.git
cd TempoScribePro
./build.ps1 init         # powershell – installs git hooks & tools
# or ./build.sh init     # bash
```

### Spin Up Full Stack

```bash
docker compose -f infra/docker-compose.yml up -d
dotnet run --project src/Web/TempoScribePro.Web
```

*Browse http://localhost:5000/admin with default credentials `admin@tempo.dev` / `Pass@word1`.*

### Run Tests

```bash
dotnet test
```

Coverage reports land in `./artifacts/coverage`.

---

## 🧩 Sample Usage

```csharp
// Application layer – Schedule a new post
public sealed class SchedulePostHandler
{
    private readonly IPostRepository _posts;
    private readonly IClock _clock;
    private readonly ILogger<SchedulePostHandler> _logger;

    public SchedulePostHandler(IPostRepository posts, IClock clock, ILogger<SchedulePostHandler> logger)
    {
        _posts  = posts  ?? throw new ArgumentNullException(nameof(posts));
        _clock  = clock  ?? throw new ArgumentNullException(nameof(clock));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
    }

    public async Task<PostId> HandleAsync(SchedulePost request, CancellationToken ct = default)
    {
        var post = Post.Draft(
            title: request.Title,
            body:  request.Markdown,
            authorId: request.AuthorId);

        post.ScheduleFor(_clock.UtcNow + request.Delay);
        await _posts.InsertAsync(post, ct);

        _logger.LogInformation("Post {PostId} scheduled for {PublishDate}", post.Id, post.PublishAt);
        return post.Id;
    }
}
```

---

## 🌐 API

OpenAPI spec is generated at runtime and reachable at:

```
GET /swagger/v1/swagger.json
```

Example endpoints:

| Verb | Path                     | Capability                |
| ---- | ------------------------ | ------------------------- |
| GET  | `/api/posts/{slug}`      | Fetch published post      |
| POST | `/api/posts`             | Create draft              |
| POST | `/api/payments/session`  | Stripe checkout session   |
| GET  | `/api/admin/snapshots`   | Performance metrics       |

> For GraphQL clients point to `/graphql`. Playground available in dev profile.

---

## 🛠️ Build & Deployment

CI pipeline (GitHub Actions):

1. Restore → Build → Test → Static Analysis (SonarCloud)
2. Docker Compose build (multi-arch)
3. Helm chart packaging → Publish to GHCR

Production deployment targets AKS but any Kubernetes cluster works:

```bash
helm repo add temposcribe https://tempo.s3.amazonaws.com/charts
helm upgrade --install blog temposcribe/temposcribe-pro \
  --namespace blog --create-namespace
```

---

## 🔐 Security Policy

* Report vulnerabilities to **security@temposcribe.com** (24-hour SLA)
* Critical findings patched within **72 hours** and hot-fixed to supported N-2 versions
* See [SECURITY.md](./SECURITY.md) for full policy & supported versions

---

## 💡 Roadmap (Q3-Q4 2024)

- [x] AI-powered draft assistant (GPT-4)
- [ ] Live collaborative editing (CRDT)
- [ ] Edge cache invalidation plug-in (Cloudflare Workers)
- [ ] In-app micro-course monetization

---

## 🤝 Contributing

1. Fork → Feature branch → PR targeting `dev`
2. Include unit + integration tests, adhere to **.editorconfig**
3. Sign **CLA** (auto-prompted by bot)

### Commit Message Conventions

```
feat(domain): introduce WorkSession aggregate
fix(web): sanitize markdown to prevent XSS
refactor(infrastructure): switch redis client to IDistributedCache
```

---

## 📄 License

Licensed under the **MIT License** – see [LICENSE](LICENSE) for details.

---

> Built with ❤️, caffeine ☕, and an unhealthy obsession with _throughput_.
```