```markdown
# IntraLedger BlogSuite – REST API Reference
Version: **v1.3**  
Updated: **2024-05-01**

The IntraLedger BlogSuite API allows partner systems, mobile clients, and internal micro-frontends to interact with the BlogSuite monolith over secure HTTPS.  
All endpoints are served from the same executable that powers the UI, ensuring perfect feature parity between the public web interface and remote access.

```
Base URL (production):  
`https://{your-domain}/api/v1`

All requests **must** be sent over TLS 1.2+ and include a valid `Accept: application/json` header. The server will perform content negotiation and return `406 Not Acceptable` if the client requests an unsupported media type.

---

## Table of Contents
1. Authentication  
2. Articles  
3. Search  
4. Media Uploads  
5. Subscriptions & Payments  
6. Administration  
7. Webhooks  
8. Errors & Problem Details  
9. SDK (Modern C++ 20)  

---

## 1 — Authentication

A successful authentication returns a **JWT** access token (default lifetime = 60 minutes) and a refresh token (default lifetime = 30 days).

### 1.1 Login

```
POST /auth/login
Content-Type: application/json
```

Payload

```json
{
  "email"   : "alice@example.com",
  "password": "CorrectHorseBatteryStaple"
}
```

Response `200 OK`

```json
{
  "accessToken" : "eyJhbGciOiJSUzI1NiIsInR5...",
  "refreshToken": "def50200cb9694...",
  "expiresIn"   : 3600,
  "tokenType"   : "Bearer"
}
```

Errors  
• `401 Unauthorized` – invalid credentials  
• `423 Locked` – user suspended or MFA required  

---

### 1.2 Token Refresh

```
POST /auth/refresh
Authorization: Bearer <refreshToken>
```

Response mirrors the login endpoint.

---

### 1.3 Logout

```
POST /auth/logout
Authorization: Bearer <accessToken>
```

• Invalidates both access and refresh tokens.  
• Always returns `204 No Content` whether or not the token is known (to prevent token probing).

---

## 2 — Articles

| Method | Endpoint                    | Scope                | Description                      |
|--------|----------------------------|----------------------|----------------------------------|
| GET    | `/articles`                | `read:articles`      | List, filter, and paginate posts |
| GET    | `/articles/{slug}`         | `read:articles`      | Retrieve single post             |
| POST   | `/articles`                | `write:articles`     | Create new post (draft)          |
| PATCH  | `/articles/{slug}`         | `write:articles`     | Update an existing post          |
| DELETE | `/articles/{slug}`         | `delete:articles`    | Soft-delete a post               |

All article operations return an **ETag** header (SHA-256 of the canonical JSON). Use `If-None-Match` to implement efficient client-side caching.

### 2.1 List Articles

```
GET /articles?lang=en&tag=dev&limit=20&page=2
Authorization: Bearer <token>
```

Response `200 OK`

```json
{
  "page"  : 2,
  "limit" : 20,
  "total" : 64,
  "items" : [
    {
      "slug"       : "modern-cpp-error-handling",
      "title"      : "Modern C++ Error Handling",
      "summary"    : "A tour of std::expected and more.",
      "author"     : { "id": 42, "name": "Alice K." },
      "publishedAt": "2024-04-12T08:30:00Z",
      "tags"       : ["cpp20", "error-handling"],
      "premium"    : false,
      "links"      : {
        "self": "/articles/modern-cpp-error-handling"
      }
    }
    /* … 19 more … */
  ],
  "_links": {
    "first": "/articles?limit=20&page=1",
    "prev" : "/articles?limit=20&page=1",
    "next" : "/articles?limit=20&page=3",
    "last" : "/articles?limit=20&page=4"
  }
}
```

---

### 2.2 Create Article

```
POST /articles
Content-Type: application/json
Authorization: Bearer <token>
```

```json
{
  "title"  : "Multithreading with C++23",
  "body"   : "# Executive Summary\nC++23 brings ...",
  "lang"   : "en",
  "tags"   : ["cpp23", "concurrency"],
  "status" : "draft",   // draft | published
  "premium": true
}
```

Response `201 Created`  
`Location: /articles/multithreading-with-cpp23`

---

### 2.3 Update Article (PATCH)

Supports JSON Patch (`application/json-patch+json`) or Merge Patch. Concurrency is enforced via `If-Match` header.

```json
[
  { "op": "replace", "path": "/title", "value": "Multithreading with C++ 23" },
  { "op": "replace", "path": "/status", "value": "published" }
]
```

---

## 3 — Search

```
GET /search?q=std::expected+intro&facet=tag&limit=10
```

Returns both matching articles and aggregated facets.

---

## 4 — Media Uploads

### 4.1 Image Upload (async)

```
POST /media/images
Content-Type: multipart/form-data
```

The endpoint responds with `202 Accepted` and a job ID.  
Clients can poll `/media/jobs/{id}` or subscribe to the server-sent events stream `/events/media`.

---

## 5 — Subscriptions & Payments

| Endpoint                | Description                                 |
|-------------------------|---------------------------------------------|
| `/billing/tiers`        | List available subscription tiers           |
| `/billing/checkout`     | Initiate checkout session (PCI-compliant)   |
| `/billing/webhook`      | Stripe/Adyen webhook (server-to-server)     |

All payment data are processed off-site; BlogSuite stores only minimal metadata and last 4 digits for audit.

---

## 6 — Administration

All admin routes are prefixed with `/admin` and are protected by RBAC (`role:admin` plus granular policies).

```
GET /admin/audit?event=login_failure&limit=50
```

---

## 7 — Webhooks

BlogSuite can notify external systems on key events.

| Event        | Payload Schema                    |
|--------------|-----------------------------------|
| `article.published` | Article payload             |
| `subscription.renewed` | Subscription metadata    |
| `media.processed`  | Media job result             |

Each webhook is signed using HMAC-SHA256 + timestamp header (`X-BSignature`). Verify the signature before trusting the payload.

---

## 8 — Errors & Problem Details

The API follows [RFC 9457](https://datatracker.ietf.org/doc/html/rfc9457) (*Problem Details for HTTP APIs*).

Example — `404 Not Found`

```json
{
  "type"   : "https://docs.intraledger.io/errors/resource-not-found",
  "title"  : "Resource Not Found",
  "status" : 404,
  "detail" : "Article slug 'does-not-exist' not found.",
  "instance": "/articles/does-not-exist"
}
```

---

## 9 — Modern C++ 20 SDK (Header-only)

A thin wrapper around **std::net** (or Boost.Beast) is available under the namespace `ilb::sdk`.  
Below is a quick-start example that lists the first page of articles.

```cpp
// file: examples/list_articles.cpp
#include <ilb/sdk/client.hpp>
#include <iostream>

int main() try
{
    using ilb::sdk::HttpClient;
    using ilb::sdk::JwtToken;

    // Load token from env or secrets manager
    JwtToken token = JwtToken::load_from_env("BLOGSUITE_TOKEN");

    HttpClient client{
        /* base_url = */ "https://demo.intraledger.io/api/v1",
        /* default_headers = */ {
            { "Accept", "application/json" },
            { "Authorization", "Bearer " + token.access_token() }
        }
    };

    auto response = client.get("/articles?limit=5");
    if (response.ok()) {
        auto json = response.json(); // nlohmann::json
        std::cout << "Total articles: " << json["total"] << '\n';
        for (auto& item : json["items"]) {
            std::cout << "- " << item["title"].get<std::string>() << '\n';
        }
    } else {
        std::cerr << "Request failed: " << response.status()
                  << " — " << response.error_message() << '\n';
    }
}
catch (const std::exception& ex) {
    std::cerr << "Fatal: " << ex.what() << '\n';
    return EXIT_FAILURE;
}
```

Compile

```bash
g++ -std=c++20 -Wall -O2 examples/list_articles.cpp -o list_articles \
    -I./vendor/nlohmann_json/include -lcurl
```

---

### SDK Error Handling

All SDK methods return an `ilb::sdk::Response` object.  
`ok()` is `true` for any `2xx` status code.

```cpp
if (!resp.ok()) {
    if (resp.status() == 401) {
        throw ilb::sdk::AuthError{resp.problem_detail()};
    }
    // Other domain-specific error translation…
}
```

---

## Changelog

| Version | Date       | Notes                         |
|---------|-----------|-------------------------------|
| 1.3     | 2024-05-01 | Added RFC 9457 compliance     |
| 1.2     | 2024-03-15 | Media jobs + SSE stream       |
| 1.1     | 2024-01-20 | Payment tier management       |
| 1.0     | 2023-11-01 | Initial public release        |

---

© 2024 IntraLedger LLC. All rights reserved.  
Please report issues at `https://github.com/intraledger/blogsuite/issues`.
```