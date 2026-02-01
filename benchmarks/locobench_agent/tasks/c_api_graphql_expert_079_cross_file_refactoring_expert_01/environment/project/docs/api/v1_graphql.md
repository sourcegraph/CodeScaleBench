```markdown
# SynestheticCanvas API Suite — GraphQL v1  
*File: `docs/api/v1_graphql.md`*  
*Last-Updated: 2024-05-01*  

> “Every endpoint is a brush stroke.”

---

## Table&nbsp;of&nbsp;Contents
1. Introduction  
2. Getting Started
3. HTTP Endpoint
4. Authentication
5. GraphQL Schema (v1.0.0)
6. Queries
    1. `palette`
    2. `texture`
    3. `timeline`
7. Mutations
    1. `createPalette`
    2. `synthesizeTexture`
8. Pagination
9. Error Handling
10. C Client Examples
11. Changelog

---

## 1. Introduction
`v1_graphql` exposes a unified, color-coded GraphQL interface that lets you orchestrate real-time media across the SynestheticCanvas micro-service constellation. Version **1.0.0** bundles:

* Palette service (`svc_palette`)
* Dynamic texture synthesis service (`svc_texture`)
* Timeline sequencer (`svc_timeline`)
* Global rate-limited caching

---

## 2. Getting Started
All requests must be `POST`ed with a JSON body containing at least the `query` field. Recommended HTTP headers:

```
Content-Type: application/json
Accept: application/json
Authorization: Bearer <JWT|API_KEY>
X-SC-Version: 1
```

---

## 3. HTTP Endpoint
```
https://gateway.synestheticcanvas.io/graphql
```

---

## 4. Authentication

| Target Environment | Auth Mechanism             | Notes                                    |
| ------------------ | -------------------------- | ---------------------------------------- |
| Production         | JWT (OAuth 2.0 / OIDC)    | `exp ≤ 15 min`, refresh via `/auth/refresh` |
| Dev / CI           | Static API Key            | Provisioned per-project                  |

Both tokens must be passed in the `Authorization` header using the `Bearer` scheme.

---

## 5. GraphQL Schema (v1.0.0)

```graphql
schema {
  query: Query
  mutation: Mutation
}

"Root queries."
type Query {
  palette(id: ID!): Palette!
  texture(id: ID!): Texture!
  timeline(cursor: CursorInput): TimelineConnection!
}

"Root mutations."
type Mutation {
  createPalette(input: CreatePaletteInput!): Palette!
  synthesizeTexture(input: SynthesizeTextureInput!): Texture!
}

"Palette: a color collection."
type Palette {
  id: ID!
  title: String!
  createdAt: Timestamp!
  swatches: [Swatch!]!
}

"Texture: GPU-rasterized procedural bitmap."
type Texture {
  id: ID!
  name: String!
  url: URL!
  paletteId: ID!
  synthesizedAt: Timestamp!
}

"Relay-style cursor connection for timelines."
type TimelineConnection {
  nodes: [TimelineItem!]!
  pageInfo: PageInfo!
}

type PageInfo {
  hasNextPage: Boolean!
  endCursor: String
}

input CursorInput {
  after: String
  limit: Int = 50
}

input CreatePaletteInput {
  title: String!
  swatches: [String!]! # hex codes
}

input SynthesizeTextureInput {
  name: String!
  algorithm: String! # e.g. "noise_perlin"
  paletteId: ID!
}
```

Complete & version-locked introspection JSON is available at  
`https://gateway.synestheticcanvas.io/schema/v1/introspection.json`.

---

## 6. Queries

### 6.1 `palette`
Retrieve a palette by ID.

```graphql
query GetPalette($id: ID!) {
  palette(id: $id) {
    id
    title
    swatches
    createdAt
  }
}
```

Variables:

```json
{ "id": "pal_24b9dd54" }
```

### 6.2 `texture`
Fetch a previously synthesized texture.

```graphql
query GetTexture($id: ID!) {
  texture(id: $id) {
    id
    name
    url
    paletteId
    synthesizedAt
  }
}
```

### 6.3 `timeline`
Paging through recent textures & palettes combined.

```graphql
query GetTimeline($cursor: CursorInput) {
  timeline(cursor: $cursor) {
    nodes {
      ... on Palette {
        id
        title
      }
      ... on Texture {
        id
        name
        url
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
```

---

## 7. Mutations

### 7.1 `createPalette`

```graphql
mutation CreatePalette($input: CreatePaletteInput!) {
  createPalette(input: $input) {
    id
    title
  }
}
```

Variables:

```json
{
  "input": {
    "title": "Midnight Neon",
    "swatches": ["#050014", "#27005D", "#9400FF", "#AED2FF", "#41C9E2"]
  }
}
```

### 7.2 `synthesizeTexture`

```graphql
mutation SynthesizeTexture($input: SynthesizeTextureInput!) {
  synthesizeTexture(input: $input) {
    id
    name
    url
  }
}
```

---

## 8. Pagination
The API implements Relay-style cursors. Provide `after` and optionally `limit` (max 250). Omitted cursors default to the first page.

```graphql
query ($cursor: CursorInput) {
  timeline(cursor: $cursor) {
    nodes { id }
    pageInfo { endCursor hasNextPage }
  }
}
```

---

## 9. Error Handling

Error objects comply with the following format:

```json
{
  "errors": [
    {
      "message": "Palette not found",
      "extensions": {
        "code": "NOT_FOUND",
        "timestamp": "2024-05-01T14:58:22Z",
        "path": "palette",
        "correlationId": "02e4adc5-8c6b-4b49-a891-1fc12ffc6797"
      }
    }
  ]
}
```

* `code` enumerations: `UNAUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`, `VALIDATION_FAILED`, `INTERNAL_SERVER_ERROR`  
* `correlationId` echoes back the gateway’s request UUID, enabling distributed tracing.

---

## 10. C Client Examples

Below are self-contained, production-ready snippets using `libcurl` and `jansson`.  
Each function is intentionally small for clarity and unit-testability.

> Compile with:  
> `cc -Wall -Wextra -pedantic -std=c17 -lcurl -ljansson -o sc_client sc_client.c`

```c
/* sc_client.c — minimal GraphQL client for SynestheticCanvas */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <curl/curl.h>
#include <jansson.h>

/*----------- Constants ----------------------------------------------------*/
static const char *SC_ENDPOINT = "https://gateway.synestheticcanvas.io/graphql";
static const char *SC_VERSION  = "1";

/*----------- Utilities ----------------------------------------------------*/
struct memory {
    char *data;
    size_t size;
};

static size_t on_write(void *ptr, size_t size, size_t nmemb, void *userdata)
{
    size_t real = size * nmemb;
    struct memory *mem = userdata;

    char *tmp = realloc(mem->data, mem->size + real + 1);
    if (!tmp) return 0; /* Out of memory */
    mem->data = tmp;

    memcpy(&(mem->data[mem->size]), ptr, real);
    mem->size += real;
    mem->data[mem->size] = '\0';
    return real;
}

/*----------- Error helpers ------------------------------------------------*/
static void die(const char *msg)
{
    fprintf(stderr, "fatal: %s\n", msg);
    exit(EXIT_FAILURE);
}

/*----------- Core logic ---------------------------------------------------*/
static json_t *sc_graphql_post(const char *query, json_t *variables,
                               const char *token)
{
    CURL *curl = curl_easy_init();
    if (!curl) die("curl init failed");

    /* Build JSON payload */
    json_t *root = json_object();
    json_object_set_new(root, "query", json_string(query));
    if (variables)
        json_object_set(root, "variables", variables);

    char *payload = json_dumps(root, JSON_COMPACT);
    json_decref(root);

    struct curl_slist *headers = NULL;
    char auth[256] = {0};
    snprintf(auth, sizeof(auth), "Authorization: Bearer %s", token);
    headers = curl_slist_append(headers, "Content-Type: application/json");
    headers = curl_slist_append(headers, "Accept: application/json");
    headers = curl_slist_append(headers, auth);
    headers = curl_slist_append(headers, "Expect:"); /* Disable 100-continue */
    headers = curl_slist_append(headers, "User-Agent: sc-client/1.0");
    headers = curl_slist_append(headers, "X-SC-Version: 1");

    struct memory mem = {0};

    curl_easy_setopt(curl, CURLOPT_URL, SC_ENDPOINT);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, payload);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, on_write);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &mem);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 10L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 1L);

    CURLcode res = curl_easy_perform(curl);
    long status_code = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status_code);

    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
    free(payload);

    if (res != CURLE_OK)
        die(curl_easy_strerror(res));

    if (status_code != 200)
        die("non-200 HTTP status");

    /* Parse JSON */
    json_error_t err;
    json_t *json = json_loads(mem.data, 0, &err);
    free(mem.data);

    if (!json)
    {
        fprintf(stderr, "json parse error at <%d:%d>: %s\n",
                err.line, err.column, err.text);
        exit(EXIT_FAILURE);
    }
    return json;
}

/*----------- High-level API wrappers --------------------------------------*/
static void fetch_palette(const char *palette_id, const char *token)
{
    const char *query =
        "query GetPalette($id: ID!) {"
        "  palette(id: $id) { id title swatches createdAt }"
        "}";

    json_t *vars = json_pack("{s:s}", "id", palette_id);
    json_t *resp = sc_graphql_post(query, vars, token);
    json_decref(vars);

    json_t *errors = json_object_get(resp, "errors");
    if (errors)
    {
        /* Print first error */
        json_t *err0 = json_array_get(errors, 0);
        fprintf(stderr, "GraphQL error: %s\n",
                json_string_value(json_object_get(err0, "message")));
        json_decref(resp);
        return;
    }

    json_t *data = json_object_get(resp, "data");
    json_t *palette = json_object_get(data, "palette");

    printf("Palette %s — %s\n",
           json_string_value(json_object_get(palette, "id")),
           json_string_value(json_object_get(palette, "title")));

    json_t *swatches = json_object_get(palette, "swatches");
    for (size_t i = 0; i < json_array_size(swatches); ++i)
        printf("  • %s\n", json_string_value(json_array_get(swatches, i)));

    json_decref(resp);
}

/*----------- Entry point --------------------------------------------------*/
int main(int argc, char **argv)
{
    if (argc != 3)
    {
        fprintf(stderr, "usage: %s <API_TOKEN> <PALETTE_ID>\n", argv[0]);
        return EXIT_FAILURE;
    }
    fetch_palette(argv[2], argv[1]);
    return EXIT_SUCCESS;
}
```

---

## 11. Changelog

| Date       | Version | Notes                        |
| ---------- | ------- | ---------------------------- |
| 2024-05-01 | 1.0.0   | Initial public release       |
| 2024-06-07 | 1.1.0   | Added `timeline` pagination  |

---

© 2024 SynestheticCanvas. All rights reserved.
```