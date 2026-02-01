```markdown
# PulseSphere SocialOps – System Monitoring  
`docs/api.md` – v1.4.0 (2024-06-10)  

> Production-grade reference of the **System Monitoring** domain service exposed by the **PulseSphere SocialOps** platform.  
> All examples are **TypeScript 5.x** compliant and leverage `fetch`/`WebSocket` native APIs.  

---

## Table of Contents

1.  Quick-Start
2.  Service Endpoints
    - REST
    - WebSocket Live-Feed
3.  Event-Driven Topics (Kafka / NATS)
4.  Data Models (TypeScript)
5.  Error Handling & Problem Details
6.  Security & Authentication
7.  Rate Limits
8.  TypeScript Client SDK
9.  CLI Usage
10. Change Log

---

## 1. Quick-Start

```bash
# Retrieve the latest 5-minute system metrics window
curl -H "Authorization: Bearer ${TOKEN}" \
     https://api.pulsesphere.io/monitoring/v1/metrics?window=5m
```

```typescript
import { MonitoringClient } from "@pulsesphere/socialops-sdk";

const client = new MonitoringClient({ token: process.env.TOKEN! });

const cpu = await client.metrics.getCurrentWindow({ window: "5m" });
console.log(cpu.avgUsage);          // ⇒ 38.42
console.log(cpu.socialHeatIndex);   // ⇒ 0.82
```

---

## 2. Service Endpoints

### Base URL

```
https://api.pulsesphere.io/monitoring/v1
```

All requests **must** be HTTPS and include `Authorization: Bearer <JWT>` header.

---

### 2.1 `GET /metrics`

Retrieves aggregated infrastructure metrics, enriched with real-time social signals.

| Query Param | Type          | Required | Description                                             |
|-------------|---------------|----------|---------------------------------------------------------|
| `window`    | `string`      | No       | ISO-8601 duration → `PT5M`, `15m`, `1h` (default `5m`)  |
| `since`     | `Instant`     | No       | Start timestamp (RFC3339). Mutually exclusive with `window` |
| `tags`      | `string[]`    | No       | Filter by custom tags (`db`, `cdn`, `redis`)            |

**Response** → `200 OK`

```jsonc
{
  "window": "PT5M",
  "generatedAt": "2024-06-10T12:30:04.000Z",
  "metrics": [
    {
      "name": "cpu_usage",
      "avg": 38.42,
      "p95": 69.02,
      "socialHeatIndex": 0.82,
      "unit": "percent"
    },
    {
      "name": "request_latency",
      "avg": 84.3,
      "p95": 210.1,
      "socialHeatIndex": 0.82,
      "unit": "milliseconds"
    }
  ]
}
```

| Status | Meaning                     | `application/problem+json` payload |
|--------|-----------------------------|-------------------------------------|
| `400`  | Invalid query parameters    | `type: "https://docs.pulsesphere.io/problems/validation"` |
| `401`  | Missing / expired JWT       | `type: "https://docs.pulsesphere.io/problems/auth"` |
| `429`  | Rate-limit exceeded         | see Rate Limits section             |
| `5xx`  | Server error                | —                                   |


---

### 2.2 `POST /alerts`

Creates or updates **dynamic** alerting rules.

```http
POST /alerts HTTP/1.1
Content-Type: application/json
Authorization: Bearer <JWT>
```

```jsonc
{
  "id": "hot-cache-miss",
  "expr": "cache_miss_rate > 0.05 && socialHeatIndex > 0.7",
  "severity": "high",
  "notify": ["pagerduty", "slack"],
  "snoozeUntil": null
}
```

| Field       | Type            | Rules                                |
|-------------|-----------------|--------------------------------------|
| `id`        | `string`        | Unique kebab-case                    |
| `expr`      | `string (CEL)`  | Common Expression Language           |
| `severity`  | `"low" \| "medium" \| "high" \| "critical"` |
| `notify`    | `string[]`      | Channels registered in User Profile  |
| `snoozeUntil` | `Instant \| null` | UTC timestamp to suppress alerts |

**Response** → `201 Created`

```json
{ "id": "hot-cache-miss", "status": "active" }
```

---

### 2.3 `PATCH /config`

Upserts runtime configuration (feature flags, thresholds, service mesh knobs).

```jsonc
{
  "path": "ingress.lb.maxConnections",
  "op": "replace",
  "value": 25000,
  "correlationId": "fa7db6c5-e984-4a0e-b97e-f1d57a8dd409"
}
```

**Idempotent**: safe for retries.

---

### 2.4 `POST /backup` & `POST /recovery`

Long-running operations executed asynchronously. Respond with `202 Accepted` + Operation Id that can be polled.

---

### 2.5 `/ws/live`

Bidirectional WebSocket stream for low-latency metrics and sentiment deltas (~500 ms).

```typescript
const ws = new WebSocket("wss://api.pulsesphere.io/monitoring/v1/ws/live?auth=" + token);

ws.onmessage = e => {
  const msg = JSON.parse(e.data) as LiveMetricPacket;
  if (msg.kind === "heartbeat") return;
  console.table(msg.payload.samples);
};
```

---

## 3. Event-Driven Topics

| Topic                                   | Broker | Key Schema                      | Value Schema                    |
|-----------------------------------------|--------|---------------------------------|---------------------------------|
| `telemetry.metrics.system`              | Kafka  | `clusterId:string`              | `SystemMetricEnvelope`          |
| `telemetry.social.heat_index`           | NATS   | `user_segment:string`           | `SocialHeatEnvelope`            |
| `ops.alerts.triggered`                  | Kafka  | `alertId:string`                | `AlertFiredEvent`               |
| `ops.backup.lifecycle`                  | NATS   | `operationId:uuid`              | `BackupLifecycleEvent`          |

All schemas are versioned with **Schema Registry** (Avro + JSON Schema). Backward compat reqs: *MUST NOT* remove fields, *SHOULD* add with defaults.

---

## 4. Data Models (generated from `@pulsesphere/schemas@2.x`)

```typescript
// Metrics ------------------------------------------------------------
export interface MetricSample {
  name: string;           // e.g., "cpu_usage"
  avg: number;            // mean over window
  p95: number;            // 95th percentile
  socialHeatIndex: number;// 0..1
  unit: "percent" | "bytes" | "milliseconds";
}

export interface MetricWindow {
  window: string;            // ISO-8601 duration
  generatedAt: string;       // RFC3339 UTC stamp
  metrics: MetricSample[];
}

// Alerts -------------------------------------------------------------
export interface AlertRule {
  id: string;
  expr: string; // CEL
  severity: "low" | "medium" | "high" | "critical";
  notify: string[];
  snoozeUntil: string | null;
}

// WebSocket ----------------------------------------------------------
export type LiveMetricPacket =
  | { kind: "heartbeat"; ts: string }
  | { kind: "metric"; payload: MetricWindow };
```

---

## 5. Error Handling & Problem Details

All non-2xx responses follow [RFC 7807](https://datatracker.ietf.org/doc/html/rfc7807).

```jsonc
{
  "type": "https://docs.pulsesphere.io/problems/validation",
  "title": "Invalid query parameter",
  "status": 400,
  "detail": "window must be positive duration",
  "instance": "/metrics?window=-5m",
  "correlationId": "09bf41a1-6bd0-4f62-af1e-862239e7dfd7"
}
```

Include `X-Correlation-Id` header on all requests to ease distributed tracing. Mirror returned by server.

---

## 6. Security & Authentication

- OAuth 2.1 / OIDC → obtain JWT (RS256) with scope `socialops.monitoring.*`.
- JWT **must** include:
  - `sub` (user id)
  - `iat`, `exp`
  - `permissions` claim (`read_metrics`, `manage_alerts`, …)

**mTLS** enforced inside Service Mesh – user-facing traffic only requires TLS.

---

## 7. Rate Limits

| Tier        | RPM | Burst | Headers Exposed                  |
|-------------|-----|-------|----------------------------------|
| Free-Trial  | 600 | 100   | `X-RateLimit-Remaining`, `Retry-After` |
| Pro         | 3 000 | 500 | —                                |
| Enterprise  | 10 000 | 1 500 | —                              |

429 response body is RFC 7807 (see §5).

---

## 8. TypeScript Client SDK

```typescript
/* eslint-disable @typescript-eslint/no-exp-licit-any */
import { MetricWindow, AlertRule } from "./types";
import { buildUrl, safeFetch } from "./utils";

/**
 * MonitoringClient – thin wrapper around PulseSphere REST API.
 */
export class MonitoringClient {
  constructor(private readonly opts: { token: string; baseUrl?: string } ) {
    this.baseUrl = opts.baseUrl ?? "https://api.pulsesphere.io/monitoring/v1";
  }

  private readonly baseUrl: string;

  /** GET /metrics */
  async getMetricWindow(params: { window?: string; since?: string; tags?: string[] } = {}): Promise<MetricWindow> {
    const url = buildUrl(`${this.baseUrl}/metrics`, params);
    return safeFetch<MetricWindow>(url, { headers: this.headers });
  }

  /** POST /alerts */
  async upsertAlert(rule: AlertRule): Promise<{ id: string; status: string }> {
    return safeFetch(`${this.baseUrl}/alerts`, {
      method: "POST",
      headers: { ...this.headers, "Content-Type": "application/json" },
      body: JSON.stringify(rule),
    });
  }

  private get headers() {
    return { Authorization: `Bearer ${this.opts.token}` };
  }
}
```

`buildUrl` and `safeFetch` perform query-string serialization and automatic 4xx/5xx mapping to `ProblemDetailsError` (custom Error class).

---

## 9. CLI Usage

PulseSphere ships a binary `psphere` built with **Oclif**.

```
psphere metrics get --window 15m --json
psphere alerts create hot-cache-miss --expr "..." --severity high
psphere backup start --target prod-cluster-a
```

Docs: `psphere <command> --help`.

---

## 10. Change Log (excerpt)

| Version | Date       | Notes                                      |
|---------|------------|--------------------------------------------|
| 1.4.0   | 2024-06-10 | Added `socialHeatIndex` to `/metrics` API. |
| 1.3.0   | 2024-05-18 | WebSocket heartbeat packets every 5 s.     |
| 1.2.0   | 2024-04-07 | Asynchronous Backup/Recovery endpoints.    |
| 1.0.0   | 2024-02-01 | GA launch.                                 |

---

*© 2024 PulseSphere Inc. – All rights reserved.*
```