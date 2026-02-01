# SynestheticCanvas · Palette-Service  
Expert-level C microservice for managing dynamic color palettes in real time.

---

## 1. What this service does

`palette-service` is responsible for the entire life-cycle of a palette:

* Create / fork palettes  
* Append, remove, or reorder swatches  
* Versioning & semantic diff  
* Real-time broadcast of palette mutations to interested canvases  
* Persistent storage in PostgreSQL (JSONB + GIST for fast similarity search)

Every operation is exposed through both GraphQL *and* a REST fallback so that
upstream creative engines can keep their own stack simple.

---

## 2. Quick Start

```console
# System deps (Ubuntu ≥22.04)
sudo apt update
sudo apt install -y build-essential cmake libpq-dev libgraphqlparser-dev \
                    libjansson-dev libevent-dev

# Clone mono-repo and build only this service
git clone https://github.com/SynestheticCanvas/api_graphql.git
cd api_graphql/services/palette-service
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target palette_service

# Run migrations & start the service
./scripts/db/migrate.sh
./build/bin/palette_service
```

---

## 3. Directory layout

```
palette-service/
├── CMakeLists.txt
├── include/             <-- Public headers (service API)
├── src/
│   ├── main.c           <-- boot-straps HTTP & GraphQL servers
│   ├── service.c        <-- Service-layer (command/query separation)
│   ├── repo_pgsql.c     <-- PostgreSQL repository adapter
│   └── gql_resolvers.c  <-- GraphQL field resolvers
├── sql/                 <-- Flyway-compatible migrations
├── tests/               <-- Unit & contract tests
└── README.md            <-- You are here
```

---

## 4. Minimal, self-contained example

Below is an *extract* of the actual production code showing how a palette is
persisted using the repository pattern.  All error paths are checked and
logged; failures propagate as `SC_Status` objects that can be serialized
straight into HTTP/GraphQL error responses.

```c
/* include/palette_repo.h */
#ifndef PALETTE_REPO_H
#define PALETTE_REPO_H

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint64_t  id;
    char      name[64];
    char      author[64];
    uint32_t  version;
    size_t    color_count;
    /* 32-bit RGBA packed, max 256 colors for demo */
    uint32_t  colors[256];
} SC_Palette;

typedef enum {
    SC_OK = 0,
    SC_NOT_FOUND,
    SC_DB_ERROR,
    SC_VALIDATION_ERROR
} SC_StatusCode;

typedef struct {
    SC_StatusCode code;
    char          message[256];
} SC_Status;

typedef struct SC_PaletteRepo SC_PaletteRepo;

typedef SC_Status (*SC_CreateFn)(SC_PaletteRepo*, const SC_Palette*, uint64_t* out_id);
typedef SC_Status (*SC_FetchFn) (SC_PaletteRepo*, uint64_t id, SC_Palette* out_palette);
typedef SC_Status (*SC_UpdateFn)(SC_PaletteRepo*, const SC_Palette*);
typedef SC_Status (*SC_DeleteFn)(SC_PaletteRepo*, uint64_t id);
typedef void      (*SC_CloseFn) (SC_PaletteRepo*);

struct SC_PaletteRepo {
    void*        impl;   /* Opaque pointer */
    SC_CreateFn  create;
    SC_FetchFn   fetch;
    SC_UpdateFn  update;
    SC_DeleteFn  delete_;
    SC_CloseFn   close;
};

SC_PaletteRepo* sc_repo_pgsql_new(const char* conninfo);

#ifdef __cplusplus
}
#endif
#endif /* PALETTE_REPO_H */
```

```c
/* src/repo_pgsql.c */
#include "palette_repo.h"
#include <libpq-fe.h>
#include <jansson.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

typedef struct {
    PGconn* db;
} RepoPgSQL;

static SC_Status status_ok(void) {
    return (SC_Status){ .code = SC_OK, .message = "OK" };
}

static SC_Status status_error(SC_StatusCode code, const char* fmt, ...) {
    SC_Status s = { .code = code };
    va_list ap; va_start(ap, fmt);
    vsnprintf(s.message, sizeof s.message, fmt, ap);
    va_end(ap);
    return s;
}

static SC_Status pg_check(PGresult* res, RepoPgSQL* self) {
    if (PQresultStatus(res) != PGRES_COMMAND_OK &&
        PQresultStatus(res) != PGRES_TUPLES_OK) {
        SC_Status e = status_error(SC_DB_ERROR, "PG error: %s",
                                   PQerrorMessage(self->db));
        PQclear(res);
        return e;
    }
    return status_ok();
}

static SC_Status repo_create(SC_PaletteRepo* repo,
                             const SC_Palette* p,
                             uint64_t* out_id)
{
    RepoPgSQL* self = repo->impl;
    const char* sql =
        "INSERT INTO palettes(name, author, version, swatches) "
        "VALUES($1, $2, $3, $4::jsonb) RETURNING id;";

    /* Serialize colors to JSON array */
    json_t* jarr = json_array();
    for (size_t i = 0; i < p->color_count; ++i)
        json_array_append_new(jarr, json_integer(p->colors[i]));

    char* payload = json_dumps(jarr, 0);
    json_decref(jarr);

    const char* params[4]  = { p->name, p->author, NULL, payload };
    int         lengths[4] = { 0, 0, sizeof(uint32_t), strlen(payload) };
    int         formats[4] = { 0, 0, 1, 0 };
    uint32_t    version_n  = htonl(p->version);
    params[2]              = (char*)&version_n;

    PGresult* res = PQexecParams(self->db, sql, 4, NULL, params, lengths,
                                 formats, 0);

    free(payload);

    SC_Status st = pg_check(res, self);
    if (st.code != SC_OK) return st;

    *out_id = strtoull(PQgetvalue(res, 0, 0), NULL, 10);

    PQclear(res);
    return status_ok();
}

static SC_Status repo_fetch(SC_PaletteRepo* repo,
                            uint64_t id,
                            SC_Palette* out_p)
{
    RepoPgSQL* self = repo->impl;
    const char* sql =
        "SELECT name, author, version, swatches "
        "FROM palettes WHERE id = $1;";

    char idbuf[32];
    snprintf(idbuf, sizeof idbuf, "%llu", (unsigned long long)id);

    const char* params[1]  = { idbuf };
    PGresult* res = PQexecParams(self->db, sql, 1, NULL, params,
                                 NULL, NULL, 0);

    SC_Status st = pg_check(res, self);
    if (st.code != SC_OK) return st;

    if (PQntuples(res) == 0) {
        PQclear(res);
        return status_error(SC_NOT_FOUND, "Palette %" PRIu64 " not found", id);
    }

    strncpy(out_p->name, PQgetvalue(res, 0, 0), sizeof out_p->name);
    strncpy(out_p->author, PQgetvalue(res, 0, 1), sizeof out_p->author);
    out_p->version = (uint32_t)strtoul(PQgetvalue(res, 0, 2), NULL, 10);

    /* Parse swatches JSON */
    json_error_t je;
    json_t* sw = json_loads(PQgetvalue(res, 0, 3), 0, &je);
    if (!sw || !json_is_array(sw)) {
        json_decref(sw);
        PQclear(res);
        return status_error(SC_DB_ERROR, "Invalid swatches JSON");
    }

    out_p->color_count = json_array_size(sw);
    for (size_t i = 0; i < out_p->color_count; ++i)
        out_p->colors[i] = (uint32_t)json_integer_value(json_array_get(sw, i));

    json_decref(sw);
    PQclear(res);
    return status_ok();
}

static SC_Status repo_update(SC_PaletteRepo* repo,
                             const SC_Palette* p)
{
    RepoPgSQL* self = repo->impl;
    const char* sql =
        "UPDATE palettes SET name = $2, author = $3, version = $4, "
        "swatches = $5::jsonb WHERE id = $1;";

    json_t* jarr = json_array();
    for (size_t i = 0; i < p->color_count; ++i)
        json_array_append_new(jarr, json_integer(p->colors[i]));
    char* payload = json_dumps(jarr, 0);
    json_decref(jarr);

    char idbuf[32];
    snprintf(idbuf, sizeof idbuf, "%llu", (unsigned long long)p->id);

    uint32_t v_n = htonl(p->version);
    const char* params[5]  = { idbuf, p->name, p->author, (char*)&v_n, payload };
    int         lengths[5] = { 0, 0, 0, sizeof(uint32_t), strlen(payload) };
    int         formats[5] = { 0, 0, 0, 1, 0 };

    PGresult* res = PQexecParams(self->db, sql, 5, NULL, params,
                                 lengths, formats, 0);

    free(payload);
    SC_Status st = pg_check(res, self);
    PQclear(res);
    return st;
}

static SC_Status repo_delete(SC_PaletteRepo* repo, uint64_t id)
{
    RepoPgSQL* self = repo->impl;
    const char* sql = "DELETE FROM palettes WHERE id = $1;";
    char idbuf[32];
    snprintf(idbuf, sizeof idbuf, "%llu", (unsigned long long)id);

    PGresult* res = PQexecParams(self->db, sql, 1, NULL,
                                 (const char* const[]){ idbuf },
                                 NULL, NULL, 0);

    SC_Status st = pg_check(res, self);
    if (st.code == SC_OK && PQcmdTuples(res)[0] == '0')
        st = status_error(SC_NOT_FOUND, "Palette %" PRIu64 " not found", id);

    PQclear(res);
    return st;
}

static void repo_close(SC_PaletteRepo* repo)
{
    RepoPgSQL* self = repo->impl;
    if (self->db) PQfinish(self->db);
    free(self);
    free(repo);
}

SC_PaletteRepo* sc_repo_pgsql_new(const char* conninfo)
{
    PGconn* db = PQconnectdb(conninfo);
    if (PQstatus(db) != CONNECTION_OK) {
        fprintf(stderr, "[palette_repo] Connection failed: %s\n",
                PQerrorMessage(db));
        PQfinish(db); return NULL;
    }

    RepoPgSQL* impl = calloc(1, sizeof *impl);
    impl->db = db;

    SC_PaletteRepo* repo = calloc(1, sizeof *repo);
    repo->impl   = impl;
    repo->create = repo_create;
    repo->fetch  = repo_fetch;
    repo->update = repo_update;
    repo->delete_= repo_delete;
    repo->close  = repo_close;

    return repo;
}
```

---

## 5. GraphQL schema excerpt

```graphql
type Palette @key(fields: "id") {
  id:        ID!
  name:      String!
  author:    String!
  version:   Int!
  colors:    [Hex!]!
  createdAt: Timestamp!
  updatedAt: Timestamp!
}

extend type Query {
  palette(id: ID!): Palette
  palettes(limit: Int = 50, cursor: ID): PaletteConnection!
}

extend type Mutation {
  createPalette(input: PaletteInput!): Palette!
  updatePalette(id: ID!, input: PaletteInput!): Palette!
  deletePalette(id: ID!): Boolean!
}
```

Every GraphQL field maps to a C function in `src/gql_resolvers.c`; the compile-time
code-gen tool `sc-gqlc` converts SDL into strongly-typed signatures, meaning
there is zero runtime reflection overhead.

---

## 6. REST endpoints

| Verb | Path                 | Description                |
|------|----------------------|----------------------------|
| GET  | /palettes            | List palettes              |
| GET  | /palettes/{id}       | Fetch single palette       |
| POST | /palettes            | Create palette             |
| PUT  | /palettes/{id}       | Update palette             |
| DELETE|/palettes/{id}       | Delete palette             |

All endpoints return RFC 7807 problem-details on errors.

---

## 7. Configuration & Environment

| Variable                 | Default         | Meaning                                       |
|--------------------------|-----------------|-----------------------------------------------|
| `SC_PG_CONN`             | `host=localhost`| libpq connection string                       |
| `SC_HTTP_PORT`           | `8085`          | Port for REST server                          |
| `SC_GQL_PORT`            | `8086`          | Port for GraphQL server (WebSocket enabled)   |
| `SC_LOG_LEVEL`           | `info`          | trace/debug/info/warn/error                   |
| `SC_MAX_PALETTE_SIZE`    | `256`           | Safeguard against abusive gigantic palettes   |
| `SC_RATE_LIMIT_RPS`      | `100`           | Requests per second, per client IP            |

---

## 8. Testing

```console
cmake --build build --target test     # Unit tests (CTest + Check)
python3 contract_tests/rest_contract.py  # Pact-style contract tests
```

---

## 9. Security

* Prepared statements everywhere → immune to SQL injection  
* Input validation at HTTP + GraphQL layers (color values, array bounds, names)  
* Rate limiting (`libevent` token-bucket) and optional JWT auth middleware  

---

## 10. License

MIT © 2024 SynestheticCanvas Contributors