```markdown
# ADR-002: Introduce Event Sourcing with Kafka

* Status: **Accepted**  
* Date: 2024-05-13  
* Decision Makers: Core Platform Team (PulseLearn Campus Hub)  
* Supersedes: *N/A*  
* References: PCH-RFC-11, ADR-001 (Adopt Micro-Service Architecture)  

---

## 1. Context ‑ Why change?

PulseLearn Campus Hub (PCH) is experiencing rapid feature growth:

* Real-time dashboards for quiz progress, peer-review feedback, and badge awards  
* A new gamification engine that recalculates points on every learning event  
* Audit-ready reporting for compliance and accreditation bodies  

The existing CRUD-centric model has hit several limits:

| Pain-Point                          | Symptom                                                                             |
|------------------------------------|-------------------------------------------------------------------------------------|
| Data-coupling                       | Multiple bounded contexts write to the same tables, causing noisy merge conflicts. |
| Missed notifications                | Lost WebSocket messages because they were dispatched directly from HTTP handlers.   |
| Operational complexity              | Replaying history (e.g., to debug ranking errors) requires fragile SQL scripts.     |
| Lack of temporal data               | Hard to answer “What was Alice’s score at 14:01 yesterday?”                         |

To address these, we want:

1. **Immutable event log** – the single source of truth  
2. **Replayability** – rebuild read-models at any point in time  
3. **Loose coupling** – services subscribe to what they need, when they need it  
4. **Scalability** – horizontal partitioning of event streams  

Apache **Kafka** is already used in our data-analytics pipeline; adopting it as the system event backbone is a natural next step.

---

## 2. Decision

We will adopt **event sourcing** for all new domain workflows and gradually migrate existing ones.  
Kafka will act as the **persistent event store** (commit log) and **message bus**.  
Specifics:

1. **Each bounded context owns its topic(s)** – e.g. `education.assignment`, `identity.session`, `gamification.badge`.
2. **Events are immutable** JSON messages, versioned via a `schemaVersion` field; schema registry enforced at the gateway.
3. **Append-only**: write operations emit events; read models are derived via consumer projections.
4. **Exactly-once** semantics: achieved by Kafka idempotent producers + transactional writes to outbox tables when necessary.
5. **Snapshot strategy**: Long-lived aggregates publish `*.snapshot` events every *n* revisions to shorten replay time.
6. **Backward compatibility**: Services must ignore unknown fields and can only add optional fields to existing event versions.

---

## 3. Consequences

Positive:

* **Auditability** – every state change is traceable.  
* **Resilience** – consumers can restart and replay without data loss.  
* **Scalable read models** – each service builds its own query-optimized projection.  

Negative / Trade-offs:

* **Write complexity** – commands must succeed or be compensated by new events.  
* **Learning curve** – developers must understand eventual consistency.  
* **Storage cost** – Kafka cluster size grows with retained history.  

---

## 4. Implementation Sketch (JavaScript / Node.js)

Below are cut-down excerpts from production code to guide contributors.  
All examples assume Node.js ≥ 18, TypeScript, and the `kafkajs` client.

### 4.1 Common Infrastructure

```ts
// src/infrastructure/kafka/kafkaClient.ts
import { Kafka, logLevel } from 'kafkajs';
import config from '../../config';

export const kafka = new Kafka({
  clientId: 'pulselearn-campus-hub',
  brokers : config.kafka.brokers,
  ssl     : true,
  sasl    : {
    mechanism : 'scram-sha-256',
    username  : config.kafka.username,
    password  : config.kafka.password,
  },
  logLevel: logLevel.WARN,
});

export function topicName(boundedContext: string, suffix = ''): string {
  return `${config.env}.${boundedContext}${suffix && `.${suffix}`}`;
}
```

### 4.2 Event Contracts

```ts
// src/domain/events/AssignmentSubmittedEvent.ts
import { z } from 'zod';

export const AssignmentSubmittedEventSchema = z.object({
  schemaVersion  : z.literal(1),
  eventId        : z.string().uuid(),
  aggregateId    : z.string().uuid(),   // Assignment ID
  type           : z.literal('AssignmentSubmitted'),
  occurredAt     : z.string().datetime({ offset: true }),
  payload        : z.object({
    courseId  : z.string().uuid(),
    studentId : z.string().uuid(),
    fileUrl   : z.string().url(),
  }),
});

export type AssignmentSubmittedEvent = z.infer<typeof AssignmentSubmittedEventSchema>;
```

### 4.3 Producer (Command Handler -> Event)

```ts
// src/application/commands/submitAssignment.ts
import { AssignmentSubmittedEvent } from '../../domain/events/AssignmentSubmittedEvent';
import { kafka, topicName } from '../../infrastructure/kafka/kafkaClient';
import { randomUUID } from 'crypto';

export async function submitAssignment(cmd: {
  courseId: string;
  studentId: string;
  fileUrl: string;
}): Promise<void> {
  // Business validation omitted for brevity

  const event: AssignmentSubmittedEvent = {
    schemaVersion : 1,
    eventId       : randomUUID(),
    aggregateId   : randomUUID(),
    type          : 'AssignmentSubmitted',
    occurredAt    : new Date().toISOString(),
    payload       : cmd,
  };

  const producer = kafka.producer({ idempotent: true });
  await producer.connect();

  try {
    await producer.send({
      topic: topicName('education.assignment'),
      messages: [
        {
          key  : event.aggregateId,
          value: JSON.stringify(event),
          headers: {
            'schema-version': '1',
            'event-type'    : event.type,
          },
        },
      ],
    });
  } finally {
    await producer.disconnect();
  }
}
```

### 4.4 Consumer Projection (Gamification Points)

```ts
// src/projections/gamification/pointsProjector.ts
import { kafka, topicName } from '../../infrastructure/kafka/kafkaClient';
import { AssignmentSubmittedEventSchema } from '../../domain/events/AssignmentSubmittedEvent';
import pointsRepo from '../../repositories/pointsRepository';

export async function runPointsProjector(): Promise<void> {
  const consumer = kafka.consumer({
    groupId: 'gamification-points-projector-v1',
  });

  await consumer.connect();
  await consumer.subscribe({
    topic: topicName('education.assignment'),
    fromBeginning: false,
  });

  await consumer.run({
    eachMessage: async ({ message, partition }) => {
      try {
        const raw = message.value?.toString() ?? '{}';
        const parsed = AssignmentSubmittedEventSchema.parse(JSON.parse(raw));

        await pointsRepo.increment(
          parsed.payload.studentId,
          /* points = */ 5,
        );

        console.info(
          `[PointProjector] +5 for student=${parsed.payload.studentId} (partition=${partition})`,
        );
      } catch (err) {
        // DLQ or retry logic could be implemented here
        console.error('[PointProjector] Failed to process message', err);
      }
    },
  });
}
```

### 4.5 Snapshotter Utility

```ts
// src/utils/snapshotter.ts
import { kafka, topicName } from '../infrastructure/kafka/kafkaClient';

export async function publishSnapshot<T>({
  boundedContext,
  aggregateName,
  aggregateId,
  revision,
  state,
}: {
  boundedContext: string;
  aggregateName: string;
  aggregateId: string;
  revision: number;
  state: T;
}): Promise<void> {
  const producer = kafka.producer();

  await producer.connect();
  try {
    await producer.send({
      topic: topicName(`${boundedContext}.${aggregateName}.snapshot`),
      messages: [
        {
          key  : aggregateId,
          value: JSON.stringify({
            schemaVersion: 1,
            type         : `${aggregateName}.snapshot`,
            revision,
            occurredAt   : new Date().toISOString(),
            state,
          }),
        },
      ],
    });
  } finally {
    await producer.disconnect();
  }
}
```

---

## 5. Migration Path

1. **Brown-field integration**: legacy CRUD modules will emit events in a “change-data-capture” style, then slowly migrate command handling logic.  
2. **Feature toggles**: Read models behind `/v2/` API routes will use event projections; `/v1/` remains on relational reads.  
3. **Runbook & SRE**: New runbooks added for Kafka cluster monitoring (Lag, ISR, Disk usage).  
4. **Developer enablement**: Internal workshop + “Event Sourcing 101” wiki page.  

---

## 6. Rejected Alternatives

* **RabbitMQ + Outbox pattern** – flexible routing but lacks strong log-compaction and replay features.  
* **Full CQRS without Event Sourcing** – improves reads but doesn’t solve auditability or temporal requirements.  

---

## 7. Open Issues / Next Steps

1. Define retention policy per topic (regulatory requirement: 5-year minimum).  
2. Agree on company-wide naming convention for events (`<Domain>.<Action><PastTense>`).  
3. Evaluate Confluent Schema Registry vs. open-source alternatives.  
4. Prototype snapshotting performance with 1M-event aggregate.  

---

> “If you treat data as immutable facts, your systems become a chronicle of truth, not just a reflection of the present.” –  Tech Lead, PCH
```