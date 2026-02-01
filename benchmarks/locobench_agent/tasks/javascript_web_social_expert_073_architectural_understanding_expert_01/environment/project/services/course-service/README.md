```markdown
# 📚 PulseLearn Campus Hub – Course Service

The **Course Service** is a stateless, event-driven micro-service that owns the **Course** aggregate in the PulseLearn ecosystem.  
Its responsibilities include:

* CRUD life-cycle of courses, modules, and lessons
* Cohort enrolment & role management (student / instructor / TA)
* Publishing domain events (`CourseCreated`, `ModuleUpdated`, `EnrollmentRevoked`, …)
* Consuming cross-cutting events (e.g., `UserDeleted`, `PaymentCaptured`)
* Exposing a REST/JSON API for the web/mobile front-ends
* Persisting data in PostgreSQL via Prisma ORM
* Emitting real-time WebSocket updates to subscribed clients (via the Gateway)

> TL;DR — **The Course Service is the single source of truth for all course metadata in PulseLearn.**


---

## ✨ Quick Start

```bash
# 1. Install dependencies
pnpm i

# 2. Start PostgreSQL & NATS dev stack (via docker-compose)
pnpm docker:up

# 3. Run DB migrations & seed fixtures
pnpm db:migrate   # => prisma migrate deploy
pnpm db:seed      # => prisma db seed

# 4. Start the micro-service
pnpm dev
```

The service boots on `http://localhost:5001` (REST) and connects to NATS at `nats://localhost:4222` by default.

---

## 🗂️ Folder Structure
```
services/
└─ course-service/
   ├─ src/
   │  ├─ api/               # Express routers & OpenAPI docs
   │  ├─ domain/            # Entities, aggregates, domain logic
   │  ├─ events/            # NATS publishers/subscribers
   │  ├─ prisma/            # Prisma schema & migrations
   │  ├─ services/          # Application services (Service Layer)
   │  └─ utils/             # Shared helpers & middlewares
   ├─ tests/                # Jest tests (unit + integration)
   ├─ Dockerfile
   ├─ docker-compose.yml
   ├─ .env.example
   └─ README.md             # ← You are here
```

---

## 🛠️ Environment Variables

Copy `.env.example` to `.env` and adjust as needed:

```
# HTTP
PORT=5001

# Postgres
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/pulselearn_courses

# NATS
NATS_URL=nats://localhost:4222
NATS_CLUSTER_ID=pulselearn
NATS_CLIENT_ID=course-svc-${RANDOM}

# JWT
JWT_PUBLIC_KEY_PATH=../../certs/jwt_public.pem
```

⚠️ **Never** commit secrets. Use a secrets manager (Vault, AWS Secrets Manager, …) in production.

---

## 🧩 API Reference

### Base URL
`/api/v1/courses`

### Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET    | `/` | List courses (paginated) | Optional |
| GET    | `/:courseId` | Get single course | Optional |
| POST   | `/` | Create new course | Instructor |
| PATCH  | `/:courseId` | Update course | Instructor (owner) |
| DELETE | `/:courseId` | Soft-delete course | Admin / Instructor |
| POST   | `/:courseId/enroll` | Enroll user | Authenticated |
| DELETE | `/:courseId/enroll/:userId` | Remove enrollment | Instructor / Admin |

Full OpenAPI 3 schema lives under `src/api/openapi.yaml` and is served at `/docs` (Swagger UI).

---

## 🗄️ Data Model (Prisma)

```prisma
model Course {
  id          String    @id @default(cuid())
  title       String
  description String
  thumbnail   String?    @db.VarChar(2048)
  visibility  Visibility @default(PUBLIC)
  modules     Module[]
  ownerId     String
  owner       User       @relation(fields: [ownerId], references: [id])
  enrollments Enrollment[]
  createdAt   DateTime   @default(now())
  updatedAt   DateTime   @updatedAt
}
```

See `schema.prisma` for the full ERD.

---

## 📣 Domain Events

| Event | Payload | Published On | Consumers |
|-------|---------|--------------|-----------|
| `CourseCreated` | `courseId`, `ownerId` | after successful POST `/` | Achievement Svc, Search Indexer |
| `CourseDeleted` | `courseId`, `softDelete` | DELETE endpoint | Notification Svc |
| `EnrollmentAdded` | `courseId`, `userId`, `role` | when a user enrolls | Notification Svc, Gamification Svc |
| `EnrollmentRemoved` | `courseId`, `userId` | on unenroll | Notification Svc |

All events are JSON-encoded and published over NATS Streaming (JetStream in prod).

---

## 🏗️ Sample Usage (Frontend)

```js
import axios from 'axios';
import { getAuthToken } from '@/lib/auth';

export async function createCourse(form) {
  const { data } = await axios.post(
    '/api/v1/courses',
    {
      title: form.title,
      description: form.description,
      thumbnail: form.thumbnailUrl,
      visibility: 'PRIVATE',
    },
    {
      headers: {
        Authorization: `Bearer ${getAuthToken()}`,
      },
    },
  );

  return data; // => { courseId: 'cjx...', ... }
}
```

---

## 🧑‍💻 Development Scripts (pnpm)

| Script | Description |
|--------|-------------|
| `dev` | Run service in watch-mode (ts-node / nodemon) |
| `build` | Compile TypeScript & bundle for production |
| `start` | Start compiled JavaScript |
| `test` | Jest unit + integration tests |
| `lint` | ESLint + Prettier fix |
| `docker:up` | Spin up Postgres & NATS via docker-compose |
| `docker:down` | Stop and remove containers |
| `db:migrate` | Apply Prisma migrations |
| `db:seed` | Seed dev data |

---

## ✅ Testing Strategy

1. **Unit Tests** – Pure functions, domain logic – run in CI on every PR.  
2. **Integration Tests** – Spawns an ephemeral Postgres DB (via `docker-compose -p test`).  
3. **Contract Tests** – Pact JS ensures consumers (front-end) respect the OpenAPI spec.  

Run all locally:

```bash
pnpm test           # jest --runInBand
pnpm test:watch
```

---

## 🚀 Deployment

* **CI**: GitHub Actions  
* **CD**: Argo CD deploys Helm chart to Kubernetes  
* **Observability**: Winston > Logstash > Kibana, Prometheus metrics exposed on `/metrics`  

K8s readiness/liveness probes hit `/healthz` and `/readyz`.  

---

## ⚠️ Gotchas

* Publishing events before DB commit may lead to lost messages. We use the **Transactional Outbox** pattern to guarantee atomicity.
* Large cohort imports should be processed via the **Bulk Enroll** endpoint (`/api/v1/courses/:id/enroll/bulk`) which streams CSV rows.
* **Idempotency-Key** header is required on all mutating requests to avoid duplicate transactions.

---

## 🤝 Contributing

1. Fork & clone
2. `pnpm i`
3. Create a branch `feat/your-feature`
4. Commit using Conventional Commits (`feat:`, `fix:` …)
5. Open PR against `dev` branch

All PRs require:
* Passing CI checks
* At least one code review
* Updated docs/tests

---

## 📝 License
MIT © 2024 PulseLearn, Inc.
```
