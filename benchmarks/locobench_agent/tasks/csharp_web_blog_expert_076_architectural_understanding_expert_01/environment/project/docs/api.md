```md
# TempoScribe Pro API Reference  
> Build blazing-fast, production-grade integrations with the Hexagonal Productivity Blog Suite.

---

## 1  Introduction
TempoScribe Pro exposes a versioned, JSON-over-HTTPS REST API (and an opt-in GraphQL gateway) designed around Ports & Adapters.  
All operations are idempotent whenever possible, secured by OAuth 2.0 / OpenID Connect (IdentityServer4), and return standard [RFC 7807](https://www.rfc-editor.org/rfc/rfc7807) problem details on error.

| Environment | Base URL                         |
|-------------|----------------------------------|
| Production  | `https://api.temposcribe.app`    |
| Sandbox     | `https://sandbox.temposcribe.app`|

```http
# Version check
GET /api/v1 HTTP/1.1
Host: api.temposcribe.app
Accept: application/json
```

Response:
```json
{
  "version": "1.0.0",
  "timestamp": "2024-05-19T12:05:10Z",
  "commit": "23ec8d4"
}
```

---

## 2  Authentication & Authorization

### 2.1  OAuth 2.0 Client Credentials (Server → Server)
1. Register an application in **Admin Panel → Integrations → API Keys**.  
2. Exchange `ClientId`/`ClientSecret` for a token:

```http
POST /connect/token HTTP/1.1
Host: login.temposcribe.app
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&
client_id=blog-bot&
client_secret={secret}&
scope=ts.read ts.write
```

Response:
```json
{
  "access_token": "{jwt}",
  "expires_in": 3600,
  "token_type": "Bearer",
  "scope": "ts.read ts.write"
}
```

### 2.2  Bearer Token Usage
Send the token in the `Authorization` header:

```http
GET /api/v1/posts HTTP/1.1
Authorization: Bearer eyJhbGciOiJSUzI1NiIsIn...
```

Tokens expire after **1 hour**; use `refresh_token` flow when needed.

---

## 3  Content Domain

### 3.1  Posts

| Verb | Path                     | Description                       | Auth  |
|------|--------------------------|-----------------------------------|-------|
| GET  | `/api/v1/posts`          | List posts (paginated)            | Public|
| GET  | `/api/v1/posts/{id}`     | Fetch single post                 | Public|
| POST | `/api/v1/posts`          | Create draft                      | ts.write |
| PUT  | `/api/v1/posts/{id}`     | Update draft or publish           | ts.write |
| DEL  | `/api/v1/posts/{id}`     | Delete (soft)                     | ts.write |

#### 3.1.1  JSON Schema (v1)
```jsonc
{
  "id": "guid",
  "slug": "string",
  "title": "string",
  "content": "markdown",
  "status": "Draft|Published|Scheduled",
  "tags": ["string"],
  "scheduledAt": "2024-05-30T18:00:00Z",
  "premium": true,
  "createdAt": "iso-datetime",
  "updatedAt": "iso-datetime"
}
```

#### 3.1.2  Create Draft
```http
POST /api/v1/posts HTTP/1.1
Content-Type: application/json
Authorization: Bearer {token}

{
  "title": "Boosting Developer Flow",
  "content": "# Flow matters\n\n> Measure lead-time for change…",
  "tags": ["productivity","engineering"],
  "premium": false
}
```

Response `201 Created` + `Location` header.

#### 3.1.3  Scheduled Publish
```http
POST /api/v1/posts/{id}/schedule HTTP/1.1
Content-Type: application/json
Authorization: Bearer {token}

{
  "scheduledAt": "2024-05-30T18:00:00Z"
}
```

---

### 3.2  Comments

| Verb | Path                                  | Description                    |
|------|---------------------------------------|--------------------------------|
| GET  | `/api/v1/posts/{id}/comments`         | List comments                  |
| POST | `/api/v1/posts/{id}/comments`         | Add comment (rate-limited)     |
| DEL  | `/api/v1/comments/{commentId}`        | Moderation delete              |

Comment schema:
```jsonc
{
  "id": "guid",
  "authorName": "string",
  "authorAvatar": "url",
  "body": "markdown",
  "createdAt": "iso-datetime"
}
```

---

### 3.3  Attachments (Blob Storage Adapter)

- **POST** `/api/v1/attachments` multipart/form-data  
  Fields: `file`, `referenceId` (post/comment), optional `altText`.

---

### 3.4  Editorial Tasks (Kanban)

| Verb | Path                       | Description              |
|------|---------------------------|--------------------------|
| GET  | `/api/v1/tasks`           | Backlog / board          |
| POST | `/api/v1/tasks`           | Create                   |
| PATCH| `/api/v1/tasks/{id}`      | Move/assign/complete     |

Task schema aligns to **WorkSession** aggregates.

---

## 4  Monetization

### 4.1  Stripe Checkout Session
```http
POST /api/v1/payments/stripe/checkout HTTP/1.1
Content-Type: application/json
Authorization: Bearer {token}

{
  "postId": "c115c9e9-9f37-4b30-88af-a89a297e08cd",
  "successUrl": "https://blog.example.com/pay/success",
  "cancelUrl": "https://blog.example.com/pay/cancel"
}
```

Returns `sessionId` for Stripe JS.

Webhook for status: `POST /api/v1/payments/stripe/webhook`.

---

## 5  Errors

TempoScribe Pro follows RFC 7807:

```http
HTTP/1.1 404 Not Found
Content-Type: application/problem+json

{
  "type":   "https://docs.temposcribe.app/errors/not-found",
  "title":  "Post not found",
  "status": 404,
  "detail": "No post with id 96f6… exists.",
  "traceId": "00-8d29e5ff6b21ce2c-5e6f0c4977b2b1b4-00"
}
```

Common codes: `400, 401, 403, 404, 409, 422, 429, 500`.

---

## 6  Rate Limits

Free tier: **60 requests/min** per IP.  
Headers returned:

```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 12
X-RateLimit-Reset: 1716131700
```

---

## 7  C# SDK (NuGet `TempoScribe.Client`)

### 7.1  Installation

```bash
dotnet add package TempoScribe.Client
```

### 7.2  Quick Start

```csharp
using System;
using System.Threading.Tasks;
using TempoScribe.Client;
using TempoScribe.Client.Models;
using Microsoft.Extensions.DependencyInjection;
using Polly;
using Polly.Extensions.Http;
using System.Net.Http;

var services = new ServiceCollection()
    .AddTempoScribeClient(options =>
    {
        options.BaseUrl = "https://api.temposcribe.app/api/v1";
        options.ClientId = Environment.GetEnvironmentVariable("TS_CLIENT_ID");
        options.ClientSecret = Environment.GetEnvironmentVariable("TS_CLIENT_SECRET");
        options.Scopes = new[] { "ts.read", "ts.write" };
    })
    // Resilience with Polly
    .AddHttpClient<ITempoScribeClient, TempoScribeClient>()
        .AddPolicyHandler(HttpPolicyExtensions
            .HandleTransientHttpError()
            .WaitAndRetryAsync(3, retry => TimeSpan.FromSeconds(Math.Pow(2, retry))))
    .Services
    .BuildServiceProvider();

var client = services.GetRequiredService<ITempoScribeClient>();

// Create a draft post
PostDraft draft = new()
{
    Title = "5 Ways to Reduce Cycle Time",
    Content = "_Shipping beats perfection._",
    Tags = new[] { "lean", "devops" }
};

Post post = await client.Posts.CreateAsync(draft);
Console.WriteLine($"Draft saved with id {post.Id}");

// Schedule publish
await client.Posts.ScheduleAsync(post.Id, DateTimeOffset.UtcNow.AddDays(2));
```

### 7.3  Pagination Helper

```csharp
await foreach (var page in client.Posts.ListAsync(pageSize: 50))
{
    foreach (var p in page.Items)
        Console.WriteLine($"{p.Id} – {p.Title}");
}
```

---

## 8  Webhook Events

Subscribe under **Admin Panel → Webhooks**.  
Headers: `TS-Signature`, `TS-Delivery` (UUID v7).

| Event              | Payload root   |
|--------------------|----------------|
| `post.published`   | `post`         |
| `post.deleted`     | `post`         |
| `payment.succeeded`| `payment`      |
| `comment.created`  | `comment`      |

Verify HMAC-SHA256 signature.

---

## 9  Change Log

| Date       | Version | Notes                          |
|------------|---------|--------------------------------|
| 2024-05-19 | 1.0.0   | Initial GA release.            |

---

© 2024 TempoScribe Inc. All rights reserved.
```