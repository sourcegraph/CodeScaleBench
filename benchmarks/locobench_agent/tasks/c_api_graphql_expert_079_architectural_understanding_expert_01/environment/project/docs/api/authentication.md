```markdown
# SynestheticCanvas API Suite  
## Authentication Guide
**File:** `docs/api/authentication.md`  
**Service Version:** `v2.3.1`  
**Last Updated:** 2024-06-01

---

> “Every brush stroke should be traceable to a verified artist.”  
> — SynestheticCanvas Core Tenet

This document explains how clients securely authenticate with the SynestheticCanvas API Gateway, whether you are using the GraphQL façade or REST fallbacks. It covers:

* API-Key bootstrap flow  
* OAuth 2.1 (PKCE) & JWT bearer tokens  
* Token refresh & rotation  
* Service-to-service mutual-TLS (mTLS)  
* Example C code using _libcurl_ + _OpenSSL_  
* Common error codes & troubleshooting

---

## 1. Quick Start (TL;DR)

```bash
# 1) Obtain a short-lived access token using your issued API Key
curl -X POST https://gateway.syncanvas.io/auth/token \
     -H "X-API-KEY: <YOUR_API_KEY>" \
     -d "grant_type=client_credentials&scope=palette:write texture:read"

# 2) Use the bearer token when querying GraphQL
curl -X POST https://gateway.syncanvas.io/graphql \
     -H "Authorization: Bearer <ACCESS_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"query":"{ palettes { id name dominantColor } }"}'
```

---

## 2. Authentication Models

| Use-Case                           | Flow                                    | Token Life-Span | Refresh | Notes                                        |
|-----------------------------------|-----------------------------------------|-----------------|---------|----------------------------------------------|
| Human artist on desktop/mobile    | OAuth 2.1 Authorization Code + PKCE     | 60 min          | ✔︎       | Uses branded sign-in UI                      |
| Service-to-service (CI / render)  | API Key → Client Credentials            | 15 min          | ✔︎       | Key can be rotated without downtime          |
| Internal microservice             | Mutual-TLS + JWT                        | 5 min           | ✖︎       | Keyless—issuer bound by client certificate   |
| Exhibition Kiosk (offline first)  | Signed Refresh Token (RT)               | 30 days         | n/a     | RT stored on disk, Access Token derived locally |

---

## 3. Endpoints

### 3.1 `/auth/token` — Obtain Token

```
POST /auth/token HTTP/1.1
Host: gateway.syncanvas.io
X-API-KEY: 15b1c2d3-...
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&
scope=palette:read texture:write
```

Successful response:

```json
HTTP/1.1 200 OK
Content-Type: application/json

{
  "access_token":  "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expires_in":    900,
  "token_type":    "Bearer",
  "scope":         "palette:read texture:write",
  "refresh_token": "def50200abcf..."
}
```

Field | Description
-------|------------
`access_token` | Base64-encoded JWT
`expires_in`   | Seconds until expiry
`refresh_token`| Present only when `offline_access` scope requested

### 3.2 `/auth/refresh` — Rotate Token

```
POST /auth/refresh
Authorization: Bearer <REFRESH_TOKEN>
```

Returns a new `access_token` and, if rotation enabled, a new `refresh_token`.

---

## 4. JWT Claims

Claim         | Type      | Example                 | Notes
--------------|-----------|-------------------------|----------------------------------
`iss`         | String    | `https://gateway.syncanvas.io`
`aud`         | String    | `syncanvas-api`
`sub`         | UUID      | `5907d18b-11bf-4e86-a...`
`scope`       | Space-del | `palette:write texture:read`
`exp`/`iat`   | Int       | Epoch seconds           | Clock skew ≤ 30 s
`ver`         | Int       | `2`                     | Schema version
`sig` (header)| RS256     | ‑                       | 4096-bit RSA

Public JWKs: `https://gateway.syncanvas.io/.well-known/jwks.json`

---

## 5. C Code — Authentication in Practice

Below is a *production-grade* snippet that:

1. Exchanges an API Key for a JWT  
2. Stores the token in memory-locked buffer  
3. Calls the GraphQL endpoint  
4. Verifies the JWT signature using the JWK set  

> Dependencies: libcurl ≥ 7.80, OpenSSL ≥ 1.1.1, [jansson](https://digip.org/jansson/) for JSON parsing.

```c
/*
 * auth_client.c  — Minimal yet production-ready authentication example
 *
 * Build:
 *   cc -Wall -O2 -o auth_client \
 *      auth_client.c -lcurl -lcrypto -lssl -ljansson -lpthread
 *
 * Note:
 *   Error handling is simplified for brevity but demonstrates the
 *   patterns we use in the SynestheticCanvas SDK.
 */
#define _POSIX_C_SOURCE 200809L
#include <curl/curl.h>
#include <jansson.h>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/x509.h>
#include <openssl/bio.h>
#include <openssl/buffer.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* ---- Configurable Constants ------------------------------------------- */
#define TOKEN_URL     "https://gateway.syncanvas.io/auth/token"
#define GRAPHQL_URL   "https://gateway.syncanvas.io/graphql"
#define API_KEY_ENV   "SYNCANVAS_API_KEY"
#define SCOPE         "palette:read texture:write"
#define GRAPHQL_QUERY "{\"query\":\"{ serverTime }\"}"

#define CURL_CHECK(x) do { \
    CURLcode __rc = (x);   \
    if (__rc != CURLE_OK) {\
        fprintf(stderr, "CURL error: %s\\n", curl_easy_strerror(__rc)); \
        exit(EXIT_FAILURE); \
    } } while(0)

/* ---- Helpers ----------------------------------------------------------- */
struct mem_buf {
    char *ptr;
    size_t len;
};

static size_t write_cb(void *data, size_t size, size_t nmemb, void *userp) {
    size_t realsize = size * nmemb;
    struct mem_buf *mem = (struct mem_buf *)userp;

    char *newptr = realloc(mem->ptr, mem->len + realsize + 1);
    if (!newptr) return 0;
    mem->ptr = newptr;
    memcpy(&(mem->ptr[mem->len]), data, realsize);
    mem->len += realsize;
    mem->ptr[mem->len] = 0;
    return realsize;
}

static char *percent_encode(const char *s) {
    CURL *c = curl_easy_init();
    char *out = curl_easy_escape(c, s, 0);
    curl_easy_cleanup(c);
    return out;
}

/* ---- Step 1: Exchange API Key for Token ------------------------------- */
static char *obtain_access_token(void) {
    const char *api_key = getenv(API_KEY_ENV);
    if (!api_key) {
        fprintf(stderr, "Error: %s not set\\n", API_KEY_ENV);
        exit(EXIT_FAILURE);
    }

    struct mem_buf response = { .ptr = malloc(1), .len = 0 };
    CURL *curl = curl_easy_init();
    CURL_CHECK(curl_easy_setopt(curl, CURLOPT_URL, TOKEN_URL));
    CURL_CHECK(curl_easy_setopt(curl, CURLOPT_POST, 1L));

    /* Build POST body */
    char *encoded_scope = percent_encode(SCOPE);
    char *post_fields = NULL;
    asprintf(&post_fields,
             "grant_type=client_credentials&scope=%s",
             encoded_scope);
    free(encoded_scope);

    CURL_CHECK(curl_easy_setopt(curl, CURLOPT_POSTFIELDS, post_fields));
    CURL_CHECK(curl_easy_setopt(curl, CURLOPT_HTTPHEADER,
        curl_slist_append(NULL, "Content-Type: application/x-www-form-urlencoded")));
    struct curl_slist *hdrs = NULL;
    char hdr_key[128];
    snprintf(hdr_key, sizeof(hdr_key), "X-API-KEY: %s", api_key);
    hdrs = curl_slist_append(hdrs, hdr_key);
    CURL_CHECK(curl_easy_setopt(curl, CURLOPT_HTTPHEADER, hdrs));
    CURL_CHECK(curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_cb));
    CURL_CHECK(curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response));
    CURL_CHECK(curl_easy_perform(curl));

    long code = 0;
    CURL_CHECK(curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &code));
    if (code != 200) {
        fprintf(stderr, "Token endpoint returned %ld: %s\\n", code, response.ptr);
        exit(EXIT_FAILURE);
    }

    /* Parse JSON */
    json_error_t jerr;
    json_t *root = json_loads(response.ptr, 0, &jerr);
    if (!root) {
        fprintf(stderr, "JSON parse error: %s\\n", jerr.text);
        exit(EXIT_FAILURE);
    }
    const char *tok = json_string_value(json_object_get(root, "access_token"));
    if (!tok) {
        fprintf(stderr, "No access_token in response\\n");
        exit(EXIT_FAILURE);
    }

    /* Duplicate token into locked memory */
    size_t len = strlen(tok);
    char *secured = malloc(len + 1);
    if (mlock(secured, len + 1) != 0) {
        perror("mlock");
        /* continue with regular memory if locking fails */
    }
    strcpy(secured, tok);

    /* Cleanup */
    json_decref(root);
    curl_easy_cleanup(curl);
    curl_slist_free_all(hdrs);
    free(post_fields);
    free(response.ptr);

    return secured;
}

/* ---- Step 2: Call GraphQL Endpoint ------------------------------------ */
static void call_graphql(const char *jwt) {
    struct mem_buf response = { .ptr = malloc(1), .len = 0 };
    CURL *curl = curl_easy_init();
    CURL_CHECK(curl_easy_setopt(curl, CURLOPT_URL, GRAPHQL_URL));
    CURL_CHECK(curl_easy_setopt(curl, CURLOPT_POST, 1L));
    CURL_CHECK(curl_easy_setopt(curl, CURLOPT_POSTFIELDS, GRAPHQL_QUERY));
    struct curl_slist *hdrs = NULL;
    hdrs = curl_slist_append(hdrs, "Content-Type: application/json");
    char auth_hdr[512];
    snprintf(auth_hdr, sizeof(auth_hdr), "Authorization: Bearer %s", jwt);
    hdrs = curl_slist_append(hdrs, auth_hdr);
    CURL_CHECK(curl_easy_setopt(curl, CURLOPT_HTTPHEADER, hdrs));
    CURL_CHECK(curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_cb));
    CURL_CHECK(curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response));
    CURL_CHECK(curl_easy_perform(curl));

    long code = 0;
    CURL_CHECK(curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &code));
    if (code != 200) {
        fprintf(stderr, "GraphQL error %ld: %s\\n", code, response.ptr);
        exit(EXIT_FAILURE);
    }

    printf("GraphQL Response: %s\\n", response.ptr);

    curl_easy_cleanup(curl);
    curl_slist_free_all(hdrs);
    free(response.ptr);
}

/* ---- Step 3: Verify JWT Signature ------------------------------------- */
static int verify_jwt(const char *jwt_b64) {
    /* Split the token by dots */
    char *token = strdup(jwt_b64);
    char *header = strsep(&token, ".");
    char *payload = strsep(&token, ".");
    char *signature = token;

    if (!header || !payload || !signature) {
        fprintf(stderr, "Malformed JWT\\n");
        return 0;
    }

    /* Recreate signed data */
    char *signed_data;
    asprintf(&signed_data, "%s.%s", header, payload);

    /* Base64url-decode signature */
    BIO *b64 = BIO_new(BIO_f_base64());
    BIO_set_flags(b64, BIO_FLAGS_BASE64_NO_NL);
    BIO *bio = BIO_new_mem_buf(signature, -1);
    bio = BIO_push(b64, bio);
    unsigned char sigbuf[512];
    int siglen = BIO_read(bio, sigbuf, sizeof(sigbuf));
    BIO_free_all(bio);

    /* Download JWKs on first run (skipped: cache to disk) */
    /* ... For brevity, we load a local public key file ... */
    FILE *fp = fopen("gateway_public.pem", "r");
    if (!fp) {
        perror("fopen public key");
        return 0;
    }
    EVP_PKEY *pkey = PEM_read_PUBKEY(fp, NULL, NULL, NULL);
    fclose(fp);

    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    EVP_PKEY_CTX *pkctx = NULL;
    if (!EVP_DigestVerifyInit(ctx, &pkctx, EVP_sha256(), NULL, pkey)) {
        fprintf(stderr, "DigestVerifyInit failed\\n");
        return 0;
    }
    if (!EVP_DigestVerifyUpdate(ctx, signed_data, strlen(signed_data))) {
        fprintf(stderr, "DigestVerifyUpdate failed\\n");
        return 0;
    }
    int ok = EVP_DigestVerifyFinal(ctx, sigbuf, siglen);
    EVP_MD_CTX_free(ctx);
    EVP_PKEY_free(pkey);
    free(signed_data);

    return ok == 1;
}

/* ---- Main ------------------------------------------------------------- */
int main(void) {
    curl_global_init(CURL_GLOBAL_DEFAULT);

    char *token = obtain_access_token();
    printf("Obtained token (truncated): %.32s...\\n", token);

    if (!verify_jwt(token)) {
        fprintf(stderr, "Token signature invalid!\\n");
        exit(EXIT_FAILURE);
    }
    printf("JWT verified successfully.\\n");

    call_graphql(token);

    /* Clean up */
    size_t tok_len = strlen(token);
    memset(token, 0, tok_len);
    munlock(token, tok_len);
    free(token);

    curl_global_cleanup();
    return EXIT_SUCCESS;
}
```

---

## 6. Error Codes

HTTP | JSON Code | When it happens                        | Suggested Remedy
-----|-----------|----------------------------------------|-----------------
401  | `E40101`  | Missing `Authorization` header         | Attach bearer token
401  | `E40102`  | Token expired                          | Refresh & retry
401  | `E40103`  | Scope insufficient                     | Request with broader scope
403  | `E40310`  | API Key revoked                        | Issue new key
429  | `E42900`  | Rate-limit exceeded                    | Back-off, exponential retry
5xx  | `E5xxx`   | Gateway/service error                  | Retry w/ jitter

---

## 7. Best Practices

* Always request the **least** scope necessary  
* Cache JWKs & refresh every `Cache-Control` max-age  
* Prefer **short-lived** tokens; rotate keys every 90 days  
* Use `mlock()`/`mprotect(PROT_NONE)` for in-memory secrets  
* Pin TLS certificates for kiosk deployments  
* Log only the first 6 bytes of tokens (`tok-hash`) for diagnostics  

---

## 8. FAQ

**Q:** “Do I need a separate token per microservice?”  
**A:** No. Obtain one token and forward it through the gateway; internal services perform an extra mTLS hop.

**Q:** “Can I disable JWT verification in development?”  
**A:** Yes, set `SYNCANVAS_SKIP_JWT_VERIFY=1`; never enable this in prod.

**Q:** “Where can I find SDKs?”  
**A:** Official C, Rust, and TypeScript SDKs are released on GitHub under the `@synesthetic` namespace.

---

© 2024 SynestheticCanvas LLC — All rights reserved.
```