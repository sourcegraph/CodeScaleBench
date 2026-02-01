```markdown
# PulseLearn Campus Hub – **web_social**

[![CI](https://github.com/pulselearn/campus-hub/actions/workflows/ci.yml/badge.svg)](https://github.com/pulselearn/campus-hub/actions/workflows/ci.yml)
[![Coverage Status](https://coveralls.io/repos/github/pulselearn/campus-hub/badge.svg?branch=main)](https://coveralls.io/github/pulselearn/campus-hub?branch=main)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

PulseLearn Campus Hub transforms any educational institution into a real-time digital campus.  
Students, teachers, and administrators collaborate through activity streams that react instantly to learning events such as lecture uploads, quiz completions, or peer-review feedback.  

<details>
<summary>Table of Contents</summary>

1. [Key Features](#key-features)  
2. [Architecture](#architecture)  
3. [Tech Stack](#tech-stack)  
4. [Getting Started](#getting-started)  
5. [Project Structure](#project-structure)  
6. [Domain Events](#domain-events--message-flow)  
7. [Security & Compliance](#security--compliance)  
8. [Scripts & Tooling](#scripts--tooling)  
9. [Contributing](#contributing)  
10. [License](#license)
</details>

---

## Key Features

| Category              | Highlights                                                                                           |
| --------------------- | ----------------------------------------------------------------------------------------------------- |
| Social Learning       | Cohort discussions, live tutoring rooms, activity feed, and gamified achievements                    |
| Realtime Events       | Event-driven micro-services orchestrated via Kafka/NATS                                              |
| Adaptive Content      | Personalized recommendations based on learner behavior & mastery maps                                |
| Admin Dashboard       | Live operational metrics, content moderation, role-based access control                              |
| Enterprise Grade      | SSL/TLS everywhere, granular session management, audit-ready logs, GDPR support                      |

---

## Architecture

```mermaid
flowchart LR
  subgraph Front-End (SPA)
    FE1[React <br/> Redux/RTK]
    FE2[Next.js SSR]
  end

  subgraph API Gateway
    GW[Node.js <br/> Express]
  end

  subgraph Micro-services
    AUTH[Auth Service]
    LEARN[Learning Service]
    FEED[Activity Feed]
    NOTIF[Notification]
    GAMIFY[Gamification]
    SEARCH[Search/Indexer]
  end

  subgraph Infra
    NATS[NATS JetStream]
    DB[(PostgreSQL Cluster)]
    CACHE[(Redis Cluster)]
    FS[(S3/MinIO)]
    ES[(OpenSearch)]
  end

  FE1 -- HTTPS --> GW
  FE2 -- HTTPS --> GW
  GW --> AUTH
  GW --> LEARN
  GW --> FEED

  AUTH <-->|events| NATS
  LEARN <-->|events| NATS
  FEED <-->|events| NATS
  NOTIF <-->|events| NATS
  GAMIFY <-->|events| NATS
  SEARCH <-->|events| NATS

  LEARN -- SQL --> DB
  AUTH -- SQL --> DB
  FEED -- SQL --> DB
  LEARN -- S3 --> FS
  SEARCH -- Index --> ES
  NOTIF -- Pub/Sub --> CACHE
```

Design patterns in play: **Service Layer**, **Repository**, **MVC Controllers**, **Domain Events**, **CQRS**, and **Outbox** pattern for transactional event publishing.

---

## Tech Stack

| Layer               | Tech                                                                                              |
| ------------------- | ------------------------------------------------------------------------------------------------- |
| Front-End           | React 18, Next.js 13, TypeScript, TailwindCSS, Socket.io                                         |
| API Gateway         | Node.js 20, Express 5.x, TypeScript, Zod (schema validation), Prisma ORM                          |
| Event Backbone      | NATS JetStream (prod) / Kafka (optional), Avro + Schema Registry                                 |
| Auth N Security     | OAuth 2.1, OpenID Connect, JWT (RS256), Passport.js, Argon2id                                     |
| Data Stores         | PostgreSQL 15, Redis 7 (sessions / pub-sub), OpenSearch 2.x (search & analytics)                  |
| Observability       | Prometheus, Grafana, OpenTelemetry, Jaeger, ELK                                                  |
| DevOps              | Docker Compose, Kubernetes Helm Charts, GitHub Actions CI/CD                                     |

---

## Getting Started

### Prerequisites

* Node.js ≥ 20
* Docker & Docker Compose ≥ v2.20
* `pnpm` (preferred) or `npm`
* Optional: `nats-server`, `kafka`, `psql` installed locally for bare-metal runs

### Quick Local Run (Docker)

```bash
git clone https://github.com/pulselearn/campus-hub.git
cd campus-hub

# Spin up DB, NATS, search, redis, and local MinIO
docker compose up -d infra

# Install dependencies
pnpm install --filter=./apps/web_social

# Start API Gateway + services
pnpm --filter @pulselearn/web_social run dev
```

Access web UI at `https://localhost:3000`, API at `https://localhost:4000/api`.

### Environment Variables

Create `.env` at project root (see `.env.example`):

```dotenv
DATABASE_URL=postgresql://plch_user:secret@localhost:5432/pulselearn
NATS_URI=nats://localhost:4222
JWT_ISSUER=https://pulselearn.dev
JWT_PRIVATE_KEY_PATH=./certs/jwt-private.pem
JWT_PUBLIC_KEY_PATH=./certs/jwt-public.pem
REDIS_URL=redis://localhost:6379
S3_ENDPOINT=http://localhost:9000
S3_ACCESS_KEY=minio
S3_SECRET_KEY=miniopass
```

---

## Project Structure

```
pulselearn-campus-hub/
├── apps/
│   ├── api-gateway/      # GraphQL + REST BFF
│   ├── web_social/       # Front-end SPA/SSR
│   ├── services/
│   │   ├── auth/
│   │   ├── learning/
│   │   ├── feed/
│   │   ├── gamification/
│   │   └── notifications/
│   └── …                 # other service domains
├── packages/
│   ├── config/           # shared tsconfig, eslint, prettier
│   ├── logger/           # pino + opentelemetry wrappers
│   ├── event-bus/        # NATS pub/sub client with Avro schemas
│   └── ui-kit/           # component library
└── infra/
    └── docker/           # compose, k8s manifests, helm charts
```

---

## Domain Events & Message Flow

Each domain action emits an immutable event.  
Events are versioned, schema-registered, and can be replayed for new projections.

| Event Name              | Payload (key fields)              | Trigger                          |
| ----------------------- | --------------------------------- | -------------------------------- |
| `AssignmentSubmitted`   | `assignmentId`, `userId`, `file`  | Student uploads assignment       |
| `BadgeAwarded`          | `badgeId`, `userId`, `reason`     | Gamification service decision    |
| `SessionExpired`        | `userId`, `expiresAt`             | Auth service TTL watcher         |
| `LectureUploaded`       | `lectureId`, `courseId`           | Instructor uploads lecture       |
| `CoursePaid`            | `orderId`, `userId`, `amount`     | Stripe webhook                   |

Example Avro schema:

```jsonc
{
  "namespace": "com.pulselearn.events",
  "type": "record",
  "name": "BadgeAwarded_v1",
  "fields": [
    { "name": "badgeId", "type": "string" },
    { "name": "userId",  "type": "string" },
    { "name": "reason",  "type": "string" },
    { "name": "awardedAt", "type": { "type": "long", "logicalType": "timestamp-millis" } }
  ]
}
```

---

## Security & Compliance

* TLS 1.3 enforced end-to-end (Let’s Encrypt in dev, ACM in prod)  
* Argon2id passwords, JWTs signed with 4096-bit RSA keys  
* OWASP Top-10 hardened (rate-limiting, input validation via Zod)  
* GDPR: Right-to-be-Forgotten endpoints, data export, opt-in analytics  
* Audit logs streamed to OpenSearch, immutable S3 with object locking  

---

## Scripts & Tooling

| Script                       | Purpose                                  |
| ---------------------------- | ---------------------------------------- |
| `pnpm dev`                   | Hot-reload dev server (nodemon + ts-node)|
| `pnpm build`                 | Compile TypeScript, bundle assets        |
| `pnpm test`                  | Run unit & integration tests             |
| `pnpm lint`                  | ESLint linting                           |
| `pnpm format`                | Prettier formatting                      |
| `docker compose up infra`    | Spin up databases & brokers              |
| `helm upgrade --install`     | Deploy to Kubernetes                     |

Continuous Integration is handled by GitHub Actions (`.github/workflows/ci.yml`) which runs:

1. Type checking  
2. ESLint + Prettier  
3. Jest with code coverage  
4. Container build & vulnerability scanning (Trivy)  

---

## Contributing

1. Fork the repo & create your feature branch (`git checkout -b feature/my-amazing-feature`)
2. Commit your changes (`git commit -am '✨ Add amazing feature'`)
3. Run `pnpm test && pnpm lint`
4. Push to the branch (`git push origin feature/my-amazing-feature`)
5. Open a Pull Request

Please read `CONTRIBUTING.md` and `CODE_OF_CONDUCT.md` for details.

---

## License

PulseLearn Campus Hub is released under the MIT License – see the [LICENSE](LICENSE) file for details.
```