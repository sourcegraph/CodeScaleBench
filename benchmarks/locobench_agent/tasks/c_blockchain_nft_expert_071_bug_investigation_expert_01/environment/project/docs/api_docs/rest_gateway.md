```markdown
# HoloCanvas Gallery-Gateway  
REST API Documentation (v1)

_Last Updated: 2024-05-30_  
_Maintainer: core@holocanvas.io_  

> The Gallery-Gateway is the public-facing HTTP façade that fronts the internal
> event mesh (Kafka + gRPC).  It offers a thin, stateless REST layer for mobile
> apps, web wallets, and bot traders that do **not** speak gRPC.  
> All
> endpoints are **idempotent** where applicable and mirror the canonical
> protobuf definitions used on the service bus.

---

## Table of Contents
1. Versioning & Conventions  
2. Authentication  
3. Common HTTP Headers  
4. Error Model  
5. Resources  
   * `/v1/artifacts`  
   * `/v1/artifacts/:id`  
   * `/v1/artifacts/:id/bid`  
   * `/v1/artifacts/:id/state`  
   * `/v1/artifacts/:id/vote`  
   * `/v1/users/:id/wallet`  
6. Server-Sent Event Stream  
7. OpenAPI / Swagger Spec  
8. Reference C Client  
9. Changelog  

---

## 1. Versioning & Conventions
* All routes are prefixed with `/v1/*`.
* Dates are RFC-3339 UTC strings (`2024-05-30T18:26:00Z`).
* Monetary values are passed as **atomic units** of the on-chain token
  (int64).  Use `/v1/meta/token` for decimals.
* Pagination: `limit` (max 250), `cursor` (opaque base64).

---

## 2. Authentication
`Authorization: HMAC <key_id>:<base64_signature>`  
The signature is `base64( HMAC_SHA256( secret, <method>|<path>|<expires>|<sha256(body)>) )`  
Header `X-Expires` must be epoch seconds (±5 min drift).

---

## 3. Common HTTP Headers

| Header                | Example                               | Description                            |
|-----------------------|---------------------------------------|----------------------------------------|
| `Authorization`       | `HMAC 44c82:fXeb...`                  | HMAC credential                        |
| `X-Request-ID`        | `b3a1c33f-6f98-49ed...`               | Client-side trace ID                   |
| `X-Expires`           | `1717094159`                          | Signature TTL                          |
| `X-Rate-Limit-Remain` | `42`                                  | Remaining calls this window            |
| `Accept-Encoding`     | `gzip, zstd`                          | Optional compression                   |
| `Content-Type`        | `application/json`                    | Always JSON unless otherwise noted     |

---

## 4. Error Model
```json
{
  "error": {
    "code": "INVALID_SIGNATURE",
    "message": "HMAC verification failed",
    "data": {
      "path": "/v1/artifacts/123/bid"
    },
    "request_id": "b3a1c33f-6f98-49ed..."
  }
}
```
| HTTP | Code (string)          | Meaning                              |
|------|------------------------|--------------------------------------|
| 400  | `BAD_REQUEST`          | Validation error                     |
| 401  | `UNAUTHENTICATED`      | Missing / bad HMAC                   |
| 403  | `UNAUTHORIZED`         | Not permitted by DAO/ACL             |
| 404  | `NOT_FOUND`            | Resource absent                      |
| 409  | `CONFLICT`             | State transition illegal             |
| 429  | `RATE_LIMIT`           | Too many requests                    |
| 500  | `INTERNAL`             | Unhandled server error               |

---

## 5. Resources

### 5.1 GET `/v1/artifacts`
List Render-NFT artifacts (paginated).
```http
GET /v1/artifacts?limit=20&cursor=eyJwYWdlIjoxfQ== HTTP/1.1
Authorization: HMAC …
```
Successful `200 OK`
```json
{
  "artifacts": [ { "id": "arc_198a…", "title": "Blossom" /*…*/ } ],
  "next_cursor": "eyJwYWdlIjoyfQ=="
}
```

---

### 5.2 GET `/v1/artifacts/:id`
Retrieve full immutable recipe + live state.
```bash
curl -H "Authorization: HMAC …" \
     https://api.holocanvas.io/v1/artifacts/arc_198a01
```
`200 OK`
```json
{
  "id": "arc_198a01",
  "creator": "usr_fe12",
  "state": "CURATED",
  "recipe": {
    "shader_frag": "ipfs://bafy…/pixel.frag",
    "audio_layer": "ipfs://bafy…/score.wav"
  },
  "live_metrics": {
    "likes": 172,
    "highest_bid": 900000000
  }
}
```

---

### 5.3 POST `/v1/artifacts/:id/bid`
Place a sealed-bid; on success an async event triggers on chain.
```http
POST /v1/artifacts/arc_198a01/bid HTTP/1.1
Content-Type: application/json
Authorization: HMAC …
{
  "amount": 950000000,
  "currency": "HOLO"
}
```
`201 Created`
```json
{ "tx_hash": "0x5aee…", "status": "PENDING" }
```
Error `409 CONFLICT` when bidding below reserve or after auction-end.

---

### 5.4 PATCH `/v1/artifacts/:id/state`
Curator-only state transition (`CURATED → AUCTION`, etc.).
```json
{
  "next_state": "AUCTION",
  "reason": "DAO-vote 42 passed"
}
```
Returns `200 OK` with updated artifact or `403 UNAUTHORIZED`.

---

### 5.5 POST `/v1/artifacts/:id/vote`
Governance vote on fractionalized artwork; payload:
```json
{ "option": "EXTEND_AUCTION", "weight": 1 }
```

---

### 5.6 GET `/v1/users/:id/wallet`
Partial proxy into Wallet-Proxy micro-service.

---

## 6. Server-Sent Event Stream

Clients can subscribe to a low-latency push channel:

```http
GET /v1/events/stream?topic=artifacts/* HTTP/1.1
Accept: text/event-stream
Authorization: HMAC …
```
Events are CloudEvents v1.0 over SSE:
```
event: bid.accepted
id: 1b0be…
data: {"artifact_id":"arc_198a01","amount":950000000}
```
Reconnect using the `Last-Event-ID` header to resume.

---

## 7. OpenAPI 3.0 Definition
```yaml
openapi: 3.0.3
info:
  title: HoloCanvas Gallery-Gateway
  version: "1.0.0"
servers:
  - url: https://api.holocanvas.io/v1
paths:
  /artifacts:
    get:
      operationId: listArtifacts
      parameters:
        - $ref: '#/components/parameters/limit'
        - $ref: '#/components/parameters/cursor'
      responses:
        '200':
          description: Paginated list
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ArtifactList'
  /artifacts/{id}:
    get:
      operationId: getArtifact
      parameters:
        - $ref: '#/components/parameters/id'
      responses:
        '200':
          description: Artifact
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Artifact'
  /artifacts/{id}/bid:
    post:
      operationId: postBid
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/BidRequest'
      responses:
        '201':
          description: Bid accepted (pending on-chain)
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BidResponse'
components:
  parameters:
    limit:
      name: limit
      in: query
      schema: { type: integer, maximum: 250, default: 20 }
    cursor:
      name: cursor
      in: query
      schema: { type: string }
    id:
      name: id
      in: path
      required: true
      schema: { type: string }
  schemas:
    ArtifactList:
      type: object
      properties:
        artifacts:
          type: array
          items: { $ref: '#/components/schemas/Artifact' }
        next_cursor: { type: string }
    Artifact:
      type: object
      required: [id, state]
      properties:
        id:  { type: string }
        title: { type: string }
        creator: { type: string }
        state: { type: string, enum: [DRAFT, CURATED, AUCTION, FRACTIONALIZED, STAKED] }
    BidRequest:
      type: object
      properties:
        amount: { type: integer }
        currency: { type: string }
    BidResponse:
      type: object
      properties:
        tx_hash: { type: string }
        status: { type: string }
security:
  - HMACAuth: []
components:
  securitySchemes:
    HMACAuth:
      type: http
      scheme: HMAC
```

---

## 8. Reference C Client (libcurl + Jansson)

```c
/*
 * Minimal bid example.
 * Compile: gcc bid.c -o bid -lcurl -ljansson -lcrypto
 */
#include <curl/curl.h>
#include <jansson.h>
#include <openssl/hmac.h>
#include <openssl/evp.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#define API_KEY_ID   "44c82"
#define API_SECRET   "b7e5c21a...redacted..."
#define HOLO_HOST    "https://api.holocanvas.io"
#define BUF_SIZE     4096

static size_t write_cb(void *ptr, size_t size, size_t nmemb, void *userdata) {
    size_t total = size * nmemb;
    fwrite(ptr, 1, total, stdout); /* stream directly to STDOUT */
    return total;
}

static void sha256_hex(const char *data, unsigned char *digest) {
    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    EVP_DigestInit_ex(ctx, EVP_sha256(), NULL);
    EVP_DigestUpdate(ctx, data, strlen(data));
    unsigned int len = 0;
    EVP_DigestFinal_ex(ctx, digest, &len);
    EVP_MD_CTX_free(ctx);
}

static char *base64(const unsigned char *input, int len) {
    BIO *b64 = BIO_new(BIO_f_base64());
    BIO *mem = BIO_new(BIO_s_mem());
    b64 = BIO_push(b64, mem);
    BIO_set_flags(b64, BIO_FLAGS_BASE64_NO_NL);
    BIO_write(b64, input, len);
    BIO_flush(b64);
    BUF_MEM *bptr;
    BIO_get_mem_ptr(b64, &bptr);
    char *buff = calloc(1, bptr->length + 1);
    memcpy(buff, bptr->data, bptr->length);
    BIO_free_all(b64);
    return buff;
}

static char *sign_request(const char *method,
                          const char *path,
                          long expires,
                          const char *body) {
    unsigned char hash[EVP_MAX_MD_SIZE];
    char body_hash_hex[65] = {0};
    sha256_hex(body, hash);
    for (int i = 0; i < 32; ++i)
        sprintf(&body_hash_hex[i*2], "%02x", hash[i]);

    char preimage[1024];
    snprintf(preimage, sizeof(preimage), "%s|%s|%ld|%s",
             method, path, expires, body_hash_hex);

    unsigned char *sig_raw =
        HMAC(EVP_sha256(),
             API_SECRET, strlen(API_SECRET),
             (unsigned char *)preimage, strlen(preimage),
             NULL, NULL);

    char *sig_b64 = base64(sig_raw, 32);
    static char header[128];
    snprintf(header, sizeof(header), "HMAC %s:%s", API_KEY_ID, sig_b64);
    free(sig_b64);
    return header;
}

int main(void) {
    CURL *curl = curl_easy_init();
    if (!curl) return 1;

    /* ---- build JSON body ---- */
    json_t *root = json_object();
    json_object_set_new(root, "amount", json_integer(950000000));
    json_object_set_new(root, "currency", json_string("HOLO"));
    char *body = json_dumps(root, JSON_COMPACT);
    json_decref(root);

    /* ---- timestamp & signature ---- */
    long expires = time(NULL) + 60;
    const char *path = "/v1/artifacts/arc_198a01/bid";
    char *auth_header = sign_request("POST", path, expires, body);

    /* ---- HTTP request ---- */
    struct curl_slist *headers = NULL;
    char exp_header[64];
    snprintf(exp_header, sizeof(exp_header), "X-Expires: %ld", expires);
    headers = curl_slist_append(headers, "Content-Type: application/json");
    headers = curl_slist_append(headers, auth_header);
    headers = curl_slist_append(headers, exp_header);

    char url[256];
    snprintf(url, sizeof(url), "%s%s", HOLO_HOST, path);

    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_cb);

    CURLcode res = curl_easy_perform(curl);
    if (res != CURLE_OK) {
        fprintf(stderr, "curl error: %s\n", curl_easy_strerror(res));
    }

    /* ---- cleanup ---- */
    curl_easy_cleanup(curl);
    curl_slist_free_all(headers);
    free(body);
    /* auth_header points into static buffer, no free */

    return 0;
}
```

---

## 9. Changelog
| Date       | Version | Notes                        |
|------------|---------|------------------------------|
| 2024-05-30 | 1.0.0   | Initial public release       |
| 2024-06-02 | 1.1.0   | Added `/vote`, SSE heartbeat |
```