```markdown
# AgoraPulse JavaScript / TypeScript SDK – API Reference  
_Last updated: 2023-11-30_

AgoraPulse turns raw social-network fire-hoses into actionable, real-time intelligence.  
This document describes the public JavaScript / TypeScript surface used by **web,
Node, and edge runtimes** to ingest events, consume enriched streams, register &
serve models, and monitor production performance.

---

## Installation

```bash
# Yarn
yarn add @agorapulse/sdk rxjs kafkajs zod

# npm
npm i @agorapulse/sdk rxjs kafkajs zod
```

---

## Quick-Start (15 Lines)

```ts
import { AgoraPulseClient, DomEvent, models } from '@agorapulse/sdk';

const client = new AgoraPulseClient({
  kafkaBrokers: ['kafka-broker.agora:9092'],
  authToken: process.env.AGORA_TOKEN!,
});

// 1️⃣  Ingest a tweet                                                                              
await client.ingest({
  type: DomEvent.Type.Tweet,
  payload: { id: '160011', text: '🚀 LFG #Web3', userId: '99' },
});

// 2️⃣  Subscribe to real-time sentiment                                                           
client.sentiment$
  .byUser('99')
  .subscribe(console.log);

// 3️⃣  Hot-swap a model version                                                                   
await models.activate('sentiment', 'v2023-11-29-fa439ad');
```

---

## High-Level Architecture

```
┌───────────┐  Kafka  ┌───────────────┐   RxJS    ┌────────────┐            
│ Ingestor  ├────────►│ FeatureStore  ├──────────►│  Pipelines │            
└───────────┘         └───────────────┘           └────┬───────┘            
                                          ┌───────────▼───────────┐        
                                          │  Model Serving Layer  │        
                                          └───────────┬───────────┘        
                                                      ▼                    
                                           Web / Node / Edge Client        
```

---

## Core Namespaces

| Namespace                | Responsibility                                 |
|--------------------------|-----------------------------------------------|
| `AgClient`               | Auth, config, connection pooling              |
| `ingest`, `emit`         | Push domain events                            |
| `streams` (`sentiment$`) | RxJS Observables for real-time features       |
| `models`                 | Registry, hot-swap, A/B routing               |
| `monitoring`             | Drift & fairness alerts                       |

---

## API Surface

### 1. Constructor: `new AgoraPulseClient(options)`

| option              | type                       | default                     |
|---------------------|----------------------------|-----------------------------|
| `kafkaBrokers`      | `string[]`                 | `['localhost:9092']`        |
| `authToken`         | `string` (🚨 required)     | —                           |
| `logLevel`          | `'info' \| 'debug'`        | `'info'`                    |
| `observability`     | `Partial<OpenTelemetry>`   | auto instrumented           |
| `featureStoreCache` | `{ttl: number, size: number}` | `{ttl: 30_000, size: 10k}` |

```ts
const client = new AgoraPulseClient({
  kafkaBrokers: ['k1:9092', 'k2:9092'],
  authToken: process.env.AGORA_TOKEN,
  logLevel: 'debug',
});
```

---

### 2. Event Ingestion

`client.ingest(event: DomEvent): Promise<void>`

```ts
import { DomEvent } from '@agorapulse/sdk/schema';

/** Fires when a user reacts with an emoji burst inside a live stream. */
const emojiEvent: DomEvent = {
  type: DomEvent.Type.EmojiBurst,
  at: Date.now(),
  payload: {
    messageId: 'a1b2',
    emoji: '🔥',
    userId: 'u007',
    streamId: 's77',
  },
};

await client.ingest(emojiEvent);
```

Under the hood:
1. Validated by `zod`.
2. Marshalled to Avro.
3. Posted to Kafka topic `dom.events.v1`.
4. Retries w/ back-off (50 ms → 4 s).
5. Emits local metrics (`events_ingested_total`).

---

### 3. Reactive Streams

All real-time features are served via cold RxJS Observables.  
Each stream is _multicast_ with a replay buffer of 1 to prevent missed frames.

#### 3.1 Sentiment
```ts
import { filters } from '@agorapulse/sdk';

client.sentiment$
  .pipe(filters.byLanguage('en'), filters.aboveConfidence(0.7))
  .subscribe(({ messageId, score }) => {
    console.log(`🧠 ${messageId} -> ${score}`);
  });
```

#### 3.2 Micro-Topics
```ts
client.topicCluster$
  .latest()
  .subscribe(cluster => {
    ui.renderWordcloud(cluster.keywords);
  });
```

#### 3.3 Toxicity Alerts
```ts
client.toxicity$
  .byCommunity('crypto-degenerates')
  .subscribe(alert => pagerDuty.trigger(alert));
```

---

### 4. Model Management

```ts
import { models } from '@agorapulse/sdk';

// List all versions
const versions = await models.list('sentiment');

/*
versions = [
  { id: 'v2023-11-29-fa439ad', metrics: {F1:0.91}, stage:'staging' },
  { id: 'v2023-11-14-c1d3a8f', metrics: {F1:0.89}, stage:'prod' },
]
*/

// Promote canary to production
await models.promote('sentiment', 'v2023-11-29-fa439ad');

// Rollback (in <10 ms thanks to event sourcing)
await models.activate('sentiment', 'v2023-11-14-c1d3a8f');
```

Behind the scenes, a domain event
`ModelVersionActivated` is published, atomically updating the routing table that
Kafka Streams uses to fan-out inference requests.

---

### 5. Monitoring & Drift Detection

```ts
import { monitoring } from '@agorapulse/sdk';

/**
 * Subscribe to any fairness regression on our toxicity classifier.
 * E.g. flagging higher toxicity for dialect 'AAVE' than 'General American'.
 */
monitoring.drift$
  .byModel('toxicity')
  .severity('high')
  .subscribe(alert => slack.post('#ml-alerts', alert));
```

Default thresholds are derived from the last 30-minute baseline,
configurable via the admin UI or:

```ts
await monitoring.setThreshold({
  model: 'toxicity',
  metric: 'false_negative_rate',
  delta: 0.02,
  direction: 'increase',
});
```

---

## HTTP/GraphQL Edge API

While WebSockets/Kafka are preferred for real-time,
serverless functions often rely on HTTP.

### 5.1 REST

`GET /v1/features/:messageId`

```http
GET /v1/features/a1b2
Authorization: Bearer <token>

200 OK
Content-Type: application/json
{
  "sentiment": {
    "score": 0.87,
    "label": "positive"
  },
  "toxicity": {
    "score": 0.02,
    "label": "clean"
  },
  "topics": ["web3", "nft", "launch"]
}
```

### 5.2 GraphQL

```graphql
query FeatureSet($id: ID!) {
  feature(id: $id) {
    sentiment {
      score
      label
    }
    toxicity {
      score
      label
    }
  }
}
```

---

## Error Handling

Every async call returns an `AgoraResult<T>` union:

```ts
type AgoraResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: AgoraError };

interface AgoraError extends Error {
  code:
    | 'AUTH_INVALID_TOKEN'
    | 'KAFKA_UNAVAILABLE'
    | 'EVENT_VALIDATION_FAILED'
    | 'MODEL_NOT_FOUND'
    | 'RATE_LIMIT';
  retryable: boolean;
}
```

Example:

```ts
const res = await client.safe.ingest(event);

if (!res.ok) {
  if (res.error.retryable) queue.retry(event);
  else logger.error(res.error);
}
```

---

## Type Definitions (excerpt)

```ts
/** Domain Events driving the pipeline */
export namespace DomEvent {
  /* eslint-disable @typescript-eslint/ban-types */
  export enum Type {
    Tweet            = 'tweet',
    Like             = 'like',
    EmojiBurst       = 'emoji_burst',
    SpacesUtterance  = 'spaces_utterance',
    LiveCaption      = 'live_caption',
  }

  export interface Base<T extends Type, P extends object> {
    id?: string;        // auto-generated UUID v4 if absent
    type: T;
    at: number;         // unix epoch millis
    payload: P;
  }

  // Concrete specializations
  export type Tweet = Base<Type.Tweet, {
    id: string;
    text: string;
    userId: string;
    lang?: string;
  }>;
  /* … */
}
/* eslint-enable */

/** Reactive stream helpers */
export interface Sentiment {
  messageId: string;
  score: number;   // −1 … 1
  label: 'negative' | 'neutral' | 'positive';
  confidence: number;
}
```

---

## Configuration File (`agorapulse.config.ts`)

```ts
import { defineConfig } from '@agorapulse/sdk';

export default defineConfig({
  auth: {
    token: process.env.AGORA_TOKEN!,
    // Staging cluster by default
    endpoint: 'https://staging.api.agorapulse.ai',
  },
  ingest: {
    batchSize: 500,
    flushInterval: 250, // ms
  },
  features: {
    languages: ['en', 'es', 'fr'],
  },
});
```

Load via:

```ts
import { loadConfig } from '@agorapulse/sdk';
const cfg = await loadConfig();
```

---

## CLI Cheat-Sheet

```bash
# Tail sentiment stream
agorapulse tail --sentiment

# Promote a model
agorapulse model promote sentiment v2023-11-29-fa439ad

# Generate OpenAPI client
agorapulse sdk openapi https://api.agorapulse.ai/openapi.yaml --lang ts
```

---

## Contributing

1. Create a feature branch (`git checkout -b feat/my-stream`).
2. Run `pnpm test:watch`.
3. Submit a PR; CI will run TypeDoc + eslint + integration tests.
4. A maintainer merges & auto-publishes via semantic-release.

---

© AgoraPulse ML/NLP 2023 – All rights reserved.
```