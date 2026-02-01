```markdown
<!--
  File: docs/api/v1_rest.md
  Project: SynestheticCanvas API Suite
  Component: REST Fallback Documentation (v1)
  ----------------------------------------------------------------------
  This document specifies the legacy‐compatible REST interface that sits
  in front of the GraphQL gateway.  It is auto-generated from the same
  OpenAPI schema that drives real-time validation inside the gateway.
  ----------------------------------------------------------------------
-->

# SynestheticCanvas REST API · v1

Welcome to the v1 REST surface of SynestheticCanvas—designed for clients
that cannot yet speak GraphQL.  Every resource you touch here maps
one-to-one to a GraphQL resolver, so you can migrate incrementally
without losing parity.

Base URL: `https://api.synestheticcanvas.io/v1`

> NOTE  
> This document intentionally mirrors the live OpenAPI definition
> published at `GET /v1/openapi.yaml`.  If anything in this file
> conflicts with the specification served by the gateway, the gateway
> wins.

---

## 1. Quick Start

### 1.1 Ping

```
GET /v1/health
```

Response:

```jsonc
{
  "service": "synestheticcanvas-gateway",
  "status": "ok",
  "timestamp": "2024-04-06T12:00:00Z",
  "uptime_ms": 2191378
}
```

### 1.2 Minimal cURL

```bash
curl -H "Authorization: Bearer ${TOKEN}" \
     -H "X-Request-Id: $(uuidgen)"    \
     https://api.synestheticcanvas.io/v1/palettes?limit=3
```

### 1.3 Minimal C / libcurl

```c
/* Compile with: cc -Wall -lcurl example.c -o example */
#include <curl/curl.h>
#include <stdio.h>

static size_t sink(void *buffer, size_t size, size_t nmemb, void *userp) {
    fwrite(buffer, size, nmemb, stdout);
    return size * nmemb;
}

int main(void) {
    CURL *curl = curl_easy_init();
    if (!curl) return 1;

    curl_easy_setopt(curl, CURLOPT_URL,
                     "https://api.synestheticcanvas.io/v1/palettes?limit=3");
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER,
                     curl_slist_append(NULL, "Authorization: Bearer YOUR_TOKEN"));
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, sink);

    CURLcode rc = curl_easy_perform(curl);
    curl_easy_cleanup(curl);
    return rc == CURLE_OK ? 0 : 1;
}
```

---

## 2. Authentication

All endpoints require **one** of the mechanisms below:

1. **Bearer JWT**  
   `Authorization: Bearer <jwt>`
2. **HMAC API Key**  
   ```
   X-Api-Key: <public>
   X-Api-Signature: <hex(hmac_sha256(secret, <request>))>
   ```

Requests without valid credentials receive `401 Unauthorized`.

---

## 3. Common Headers

| Header              | Direction | Purpose                                             |
|---------------------|-----------|-----------------------------------------------------|
| `X-Request-Id`      | In/Out    | Correlates distributed traces                       |
| `X-Rate-Limit-Limit`| Out       | Requests allowed in the current window              |
| `X-Rate-Limit-Remaining` | Out | Requests left in the current window                 |
| `X-Rate-Limit-Reset`| Out       | Window reset UNIX epoch (seconds)                   |
| `X-SC-Version`      | Out       | Deployed gateway build SHA                          |

---

## 4. Envelope Convention

Successful responses are wrapped to future-proof fields:

```jsonc
{
  "data": { /* payload */ },
  "meta": {
    "cursor":  "eyJpZCI6IjEyMyJ9",   // when paginated
    "elapsed": 4                     // server latency in ms
  }
}
```

Errors observe RFC 7807:

```jsonc
{
  "type":   "https://api.synestheticcanvas.io/errors/validation",
  "title":  "Validation error",
  "status": 422,
  "detail": "Field 'hex' must be 6 or 8 characters long",
  "instance": "0fe9f9a1-2b22-4c1e-a37f-7e54c559bd4d"
}
```

---

## 5. Pagination

Key           | Description
--------------|-------------
`limit`       | Max items (1–100, default 20)
`cursor`      | Opaque token returned in `meta.cursor`
`direction`   | `"forward"` \| `"backward"` (default `"forward"`)

---

## 6. Resources

### 6.1 Palette

Palette = a reusable set of colors (HEX or LAB) that can drive shaders,
text generators, or narrative mood themes.

| Method | Path                        | Description            |
|--------|----------------------------|------------------------|
| GET    | `/palettes`                | List palettes          |
| POST   | `/palettes`                | Create                 |
| GET    | `/palettes/{id}`           | Fetch single           |
| PATCH  | `/palettes/{id}`           | Partial update         |
| DELETE | `/palettes/{id}`           | Permanently remove     |

#### 6.1.1 List Palettes

```
GET /v1/palettes?limit=10&cursor=...&direction=backward
```

Query Parameters:

| Name       | Type   | Required | Note           |
|------------|--------|----------|----------------|
| `limit`    | int    | no       | 1–100          |
| `cursor`   | string | no       | from `meta`    |
| `direction`| enum   | no       | forward/backward |

Response `200 OK`

```jsonc
{
  "data": [
    {
      "id": "pal_01HD7J5F50FXKAX6236M3SVJRK",
      "name": "Cyber Sunset",
      "colors": ["#FF2167", "#FFDE59", "#3913B8", "#0D0D0D"],
      "created_at": "2024-02-17T13:38:22Z",
      "updated_at": "2024-02-25T19:12:54Z"
    }
    /* ... up to limit ... */
  ],
  "meta": {
    "cursor": "eyJyIjoiZm9vIn0=",
    "elapsed": 5
  }
}
```

Error Codes: `400` (bad parameter), `401`, `429`, `500`.

#### 6.1.2 Create Palette

```
POST /v1/palettes
Content-Type: application/json
```

Body:

```jsonc
{
  "name":   "Deep Ocean",
  "colors": ["#061A40", "#0353A4", "#006DAA", "#003559"]
}
```

Response `201 Created`

Headers:

```
Location: /v1/palettes/pal_01HD7...
```

Body:

```jsonc
{
  "data": {
    "id": "pal_01HD7YZFN83P9RCE64T08BHFYR",
    "name": "Deep Ocean",
    "colors": ["#061A40", "#0353A4", "#006DAA", "#003559"],
    "created_at": "2024-04-06T12:04:02Z",
    "updated_at": "2024-04-06T12:04:02Z"
  }
}
```

Validation Errors: `422 Unprocessable Entity`.

#### 6.1.3 Update Palette

```
PATCH /v1/palettes/{id}
```

Partial fields supported: `name`, `colors`.

Idempotent; returns `200 OK`.

#### 6.1.4 Delete Palette

`DELETE /v1/palettes/{id}`  
Soft-deletes by default; pass `?hard=true` for permanent removal.

---

### 6.2 Texture

| Method | Path                   | Description           |
|--------|-----------------------|-----------------------|
| GET    | `/textures`           | List shaders/textures |
| GET    | `/textures/{id}`      | Fetch details         |
| POST   | `/textures`           | Upload new texture    |
| DELETE | `/textures/{id}`      | Remove texture        |

Textures are stored in S3-compatible object storage and delivered over
CloudFront.  POST returns a pre-signed upload URL with one-time use.

---

### 6.3 Animation

| Method | Path                   | Description             |
|--------|-----------------------|-------------------------|
| POST   | `/animations`         | Kick off render job     |
| GET    | `/animations/{id}`    | Poll job progress       |
| DELETE | `/animations/{id}`    | Cancel (if queued)      |

Render jobs stream logs to `/animations/{id}/logs` via Server-Sent
Events.

---

### 6.4 Narrative

Narratives represent branching story graphs consumed by interactive
fiction engines.  The REST façade provides CRUD plus a “play” cursor
endpoint for stateless clients.

| Method | Path                                 | Description              |
|--------|--------------------------------------|--------------------------|
| POST   | `/narratives`                        | Create story             |
| GET    | `/narratives/{id}`                   | Inspect structure        |
| POST   | `/narratives/{id}/play`              | Advance via user choice  |

---

## 7. Error Reference

Code | Meaning                         | Retries | Notes
-----|---------------------------------|---------|----------------------------
400  | Bad Request                     | ✘       | Invalid parameters
401  | Unauthorized                    | ✘       | Missing / bad token
403  | Forbidden                       | ✘       | Valid token, insufficient scope
404  | Not Found                       | ✘       | Resource absent
409  | Conflict                        | ❔       | Depends on idempotency
422  | Unprocessable Entity            | ✘       | Validation failed
429  | Too Many Requests               | ✔︎       | Exponential backoff
500  | Internal Server Error           | ✔︎       | Server bug
503  | Service Unavailable             | ✔︎       | During deploy / overload

---

## 8. Rate Limiting

Limits are assigned per API key / user:

```
X-Rate-Limit-Limit:      120
X-Rate-Limit-Remaining:  47
X-Rate-Limit-Reset:      1712404800
```

When `429` is returned, retry **after** `Reset - now()` seconds.

---

## 9. Webhooks

Operations that take > 1 s (render, ingest) can notify your backend via
webhook.  Register at `POST /v1/hooks`:

```jsonc
{
  "url": "https://studio.example.com/sc/hooks",
  "events": ["render.completed", "palette.deleted"]
}
```

Each event is signed with your secret as:

```
X-Hub-Signature: sha256=<hex>
```

Verify before trusting the payload.

---

## 10. Versioning & Deprecation Policy

Path prefix (`/v1`) pins immutable semantics.  Breaking changes trigger
a new major version.  Minor/patch additions respect these rules:

1. Fields can be added but never removed.
2. Enum values can be appended.
3. Error codes ≥ 500 shall not be repurposed.

Deprecated endpoints emit:

```
Deprecation: version="2.1", date="2025-03-01"
Link: </v2/palettes>; rel="successor-version"
```

They remain available for **12 months** post-deprecation.

---

## 11. Changelog

Date        | Change
------------|----------------------------------------------------------
2024-04-06  | Initial publication
2024-04-06  | Clarified webhook signature header
```
