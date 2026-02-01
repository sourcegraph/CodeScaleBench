```markdown
# PulseLearn Campus Hub • Event Schema Registry Guide
_Last updated: 2024-05-17_

This guide documents how **PulseLearn Campus Hub** publishes, registers, and validates domain-events across our real-time architecture.  
All micro-services—regardless of language—must comply with these conventions to ensure forward- and backward-compatibility, stable contracts, and zero-downtime deploys.

---

## Table of contents
1. Motivation  
2. Event naming convention  
3. Directory layout  
4. JSON Schema specification  
5. JavaScript helpers (`@pulselearn/event-schema`)  
6. Producing events with validation  
7. Consuming events with type-safe payloads  
8. CLI utilities  
9. Versioning & deprecation strategy  

---

## 1  Motivation

A single typo in an event payload can silently break notifications, gamification, or billing.  
A central but **git-versioned** registry gives us:

* Compile-time (TS) & runtime (Ajv) validation
* Schema evolution with semantic versioning
* Automatic documentation generation
* Language-agnostic contracts (JS/TS, Go, Python, Kotlin)

---

## 2  Event naming convention

```
<BoundedContext>.<Aggregate>.<Action>.<v{MAJOR}>
```

Example: `Learning.Assignment.Submitted.v1`

* `BoundedContext` – top-level domain (Learning, Identity, Billing, Gamification, Infra)  
* `Aggregate` – entity triggering the event  
* `Action` – action in _Past Tense_  
* `v{MAJOR}` – **breaking** changes only. Minor/patch updates are handled inside the schema’s `version` field.

---

## 3  Directory layout

```
/event-schemas
  └─ learning
     └─ assignment
        ├─ submitted
        │  ├─ v1.schema.json
        │  └─ v1.example.json
        └─ graded
           └─ v1.schema.json
```

TIP: Consumers can import schemas directly from the package to avoid duplication:

```js
import AssignmentSubmittedV1 from '@pulselearn/event-schemas/learning/assignment/submitted/v1.schema.json';
```

---

## 4  JSON Schema specification (excerpt)

```jsonc
// event-schemas/learning/assignment/submitted/v1.schema.json
{
  "$id": "https://schemas.pulselearn.io/learning.assignment.submitted.v1",
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Learning.Assignment.Submitted.v1",
  "description": "Emitted when a student uploads an assignment.",
  "type": "object",
  "required": ["metadata", "data"],
  "additionalProperties": false,

  "properties": {
    "metadata": {
      "type": "object",
      "required": ["eventId", "occurredAt", "correlationId", "schemaRef", "version"],
      "properties": {
        "eventId":     { "type": "string", "format": "uuid" },
        "occurredAt":  { "type": "string", "format": "date-time" },
        "correlationId": { "type": "string", "format": "uuid" },
        "schemaRef":   { "const": "learning.assignment.submitted.v1" },
        "version":     { "type": "string", "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+$" }
      },
      "additionalProperties": false
    },

    "data": {
      "type": "object",
      "required": ["assignmentId", "courseId", "studentId", "fileUrl"],
      "properties": {
        "assignmentId": { "type": "string", "format": "uuid" },
        "courseId":     { "type": "string", "format": "uuid" },
        "studentId":    { "type": "string", "format": "uuid" },
        "fileUrl":      { "type": "string", "format": "uri" },
        "submittedAt":  { "type": "string", "format": "date-time" }
      },
      "additionalProperties": false
    }
  }
}
```

---

## 5  JavaScript helpers (`@pulselearn/event-schema`)

A thin wrapper around **Ajv** v8 shipped as an internal package.

```ts
// packages/event-schema/src/index.ts
import path from 'node:path';
import fs   from 'node:fs/promises';
import Ajv, { ValidateFunction } from 'ajv';
import addFormats from 'ajv-formats';
import { fileURLToPath } from 'node:url';

/**
 * Singleton AJV instance shared across producers / consumers.
 */
const ajv = new Ajv({ strict: true, allErrors: true });
addFormats(ajv);

/**
 * Cache of compiled validators.
 */
const registry: Record<string, ValidateFunction> = Object.create(null);

/**
 * Load & compile a JSON schema from the event-schemas directory.
 * @param schemaRef e.g. "learning.assignment.submitted.v1"
 */
export async function getValidator(schemaRef: string): Promise<ValidateFunction> {
  if (registry[schemaRef]) return registry[schemaRef];

  // Resolve absolute file path
  const baseDir = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    '../../event-schemas',
  );
  const parts   = schemaRef.split('.');
  const file    = path.join(baseDir, ...parts.slice(0, -1), `${parts.at(-1)}.schema.json`);

  let raw: Buffer;
  try {
    raw = await fs.readFile(file);
  } catch (err) {
    throw new Error(`Schema not found for ref "${schemaRef}" at ${file}`);
  }

  const schema = JSON.parse(raw.toString());
  const validate = ajv.compile(schema);
  registry[schemaRef] = validate;
  return validate;
}

/**
 * Validate an event payload at runtime and throw a descriptive error.
 */
export async function assertValid(schemaRef: string, payload: unknown): Promise<void> {
  const validate = await getValidator(schemaRef);
  const ok = validate(payload);
  if (!ok) {
    const messages = validate.errors?.map(e => `${e.instancePath} ${e.message}`).join('; ');
    throw new Error(`Schema validation failed for "${schemaRef}": ${messages}`);
  }
}
```

Publish as an npm workspace package so any service can:

```ts
import { assertValid } from '@pulselearn/event-schema';
await assertValid('learning.assignment.submitted.v1', myEventPayload);
```

---

## 6  Producing events with validation

```ts
// services/learning/src/producers/assignmentProducer.ts
import { Kafka, logLevel, CompressionTypes } from 'kafkajs';
import { assertValid } from '@pulselearn/event-schema';
import { v4 as uuid } from 'uuid';

const kafka = new Kafka({
  brokers: process.env.KAFKA_BROKERS!.split(','),
  clientId: 'learning-service',
  logLevel: logLevel.ERROR,
});

const producer = kafka.producer();

/**
 * Emit Learning.Assignment.Submitted.v1
 */
export async function emitAssignmentSubmitted({
  assignmentId,
  courseId,
  studentId,
  fileUrl,
  submittedAt = new Date().toISOString(),
}: {
  assignmentId: string;
  courseId: string;
  studentId: string;
  fileUrl: string;
  submittedAt?: string;
}) {
  const payload = {
    metadata: {
      eventId: uuid(),
      correlationId: uuid(), // forwarded if exists
      occurredAt: submittedAt,
      schemaRef: 'learning.assignment.submitted.v1',
      version: '1.0.0',
    },
    data: {
      assignmentId,
      courseId,
      studentId,
      fileUrl,
      submittedAt,
    },
  };

  // 1 validate against JSON schema
  await assertValid('learning.assignment.submitted.v1', payload);

  // 2 publish to Kafka
  await producer.connect(); // no-op if already connected
  await producer.send({
    topic: 'learning.assignment',
    messages: [
      {
        key: assignmentId,
        value: JSON.stringify(payload),
        compression: CompressionTypes.GZIP,
        headers: {
          'pulselearn-schema-ref': payload.metadata.schemaRef,
          'pulselearn-version':    payload.metadata.version,
        },
      },
    ],
  });
}
```

Error handling: the service layer wraps `emitAssignmentSubmitted` in a circuit-breaker (see `@pulselearn/lib-circuit`) so that downstream tasks like grading auto-retries.

---

## 7  Consuming events with type-safe payloads

```ts
// services/gamification/src/consumers/assignmentConsumer.ts
import { Kafka } from 'kafkajs';
import { assertValid } from '@pulselearn/event-schema';

const kafka = new Kafka({ brokers: process.env.KAFKA_BROKERS!.split(','), clientId: 'gamification' });
const consumer = kafka.consumer({ groupId: 'gamification.assignment' });

await consumer.connect();
await consumer.subscribe({ topic: 'learning.assignment', fromBeginning: false });

await consumer.run({
  eachMessage: async ({ message }) => {
    const schemaRef = message.headers?.['pulselearn-schema-ref']?.toString() ?? '';
    const payload   = JSON.parse(message.value!.toString());

    try {
      await assertValid(schemaRef, payload);
    } catch (err) {
      console.error('🛑 Invalid event, committing offset but skipping processing', err);
      // forward to dead-letter topic …
      return;
    }

    // Business logic: award "Early Bird" badge if student submits before deadline
    const { studentId, submittedAt } = payload.data;
    await maybeAwardEarlyBirdBadge(studentId, submittedAt);
  },
});
```

---

## 8  CLI utilities

`pnpm schema:check learning.assignment.submitted.v1 ./payload.json`

```ts
// tools/schema-cli.ts
#!/usr/bin/env node
import { readFile } from 'node:fs/promises';
import { assertValid } from '@pulselearn/event-schema';

(async () => {
  const [schemaRef, file] = process.argv.slice(2);
  if (!schemaRef || !file) {
    console.error('Usage: schema:check <schemaRef> <payload.json>');
    process.exit(1);
  }
  try {
    const json = JSON.parse(await readFile(file, 'utf-8'));
    await assertValid(schemaRef, json);
    console.log('✅  Payload is valid!');
  } catch (err) {
    console.error('❌  Validation failed:', (err as Error).message);
    process.exit(2);
  }
})();
```

Add `"schema:check": "ts-node tools/schema-cli.ts"` to the monorepo root `package.json`.

---

## 9  Versioning & deprecation

1. **Patch** (`x.y.PATCH`): typo fix or doc update — _no runtime impact_.  
2. **Minor** (`x.MINOR.z`): additive, non-breaking (new optional property).  
3. **Major** (`MAJOR.y.z` or `v2` directory): property removal or renamed field.

A consumer **must**:

* Handle an unknown `schemaRef` gracefully (skip & log).  
* Use a dead-letter topic `*.DLQ` for messages that fail validation.  

A producer **must**:

* Bump **only** minor version when adding optional fields.  
* Announce major changes on the `#engineering-broadcast` Slack channel at least _one week_ before merge to `main`.

> NOTE: Once a schema version is marked **Deprecated**, the producing service has 30 days to stop emitting it.

---

Happy coding & may your events always validate!  
_— PulseLearn Engineering_
```