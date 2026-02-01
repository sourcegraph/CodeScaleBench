```markdown
# LedgerLink Nexus API (v1)
Ultra-reliable, multi-tenant financial reconciliation microservice  
© 2024 LedgerLink Inc. • All rights reserved

---

## Table of Contents
1. Getting Started
2. Versioning Strategy
3. Authentication & Authorization
4. Error Handling Contract
5. REST Endpoints
   - Ledger Entries
   - Account Snapshots
   - Cash-Flow Forecasts
6. GraphQL Endpoint
7. Pagination & Caching
8. Rate Limiting
9. Observability & Tracing
10. Changelog (v1.x)

---

## 1. Getting Started
Base URL (production):

```
https://api.ledgerlink.io
```

Sandbox (free tier):

```
https://sandbox.ledgerlink.io
```

All requests **must** be served over HTTPS. HTTP requests return `426 Upgrade Required`.

---

## 2. Versioning Strategy
LedgerLink Nexus follows a _media-type driven_ versioning model.

```
Accept: application/vnd.ledgerlink.v1+json
```

Major version bumps are announced 90 days in advance via status page and in the `X-Deprecation` header.

---

## 3. Authentication & Authorization
Nexus supports two authentication flows:

1. OAuth 2.1 Client Credentials (recommended)  
2. Long-lived Service Tokens (legacy)

Include the token in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

Scopes map one-to-one with CQRS command/query capabilities:

| Scope                   | Grants                                       |
|-------------------------|----------------------------------------------|
| `ledgers:read`          | List / fetch ledger entries                  |
| `ledgers:write`         | Create / update ledger entries               |
| `accounts:read`         | Account snapshots & cash-flow forecasts      |
| `webhooks:manage`       | Register, pause, delete webhooks             |

A token with insufficient scopes returns:

```
HTTP/1.1 403 Forbidden
Ledger-Error-Code: AUTH_SCOPE_INSUFFICIENT
```

---

## 4. Error Handling Contract
LedgerLink uses structured JSON error envelopes inspired by RFC 7807.

```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "Amount must be greater than zero",
    "details": [
      {
        "field": "amount",
        "issue": "must_be_positive"
      }
    ],
    "correlation_id": "2d501f96-e65b-4b93-a7c8-a7269f30a8ea",
    "timestamp": "2024-05-05T08:17:21.155Z"
  }
}
```

| HTTP Status | Code Prefix        | Layer                       |
|-------------|-------------------|-----------------------------|
| 4xx         | VALIDATION / AUTH | Request validation, auth    |
| 5xx         | INTERNAL          | Service / DB / Upstream     |

---

## 5. REST Endpoints

### 5.1 Ledger Entries

#### 5.1.1 List Entries
```
GET /v1/ledgers/entries
```

Query parameters:

| Name          | Type   | Description                                    |
|---------------|--------|------------------------------------------------|
| `account_id`  | UUID   | Filter by account                              |
| `from_date`   | date   | Inclusive start (ISO-8601)                     |
| `to_date`     | date   | Inclusive end (ISO-8601)                       |
| `page[size]`  | int    | Items per page (default: 100, max: 1000)       |
| `page[cursor]`| string | Cursor returned by previous call               |

Example:

```bash
curl -H "Accept: application/vnd.ledgerlink.v1+json" \
     -H "Authorization: Bearer $TOKEN" \
     "https://api.ledgerlink.io/v1/ledgers/entries?account_id=ef83914f-4b2b-4ea5-9d38-38d79f5e70bc&page[size]=50"
```

Successful response (`200 OK`):

```json
{
  "data": [
    {
      "entry_id": "2e862563-37f7-4b9e-a55b-5f55fb8028b8",
      "account_id": "ef83914f-4b2b-4ea5-9d38-38d79f5e70bc",
      "amount": 1542.25,
      "currency": "USD",
      "direction": "DEBIT",
      "posting_date": "2024-04-30",
      "description": "Invoice 45602",
      "external_ref": "ERP#45602",
      "created_at": "2024-04-30T12:34:42.125Z",
      "updated_at": "2024-04-30T12:34:42.125Z"
    }
    // ...
  ],
  "meta": {
    "page": {
      "has_next": true,
      "next_cursor": "g3QAAAACZAACaWRtAAAAPGU4"
    },
    "cache": {
      "etag": "W/\"67d32bca9\"",
      "max_age_seconds": 30
    }
  }
}
```

Servers MAY return the `ETag` header. Supplying `If-None-Match` will trigger a `304 Not Modified`.

#### 5.1.2 Create Entry
```
POST /v1/ledgers/entries
Content-Type: application/json
```

```json
{
  "account_id": "ef83914f-4b2b-4ea5-9d38-38d79f5e70bc",
  "amount": 1542.25,
  "currency": "USD",
  "direction": "DEBIT",
  "posting_date": "2024-04-30",
  "description": "Invoice 45602",
  "external_ref": "ERP#45602"
}
```

Validation rules enforced by the View-Model:

* `amount > 0`
* `currency` conforms to ISO 4217
* `posting_date` ≤ current date
* `external_ref` ≤ 100 characters (UTF-8)

On success (`201 Created`) the response body matches GET by ID.

#### 5.1.3 Retrieve Entry
```
GET /v1/ledgers/entries/{entry_id}
```

Returns `404 Not Found` when the entry does not exist or tenant mismatch.

#### 5.1.4 Update Entry
```
PATCH /v1/ledgers/entries/{entry_id}
Content-Type: application/merge-patch+json
```

Immutable fields (`entry_id`, `account_id`, `currency`, `direction`) are ignored with `412 Precondition Failed`.

---

### 5.2 Account Snapshots

```
GET /v1/accounts/{account_id}/snapshots
```

Snapshots collapse entries into daily balances.

| Query Param | Description                         |
|-------------|-------------------------------------|
| `from_date` | Inclusive start date (ISO-8601)     |
| `to_date`   | Inclusive end date   (ISO-8601)     |

```json
{
  "data": [
    {
      "as_of": "2024-04-30",
      "balance": 78542.91,
      "currency": "USD"
    }
  ],
  "meta": {
    "generated_at": "2024-04-30T23:59:59Z"
  }
}
```

Snapshots are cached aggressively (TTL = 300s) and revalidated on ledger mutations.

---

### 5.3 Cash-Flow Forecasts

```
POST /v1/cashflows/forecasts
```

Request body:

```json
{
  "account_ids": ["ef83914f-4b2b-4ea5-9d38-38d79f5e70bc"],
  "horizon_days": 90,
  "scenario": "BASELINE"
}
```

Response (`202 Accepted`) returns a `forecast_id` and begins async processing.  
Poll status:

```
GET /v1/cashflows/forecasts/{forecast_id}
```

Possible `status` values: `PENDING`, `IN_PROGRESS`, `READY`, `FAILED`.

---

## 6. GraphQL Endpoint

```
POST /graphql
Content-Type: application/json
```

### 6.1 Schema Snapshot (excerpt)

```graphql
type LedgerEntry {
  entryId: UUID!
  accountId: UUID!
  amount: Decimal!
  currency: Currency!
  direction: Direction!
  postingDate: Date!
  description: String
  externalRef: String
  createdAt: DateTime!
  updatedAt: DateTime!
}

type Query {
  ledgerEntries(
    accountId: UUID
    fromDate: Date
    toDate: Date
    after: String
    first: Int = 100
  ): LedgerEntryConnection!
}

type Mutation {
  createLedgerEntry(input: CreateLedgerEntryInput!): LedgerEntry!
  updateLedgerEntry(entryId: UUID!, patch: UpdateLedgerEntryPatch!): LedgerEntry!
}
```

### 6.2 Example Query

```graphql
query Entries($account: UUID!, $cursor: String) {
  ledgerEntries(accountId: $account, first: 50, after: $cursor) {
    nodes {
      entryId
      amount
      currency
      postingDate
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
```

---

## 7. Pagination & Caching
Nexus employs _cursor-based pagination_ (`page[cursor]`). Cursors are opaque Base64-encoded and signed.

Responses MAY include:

```
Cache-Control: private, max-age=30, stale-while-revalidate=30
ETag: W/"67d32bca9"
```

Clients SHOULD provide `If-None-Match` for cache hits and store cursors per filter signature.

---

## 8. Rate Limiting
Default production limits:

| Resource            | Limit                       |
|---------------------|-----------------------------|
| **Authenticated**   | 600 requests / minute / key |
| **Unauthenticated** | *Not supported*             |

Headers:

```
X-RateLimit-Limit: 600
X-RateLimit-Remaining: 587
X-RateLimit-Reset: 1714928420
```

Exceeding returns `429 Too Many Requests` with a `Retry-After` header.

---

## 9. Observability & Tracing
All requests must include a UUID4 `X-Correlation-Id` header; otherwise the gateway assigns one.

Structured logs are emitted in the [OpenTelemetry](https://opentelemetry.io/) semantic conventions and shipped to the **LogDNA** cluster.  
Tracing: W3C `traceparent` header is honored.

---

## 10. Changelog

### 1.4.0 – 2024-05-01
* Added `direction` field enum values validation.
* Introduced async forecast processing with `/cashflows/forecasts`.

### 1.3.0 – 2024-03-26
* Experimental GraphQL endpoint (`/graphql`) graduated to GA.

### 1.2.2 – 2024-02-14
* Improved pagination performance with Redis cursor cache.

---

_For questions, contact dev-support@ledgerlink.io or join our Slack community._  
```