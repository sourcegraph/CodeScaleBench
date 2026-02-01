/*
 * EduPay Ledger Academy
 * File: projections_service/event_handlers/dashboard_projector.c
 *
 * Description:
 *   Dashboard projector responsible for building the real-time read-model that
 *   powers the instructor/student analytics dashboard.  The projector consumes
 *   immutable domain events from the event-bus and updates aggregated KPI’s
 *   such as total tuition collected, payment counts, pending settlements, and
 *   open fraud alerts.  The component is written in C following Clean
 *   Architecture guidelines so that higher layers (REST, gRPC, GraphQL, etc.)
 *   can query the materialized view without coupling to the write-side or to
 *   any framework.
 *
 *   The projection state is persisted to a pluggable store; a lightweight
 *   POSIX-file implementation is provided for coursework convenience but can be
 *   replaced with SQLite, Redis, or cloud storage by swapping the v-table.
 *
 *   Thread-safety is guaranteed via a coarse mutex because projections are
 *   write-heavy and latency-tolerant relative to OLTP processing.
 *
 * Author: EduPay Core Engineering Team
 */

#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/* ────────────────────────────────────────────────────────────────────────── */
/*                                   Macros                                  */
/* ────────────────────────────────────────────────────────────────────────── */

#ifndef DASHBOARD_PROJECTOR_LOG
#define DASHBOARD_PROJECTOR_LOG(fmt, ...)                                                   \
    do {                                                                                    \
        fprintf(stderr, "[DASHBOARD_PROJECTOR] %s:%d: " fmt "\n", __FILE__, __LINE__,       \
                ##__VA_ARGS__);                                                             \
    } while (0)
#endif

#define FILE_MAGIC "EDUPAY_DASHBD_V1" /* 16 bytes incl. NUL */
#define DEFAULT_SNAPSHOT_FILE "dashboard.snapshot"

/* ────────────────────────────────────────────────────────────────────────── */
/*                          Forward Declarations                             */
/* ────────────────────────────────────────────────────────────────────────── */

struct projection_store;

/* ────────────────────────────────────────────────────────────────────────── */
/*                              Event Section                                */
/* ────────────────────────────────────────────────────────────────────────── */

/*
 * The write-side emits events in canonical UoW order with monotonic sequence
 * numbers (can be the commit-log offset or ULID).  Only the subset consumed by
 * this projection is modeled below to keep the file self-contained.
 */

typedef enum {
    EVENT_PAYMENT_INITIATED = 1,
    EVENT_PAYMENT_SETTLED   = 2,
    EVENT_FRAUD_ALERT       = 3,
} domain_event_type_t;

typedef struct {
    domain_event_type_t type;
    uint64_t            sequence_number; /* global ordering */
    union {
        struct {
            double amount;
        } payment_initiated;

        struct {
            double amount;
            int    success; /* 1 = settled, 0 = failed/reversed */
        } payment_settled;

        struct {
            char student_id[32];
        } fraud_alert;
    } data;
} domain_event_t;

/* ────────────────────────────────────────────────────────────────────────── */
/*                           Projection Snapshot                             */
/* ────────────────────────────────────────────────────────────────────────── */

typedef struct {
    double   total_tuition;
    uint64_t total_payments;
    uint64_t pending_payments;
    uint64_t fraud_alerts;
    uint64_t last_sequence_number;
} dashboard_snapshot_t;

/* ────────────────────────────────────────────────────────────────────────── */
/*                            Store Interface                                */
/* ────────────────────────────────────────────────────────────────────────── */

typedef struct projection_store {
    int (*save)(struct projection_store *self,
                const dashboard_snapshot_t *snapshot);
    int (*load)(struct projection_store *self, dashboard_snapshot_t *snapshot);
    void (*destroy)(struct projection_store *self);
} projection_store_t;

/* ────────────────────────────────────────────────────────────────────────── */
/*                       File-based Store (default)                          */
/* ────────────────────────────────────────────────────────────────────────── */

typedef struct {
    projection_store_t iface;
    char               filepath[256];
} file_projection_store_t;

static int file_store_save(projection_store_t *base,
                           const dashboard_snapshot_t *snapshot) {
    file_projection_store_t *self = (file_projection_store_t *)base;
    FILE *                   fp   = fopen(self->filepath, "wb");
    if (!fp) {
        DASHBOARD_PROJECTOR_LOG("Failed to open snapshot file for writing: %s",
                                strerror(errno));
        return -1;
    }

    /* Write header so that older snapshots are rejected on format upgrade */
    if (fwrite(FILE_MAGIC, 1, sizeof(FILE_MAGIC), fp) != sizeof(FILE_MAGIC)) {
        DASHBOARD_PROJECTOR_LOG("Failed to write file magic");
        fclose(fp);
        return -1;
    }

    if (fwrite(snapshot, sizeof(*snapshot), 1, fp) != 1) {
        DASHBOARD_PROJECTOR_LOG("Failed to write snapshot");
        fclose(fp);
        return -1;
    }

    fflush(fp);
    fclose(fp);
    return 0;
}

static int file_store_load(projection_store_t *base,
                           dashboard_snapshot_t *snapshot) {
    file_projection_store_t *self = (file_projection_store_t *)base;
    FILE *                   fp   = fopen(self->filepath, "rb");
    if (!fp) {
        if (errno != ENOENT) {
            DASHBOARD_PROJECTOR_LOG("Failed to open snapshot file for reading: "
                                    "%s",
                                    strerror(errno));
            return -1;
        }
        /* File does not exist: treat as fresh start. */
        memset(snapshot, 0, sizeof(*snapshot));
        return 0;
    }

    char magic[sizeof(FILE_MAGIC)];
    if (fread(magic, 1, sizeof(magic), fp) != sizeof(magic) ||
        memcmp(magic, FILE_MAGIC, sizeof(FILE_MAGIC)) != 0) {
        DASHBOARD_PROJECTOR_LOG("Snapshot file missing magic header – ignoring");
        fclose(fp);
        memset(snapshot, 0, sizeof(*snapshot));
        return 0;
    }

    if (fread(snapshot, sizeof(*snapshot), 1, fp) != 1) {
        DASHBOARD_PROJECTOR_LOG("Corrupted snapshot – starting from scratch");
        memset(snapshot, 0, sizeof(*snapshot));
        fclose(fp);
        return 0;
    }

    fclose(fp);
    return 0;
}

static void file_store_destroy(projection_store_t *base) {
    free(base);
}

static projection_store_t *file_store_create(const char *filepath) {
    file_projection_store_t *self = calloc(1, sizeof(*self));
    if (!self) {
        return NULL;
    }

    snprintf(self->filepath, sizeof(self->filepath), "%s",
             filepath ? filepath : DEFAULT_SNAPSHOT_FILE);

    self->iface.save    = file_store_save;
    self->iface.load    = file_store_load;
    self->iface.destroy = file_store_destroy;
    return &self->iface;
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                           Projector Context                                */
/* ────────────────────────────────────────────────────────────────────────── */

typedef struct {
    dashboard_snapshot_t state;
    projection_store_t  *store;
    pthread_mutex_t      mtx;
} dashboard_projector_t;

/* ────────────────────────────────────────────────────────────────────────── */
/*                           Public Functions                                 */
/* ────────────────────────────────────────────────────────────────────────── */

/*
 * projector_create
 *   Allocates a new projector and hydrates its state from the store.
 *
 *   Returns NULL on allocation or persistence failure.
 */
dashboard_projector_t *
dashboard_projector_create(projection_store_t *store) {
    if (!store) {
        store = file_store_create(NULL);
        if (!store) {
            return NULL;
        }
    }

    dashboard_projector_t *proj = calloc(1, sizeof(*proj));
    if (!proj) {
        store->destroy(store);
        return NULL;
    }

    proj->store = store;
    pthread_mutex_init(&proj->mtx, NULL);

    /* Load existing snapshot, if any */
    if (store->load(store, &proj->state) != 0) {
        DASHBOARD_PROJECTOR_LOG("Failed to load snapshot – aborting");
        pthread_mutex_destroy(&proj->mtx);
        store->destroy(store);
        free(proj);
        return NULL;
    }

    return proj;
}

/*
 * projector_destroy
 *   Persists the final state and frees resources.
 */
void dashboard_projector_destroy(dashboard_projector_t *proj) {
    if (!proj) {
        return;
    }

    pthread_mutex_lock(&proj->mtx);
    proj->store->save(proj->store, &proj->state);
    pthread_mutex_unlock(&proj->mtx);

    proj->store->destroy(proj->store);
    pthread_mutex_destroy(&proj->mtx);
    free(proj);
}

/*
 * dashboard_projector_snapshot
 *   Returns a copy of the current read-model for external queries.
 *   Caller owns the return value.
 */
dashboard_snapshot_t
dashboard_projector_snapshot(dashboard_projector_t *proj) {
    dashboard_snapshot_t copy;
    pthread_mutex_lock(&proj->mtx);
    memcpy(&copy, &proj->state, sizeof(copy));
    pthread_mutex_unlock(&proj->mtx);
    return copy;
}

/*
 * dashboard_projector_handle
 *   Consumes a domain event and mutates the projection atomically.
 */
int dashboard_projector_handle(dashboard_projector_t *proj,
                               const domain_event_t *event) {
    if (!proj || !event) {
        return -1;
    }

    pthread_mutex_lock(&proj->mtx);

    /* Ensure idempotency */
    if (event->sequence_number <= proj->state.last_sequence_number) {
        pthread_mutex_unlock(&proj->mtx);
        return 0;
    }

    switch (event->type) {
    case EVENT_PAYMENT_INITIATED:
        proj->state.total_payments++;
        proj->state.pending_payments++;
        break;

    case EVENT_PAYMENT_SETTLED:
        if (proj->state.pending_payments > 0) {
            proj->state.pending_payments--;
        }
        if (event->data.payment_settled.success) {
            proj->state.total_tuition +=
                event->data.payment_settled.amount;
        }
        break;

    case EVENT_FRAUD_ALERT:
        proj->state.fraud_alerts++;
        break;

    default:
        DASHBOARD_PROJECTOR_LOG("Unknown event type: %d", event->type);
        break;
    }

    proj->state.last_sequence_number = event->sequence_number;

    /* Best-effort persistence; if it fails we keep working but log an error */
    if (proj->store->save(proj->store, &proj->state) != 0) {
        DASHBOARD_PROJECTOR_LOG("Failed to persist snapshot (seq=%" PRIu64 ")",
                                event->sequence_number);
    }

    pthread_mutex_unlock(&proj->mtx);
    return 0;
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                      Example Usage (unit-test style)                       */
/* ────────────────────────────────────────────────────────────────────────── */

#ifdef DASHBOARD_PROJECTOR_DEMO_MAIN
/*
 * Build:
 *   gcc -DDASHBOARD_PROJECTOR_DEMO_MAIN -pthread dashboard_projector.c -o demo
 *
 * Run:
 *   ./demo
 */
static void feed_demo_events(dashboard_projector_t *proj) {
    domain_event_t ev = {0};

    ev.type            = EVENT_PAYMENT_INITIATED;
    ev.sequence_number = 1;
    ev.data.payment_initiated.amount = 4999.50;
    dashboard_projector_handle(proj, &ev);

    ev.type            = EVENT_PAYMENT_SETTLED;
    ev.sequence_number = 2;
    ev.data.payment_settled.amount  = 4999.50;
    ev.data.payment_settled.success = 1;
    dashboard_projector_handle(proj, &ev);

    ev.type            = EVENT_FRAUD_ALERT;
    ev.sequence_number = 3;
    strncpy(ev.data.fraud_alert.student_id, "S1234567", sizeof(ev.data.fraud_alert.student_id));
    dashboard_projector_handle(proj, &ev);
}

int main(void) {
    dashboard_projector_t *proj = dashboard_projector_create(NULL);
    if (!proj) {
        fprintf(stderr, "Failed to create projector\n");
        return EXIT_FAILURE;
    }

    feed_demo_events(proj);

    dashboard_snapshot_t snap = dashboard_projector_snapshot(proj);
    printf("Snapshot after demo:\n");
    printf("  total_tuition     : %.2f\n", snap.total_tuition);
    printf("  total_payments    : %" PRIu64 "\n", snap.total_payments);
    printf("  pending_payments  : %" PRIu64 "\n", snap.pending_payments);
    printf("  fraud_alerts      : %" PRIu64 "\n", snap.fraud_alerts);
    printf("  last_seq          : %" PRIu64 "\n", snap.last_sequence_number);

    dashboard_projector_destroy(proj);
    return EXIT_SUCCESS;
}
#endif /* DASHBOARD_PROJECTOR_DEMO_MAIN */

/* End of file */