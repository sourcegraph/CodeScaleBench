```markdown
# SprintCart Pro · Developer Setup Guide
Welcome to the SprintCart Pro code-base!  
This guide will walk you through getting a fully-featured development environment
up and running—backend, frontend, and all auxiliary services—within **15 minutes**.

---

## 1. Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| JDK 17 | ✅ | Tested with Temurin 17.0.8 |
| Maven 3.8+ | ✅ | Wrapper included (`./mvnw`) |
| Node 18 LTS | ✅ | Yarn 3 is bundled locally |
| Docker 24+  | ✅ | Compose v2 syntax |
| Git 2.40+   | ✅ | `git config --global core.autocrlf input` recommended |
| IDE | IntelliJ 2023.2 / VS Code 1.85 | Lombok & Annotation Processing enabled |

> ℹ️  SprintCart Pro uses **Hexagonal Architecture**; you can swap adapters
> without restarting the JVM.

---

## 2. Clone & Bootstrap

```bash
git clone https://github.com/sprintcart/sprintcart-pro.git
cd sprintcart-pro

# Pull large binaries (product images, Cypress fixtures, etc.)
git lfs install
git lfs pull
```

### 2.1. Spin-up Supporting Services

```bash
# Database (PostgreSQL 15), Redis, LocalStack (S3, SNS/SQS), Mailhog
docker compose -f infra/dev/docker-compose.yml up -d
```

Container status check:

```bash
docker compose ps
```

You should see something like:

```
NAME                 STATE   PORTS
postgres             Up      5432->5432/tcp
redis                Up      6379->6379/tcp
localstack           Up      4566->4566/tcp
mailhog              Up      8025->8025/tcp
```

---

## 3. Configure Your Environment

Copy the sample environment file and tweak as needed:

```bash
cp backend/src/main/resources/application-local.yml.example \
   backend/src/main/resources/application-local.yml
```

Key properties:

```yaml
spring:
  datasource:
    url: jdbc:postgresql://localhost:5432/sprintcart_pro
    username: scp_local
    password: scp_local_pw
  redis:
    host: localhost
    port: 6379
aws:
  s3:
    bucket: sprintcart-pro-dev
```

Environment-specific overrides live in:

```
backend/src/main/resources/
  ├── application.yml        # baseline config
  ├── application-local.yml  # local JVM override
  └── application-ci.yml     # GitHub Actions
```

---

## 4. Build & Run the Backend

```bash
# compile + run all checks
./mvnw clean verify

# start the Spring Boot API on port 8080
./mvnw -Pdev spring-boot:run
```

If everything works, `http://localhost:8080/actuator/health`
returns:

```json
{"status":"UP"}
```

### 4.1. Hot-reloading with JRebel / Spring DevTools
Simply enable *Build project automatically* in your IDE and attach the JRebel
agent; restart loops are sub-second.

---

## 5. Build & Run the Frontend (Vue 3)

```bash
# bootstrap node_modules via yarn-berry’s zero-install
cd frontend
yarn dev --port 5173
```

Navigate to `http://localhost:5173`.  
The Vite dev proxy forwards `/api/**` traffic to `http://localhost:8080`.

---

## 6. Database Migrations & Seed Data

SprintCart Pro ships with **Flyway** migrations.

```bash
./mvnw -pl backend -am flyway:migrate \
       -Dflyway.configFiles=infra/dev/flyway-local.conf
```

Add seed data:

```bash
psql -h localhost -U scp_local -d sprintcart_pro \
     -f infra/dev/seed/catalog_seed.sql
```

> ☕  Migrations automatically run on `spring-boot:run` if the profile is `dev`.

---

## 7. Writing Code — An Example Hex Adapter

Below is a production-grade example of an **Outbound Adapter** that posts order
events to Redis Streams. Feel free to use this as a template when adding new
integrations.

```java
package com.sprintcart.orders.infrastructure.redis;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sprintcart.orders.domain.event.OrderPlaced;
import com.sprintcart.shared.domain.EventPublisherPort;
import com.sprintcart.shared.domain.exceptions.SerializationException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.connection.stream.RecordId;
import org.springframework.data.redis.core.StreamOperations;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.util.Map;

@Slf4j
@Component
@RequiredArgsConstructor
public class RedisOrderEventPublisher implements EventPublisherPort<OrderPlaced> {

    private static final String STREAM_KEY = "scpro.order-events";
    private static final String TYPE_FIELD  = "type";
    private static final String PAYLOAD_FIELD = "payload";

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;

    @Override
    public void publish(OrderPlaced event) {
        StreamOperations<String, String, Map<String, String>> streamOps =
                redisTemplate.opsForStream();

        Map<String, String> msg = Map.of(
                TYPE_FIELD, event.getClass().getSimpleName(),
                PAYLOAD_FIELD, toJson(event)
        );

        RecordId recordId = streamOps.add(STREAM_KEY, msg);
        log.debug("Published OrderPlaced event {} to Redis stream {}", recordId, STREAM_KEY);
    }

    private String toJson(Object obj) {
        try {
            return objectMapper.writeValueAsString(obj);
        } catch (JsonProcessingException ex) {
            throw new SerializationException("Failed to serialize order event", ex);
        }
    }
}
```

Unit test:

```java
// src/test/java/.../RedisOrderEventPublisherTest.java
@ExtendWith(SpringExtension.class)
@ContextConfiguration(classes = {RedisTestConfig.class, RedisOrderEventPublisher.class})
class RedisOrderEventPublisherTest {
    @Autowired RedisOrderEventPublisher publisher;
    @Autowired StringRedisTemplate redis;

    @Test
    void shouldPublishEvent() {
        OrderPlaced evt = Fixtures.orderPlaced();
        publisher.publish(evt);

        List<MapRecord<String, String, String>> records =
            redis.opsForStream().read(StreamOffset.latest("scpro.order-events"));

        assertThat(records).isNotEmpty();
        assertThat(records.get(0).getValue()).containsEntry("type", "OrderPlaced");
    }
}
```

---

## 8. Run the Test-Suite

```bash
# Unit & integration tests (includes Testcontainers)
./mvnw verify

# Frontend unit tests
cd frontend
yarn test:unit

# End-to-end tests (Cypress)
yarn test:e2e
```

---

## 9. Building a Production Image

SprintCart Pro leverages **Jib** for reproducible OCI layers with zero Dockerfile
boilerplate.

```bash
./mvnw -pl backend -am jib:build \
       -Djib.to.image=ghcr.io/sprintcart/pro-backend:1.2.0
```

Frontend production build:

```bash
cd frontend
yarn build
docker build -t ghcr.io/sprintcart/pro-frontend:1.2.0 -f Dockerfile.prod .
```

Deploy the two images behind an Nginx gateway or your favorite orchestrator
(Kubernetes manifests are in `deploy/k8s/`).

---

## 10. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `address already in use :8080` | Another JVM is running. `lsof -i :8080 | kill` |
| `java.lang.NoClassDefFoundError: lombok` | Enable annotation processing & install Lombok in your IDE |
| Frontend cannot reach API | Verify `VITE_API_HOST` in `frontend/.env.local` |
| Docker “connection reset” on Windows | Switch to WSL 2 backend; disable VPN interference |

---

## 11. Next Steps

1. Read `docs/architecture/hexagonal_overview.md` for a deep dive into ports &
   adapters.
2. Explore code ownership with `CODEOWNERS` to find maintainers.
3. Join our Slack `#dev` channel and run `/onboard me` to gain commit access.

Happy shipping 🚀
```