```c
/**
 * EduPay Ledger Academy
 * File:    src/core/event_sourcing/event.h
 * Author:  EduPay Engineering Team
 * License: MIT
 *
 * Description:
 *   Core Event-Sourcing abstraction shared across all bounded contexts.
 *   Because the core domain must remain framework-agnostic, this header
 *   limits itself to the C standard library.  Adapters (Kafka, NATS, AMQP,
 *   flat-file journaling, etc.) are expected to translate `event_t` into
 *   their respective wire formats.
 *
 *   The implementation is deliberately kept header-only (using `static
 *   inline` where appropriate) to simplify distribution in academic
 *   settings—professors can drop this file into unit-test projects without
 *   linking against a separate binary.
 */

#ifndef EDUPAY_LEDGER_ACADEMY_EVENT_H
#define EDUPAY_LEDGER_ACADEMY_EVENT_H

#ifdef __cplusplus
extern "C" {
#endif

/* ────────────────────────────────────────────────────────────────────────── */
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <stdio.h>

/* ────────────────────────────────────────────────────────────────────────── */
/* Constants                                                                 */

#define EVENT_UUID_STRLEN        37u   /* 36 chars + NUL                      */
#define EVENT_TYPE_STRLEN        64u
#define EVENT_TENANT_STRLEN      32u
#define EVENT_MAX_PAYLOAD_BYTES  4096u /* Upper-bound for in-memory payload   */
#define EVENT_WIRE_MAGIC         0xEDUPA7Au /* used in binary serialization  */

/* ────────────────────────────────────────────────────────────────────────── */
/* Error codes                                                               */

typedef enum
{
    EVENT_OK = 0,
    EVENT_ERR_INVALID_ARGUMENT,
    EVENT_ERR_OOM,
    EVENT_ERR_BUFFER_TOO_SMALL,
    EVENT_ERR_SERIALIZATION,
    EVENT_ERR_DESERIALIZATION,
} event_rc_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Event metadata                                                            */

typedef struct
{
    char      id[EVENT_UUID_STRLEN];        /* Event GUID                       */
    char      aggregate_id[EVENT_UUID_STRLEN];
    char      tenant_id[EVENT_TENANT_STRLEN];
    char      type[EVENT_TYPE_STRLEN];      /* Business type (“PAYMENT_INIT”)   */
    uint64_t  sequence;                     /* monotonically-increasing         */
    uint16_t  version;                      /* schema version for up-casting    */
    time_t    timestamp;                    /* UTC                              */
} event_meta_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Event                                                                     */

typedef struct
{
    event_meta_t meta;
    uint8_t      *payload;     /* opaque business payload                   */
    size_t        payload_len;
    bool          owns_payload;/* whether to free() on destroy              */
} event_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* API                                                                       */

/**
 * Generates a RFC-4122 UUIDv4 string (NUL-terminated).
 * out must point to a buffer of at least EVENT_UUID_STRLEN bytes.
 */
static inline event_rc_t
event_uuid4(char out[EVENT_UUID_STRLEN])
{
    if (!out) return EVENT_ERR_INVALID_ARGUMENT;

    const char *hex = "0123456789abcdef";
    uint8_t rnd[16];

    /* Cheap non-cryptographic PRNG suitable for test rigs only.              */
    for (size_t i = 0; i < sizeof rnd; ++i)
        rnd[i] = (uint8_t)(rand() & 0xFF);

    /* Set version(4) and variant(10) bits per RFC-4122                       */
    rnd[6] = (rnd[6] & 0x0F) | 0x40;
    rnd[8] = (rnd[8] & 0x3F) | 0x80;

    size_t p = 0;
    for (size_t i = 0; i < sizeof rnd; ++i)
    {
        out[p++] = hex[rnd[i] >> 4];
        out[p++] = hex[rnd[i] & 0x0F];

        if (p == 8 || p == 13 || p == 18 || p == 23)
            out[p++] = '-';
    }
    out[p] = '\0';
    return EVENT_OK;
}

/**
 * Allocates and initializes a new event.  The payload is copied into an owned
 * buffer; callers may free their original memory after this call returns.
 */
static inline event_t *
event_new(const char       *type,
          const char       *aggregate_id,
          const void       *payload,
          size_t            payload_len,
          uint16_t          version,
          const char       *tenant_id,
          event_rc_t       *o_rc)
{
    if (!type || !aggregate_id ||
        payload_len > EVENT_MAX_PAYLOAD_BYTES)
    {
        if (o_rc) *o_rc = EVENT_ERR_INVALID_ARGUMENT;
        return NULL;
    }

    event_t *ev = (event_t *)calloc(1, sizeof *ev);
    if (!ev)
    {
        if (o_rc) *o_rc = EVENT_ERR_OOM;
        return NULL;
    }

    /* Fill metadata                                                          */
    event_uuid4(ev->meta.id);
    strncpy(ev->meta.aggregate_id, aggregate_id, EVENT_UUID_STRLEN - 1);
    strncpy(ev->meta.type, type, EVENT_TYPE_STRLEN - 1);
    strncpy(ev->meta.tenant_id,
            tenant_id ? tenant_id : "default",
            EVENT_TENANT_STRLEN - 1);
    ev->meta.sequence  = 0;  /* sequence assigned by store/stream            */
    ev->meta.version   = version;
    ev->meta.timestamp = time(NULL);

    /* Copy payload                                                           */
    if (payload_len)
    {
        ev->payload = (uint8_t *)malloc(payload_len);
        if (!ev->payload)
        {
            free(ev);
            if (o_rc) *o_rc = EVENT_ERR_OOM;
            return NULL;
        }

        memcpy(ev->payload, payload, payload_len);
        ev->payload_len  = payload_len;
        ev->owns_payload = true;
    }

    if (o_rc) *o_rc = EVENT_OK;
    return ev;
}

/**
 * Releases all dynamic allocations owned by the event.
 */
static inline void
event_free(event_t *ev)
{
    if (!ev) return;
    if (ev->owns_payload)
        free(ev->payload);
    free(ev);
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Binary serialization format                                               *
 *  +------------+--------------------------------------------------------+
 *  | Field      | Bytes                                                 |
 *  +------------+--------------------------------------------------------+
 *  | magic      | 4  (0xEDUPA7A)                                        |
 *  | meta       | sizeof(event_meta_t) (padded with NULs)               |
 *  | payloadLen | 4 (uint32 LE)                                        |
 *  | payload    | N bytes                                              |
 *  +--------------------------------------------------------------------+
 */

static inline size_t
event_calc_wire_size(const event_t *ev)
{
    return sizeof(uint32_t) +                  /* magic                */
           sizeof(event_meta_t) +
           sizeof(uint32_t) +                  /* payloadLen           */
           ev->payload_len;
}

static inline event_rc_t
event_serialize(const event_t *ev,
                uint8_t       *buffer,
                size_t        *inout_len)   /* in: buffer size, out: bytes used */
{
    if (!ev || !buffer || !inout_len)
        return EVENT_ERR_INVALID_ARGUMENT;

    size_t needed = event_calc_wire_size(ev);
    if (*inout_len < needed)
    {
        *inout_len = needed;
        return EVENT_ERR_BUFFER_TOO_SMALL;
    }

    uint8_t *p = buffer;

    /* magic                                                                  */
    uint32_t magic = EVENT_WIRE_MAGIC;
    memcpy(p, &magic, sizeof magic);      p += sizeof magic;

    /* metadata (raw POD copy, relies on stable layout)                       */
    memcpy(p, &ev->meta, sizeof ev->meta); p += sizeof ev->meta;

    /* payload                                                                */
    uint32_t len32 = (uint32_t)ev->payload_len;
    memcpy(p, &len32, sizeof len32);      p += sizeof len32;

    if (ev->payload_len)
    {
        memcpy(p, ev->payload, ev->payload_len);
        p += ev->payload_len;
    }

    *inout_len = (size_t)(p - buffer);
    return EVENT_OK;
}

static inline event_rc_t
event_deserialize(event_t   *ev,           /* must be zero-initialized */
                  const uint8_t *buffer,
                  size_t         buf_len)
{
    if (!ev || !buffer)
        return EVENT_ERR_INVALID_ARGUMENT;

    const uint8_t *p = buffer;

    if (buf_len < sizeof(uint32_t) + sizeof(event_meta_t) + sizeof(uint32_t))
        return EVENT_ERR_DESERIALIZATION;

    /* magic                                                                  */
    uint32_t magic;
    memcpy(&magic, p, sizeof magic);        p += sizeof magic;
    if (magic != EVENT_WIRE_MAGIC)
        return EVENT_ERR_DESERIALIZATION;

    /* metadata                                                               */
    memcpy(&ev->meta, p, sizeof ev->meta);  p += sizeof ev->meta;

    /* payload length                                                         */
    uint32_t len32;
    memcpy(&len32, p, sizeof len32);        p += sizeof len32;

    if (len32 > EVENT_MAX_PAYLOAD_BYTES ||
        (size_t)(buf_len - (p - buffer)) < len32)
        return EVENT_ERR_DESERIALIZATION;

    if (len32)
    {
        ev->payload = (uint8_t *)malloc(len32);
        if (!ev->payload)
            return EVENT_ERR_OOM;

        memcpy(ev->payload, p, len32);
        ev->payload_len  = len32;
        ev->owns_payload = true;
    }

    return EVENT_OK;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Debug helpers                                                             */

static inline void
event_print(const event_t *ev, FILE *out)
{
    if (!ev) return;
    if (!out) out = stdout;

    char timebuf[32];
    struct tm tm_utc;
#if defined(_MSC_VER)
    gmtime_s(&tm_utc, &ev->meta.timestamp);
#else
    gmtime_r(&ev->meta.timestamp, &tm_utc);
#endif
    strftime(timebuf, sizeof timebuf, "%Y-%m-%dT%H:%M:%SZ", &tm_utc);

    fprintf(out,
            "Event {\n"
            "  id           : %s\n"
            "  aggregate_id : %s\n"
            "  tenant_id    : %s\n"
            "  type         : %s\n"
            "  seq          : %llu\n"
            "  version      : %u\n"
            "  timestamp    : %s\n"
            "  payload_len  : %zu\n"
            "}\n",
            ev->meta.id,
            ev->meta.aggregate_id,
            ev->meta.tenant_id,
            ev->meta.type,
            (unsigned long long)ev->meta.sequence,
            ev->meta.version,
            timebuf,
            ev->payload_len);
}

/* ────────────────────────────────────────────────────────────────────────── */
#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* EDUPAY_LEDGER_ACADEMY_EVENT_H */
```