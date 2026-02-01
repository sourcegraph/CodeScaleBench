```c
/*=========================================================================*//**
  @file    seed_data.c
  @brief   EduPay Ledger Academy – Database seeding utility
  @author  EduPay Engineering
  @date    2024-02-14

  ---------------------------------------------------------------------------

  Copyright (c) 2024 EduPay

  Licensed under the MIT License. See LICENSE file in the repo root for
  full license information.

  ---------------------------------------------------------------------------

  DESCRIPTION
  ===========
  This command–line utility populates an SQLite datastore with
  deterministic fixture data used by EduPay Ledger Academy’s automated
  tests, demo environments, and classroom exercises.

  The tool is intentionally isolated from the main application runtime so
  that instructors can drop and recreate a sandbox ledger without risking
  production data.  It follows the same “clean architecture” ethos as the
  rest of the codebase—business rules are kept out of this script, which is
  strictly infrastructure–level plumbing.

  USAGE
  -----
      seed_data [OPTIONS]

  OPTIONS
  -------
      -d, --db <PATH>        Path to the SQLite database file to seed
      -r, --reset            Drop all existing schema objects before seeding
      -q, --quiet            Suppress progress output
      -h, --help             Show help and exit

  EXAMPLES
  --------
      # Seed an empty database
      seed_data --db ./sandbox/ledger.db

      # Reset and reseed an existing database quietly
      seed_data -d ./sandbox/ledger.db -r -q

  BUILD
  -----
      cc -Wall -Wextra -pedantic -std=c17 seed_data.c -lsqlite3 -o seed_data

*//=========================================================================*/

#define _POSIX_C_SOURCE 200809L /* for strdup, getline */
#include <sqlite3.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <getopt.h>

/*----------------------------------------------------------------------*/
/*                           CONFIGURATION                              */
/*----------------------------------------------------------------------*/

#define EDU_SEED_VERSION         "1.0.0"
#define EDU_DEFAULT_DB_PATH      "./ledger.db"
#define EDU_COMMIT_DATE          "2024-02-14"

#define EDU_ARRAY_LEN(x) (sizeof(x) / sizeof((x)[0]))

/*----------------------------------------------------------------------*/
/*                           LOGGING                                    */
/*----------------------------------------------------------------------*/

static bool g_quiet = false;

#define LOG_FMT(level, fmt, ...)                                 \
    do {                                                         \
        if (!g_quiet) {                                          \
            fprintf(level == LOG_ERROR ? stderr : stdout,        \
                    "[%s] " fmt "\n",                            \
                    level == LOG_ERROR ? "ERROR" :               \
                    level == LOG_WARN  ? "WARN"  :               \
                    "INFO", ##__VA_ARGS__);                      \
        }                                                        \
    } while (0)

typedef enum { LOG_INFO, LOG_WARN, LOG_ERROR } log_level_t;

/*----------------------------------------------------------------------*/
/*                           SCHEMA                                     */
/*----------------------------------------------------------------------*/

static const char *SQL_DROP_ALL[] = {
    "DROP TABLE IF EXISTS audit_log;",
    "DROP TABLE IF EXISTS transactions;",
    "DROP TABLE IF EXISTS accounts;",
    "DROP TABLE IF EXISTS students;"
};

static const char *SQL_CREATE_TABLES[] = {
    /* Students table ---------------------------------------------------*/
    "CREATE TABLE IF NOT EXISTS students ("
    "  student_id    TEXT PRIMARY KEY,"
    "  first_name    TEXT NOT NULL,"
    "  last_name     TEXT NOT NULL,"
    "  email         TEXT UNIQUE NOT NULL,"
    "  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
    ");",

    /* Accounts table ---------------------------------------------------*/
    "CREATE TABLE IF NOT EXISTS accounts ("
    "  account_id    TEXT PRIMARY KEY,"
    "  student_id    TEXT NOT NULL REFERENCES students(student_id),"
    "  currency      TEXT NOT NULL,"          /* ISO 4217 e.g., USD */
    "  balance_cents INTEGER NOT NULL DEFAULT 0,"
    "  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
    ");",

    /* Transactions table ----------------------------------------------*/
    "CREATE TABLE IF NOT EXISTS transactions ("
    "  tx_id         TEXT PRIMARY KEY,"
    "  account_id    TEXT NOT NULL REFERENCES accounts(account_id),"
    "  amount_cents  INTEGER NOT NULL,"
    "  kind          TEXT NOT NULL,"          /* CREDIT / DEBIT */
    "  description   TEXT,"
    "  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
    ");",

    /* Audit Log table --------------------------------------------------*/
    "CREATE TABLE IF NOT EXISTS audit_log ("
    "  audit_id      INTEGER PRIMARY KEY AUTOINCREMENT,"
    "  actor         TEXT NOT NULL,"
    "  action        TEXT NOT NULL,"
    "  entity_id     TEXT NOT NULL,"
    "  timestamp     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
    ");"
};

/*----------------------------------------------------------------------*/
/*                           FIXTURE DATA                               */
/*----------------------------------------------------------------------*/

/* Students (student_id, first_name, last_name, email) */
static const char *STUDENT_FIXTURES[][4] = {
    { "S-0001", "Ada",   "Lovelace",   "ada.lovelace@edupay.io"    },
    { "S-0002", "Grace", "Hopper",     "grace.hopper@edupay.io"    },
    { "S-0003", "Alan",  "Turing",     "alan.turing@edupay.io"     },
    { "S-0004", "Linus", "Torvalds",   "linus.torvalds@edupay.io"  },
    { "S-0005", "Ken",   "Thompson",   "ken.thompson@edupay.io"    }
};

/* Accounts (account_id, student_id, currency, balance_cents) */
static const char *ACCOUNT_FIXTURES[][4] = {
    { "A-1001", "S-0001", "USD", "250000" },  /* $2,500.00 */
    { "A-1002", "S-0002", "USD", "175000" },
    { "A-1003", "S-0003", "EUR", " 90000" },
    { "A-1004", "S-0004", "GBP", "125000" },
    { "A-1005", "S-0005", "USD", " 50000" }
};

/* Transactions (tx_id, account_id, amount_cents, kind, description) */
static const char *TX_FIXTURES[][5] = {
    { "T-9001", "A-1001", "-15000", "DEBIT",  "Intro to CS tuition" },
    { "T-9002", "A-1001", "  5000", "CREDIT", "Scholarship award"  },
    { "T-9003", "A-1002", "-20000", "DEBIT",  "Compiler Design"    },
    { "T-9004", "A-1003", "- 7500", "DEBIT",  "Algorithms"         },
    { "T-9005", "A-1004", " 10000", "CREDIT", "Research grant"     }
};

/*----------------------------------------------------------------------*/
/*                           HELPER UTILS                               */
/*----------------------------------------------------------------------*/

static void die(const char *msg, sqlite3 *db)
{
    LOG_FMT(LOG_ERROR, "%s: %s", msg, db ? sqlite3_errmsg(db) : "N/A");
    if (db) sqlite3_close(db);
    exit(EXIT_FAILURE);
}

static void exec_or_die(sqlite3 *db, const char *sql)
{
    char *err_msg = NULL;
    if (sqlite3_exec(db, sql, NULL, NULL, &err_msg) != SQLITE_OK) {
        LOG_FMT(LOG_ERROR, "SQL failed: %s", err_msg);
        sqlite3_free(err_msg);
        die("Aborting", db);
    }
}

/*----------------------------------------------------------------------*/
/*                           SEEDING LOGIC                              */
/*----------------------------------------------------------------------*/

static void apply_schema(sqlite3 *db, bool reset)
{
    if (reset) {
        LOG_FMT(LOG_INFO, "Dropping existing schema …");
        for (size_t i = 0; i < EDU_ARRAY_LEN(SQL_DROP_ALL); ++i) {
            exec_or_die(db, SQL_DROP_ALL[i]);
        }
    }

    LOG_FMT(LOG_INFO, "Creating tables (if not present) …");
    for (size_t i = 0; i < EDU_ARRAY_LEN(SQL_CREATE_TABLES); ++i) {
        exec_or_die(db, SQL_CREATE_TABLES[i]);
    }
}

static void seed_students(sqlite3 *db)
{
    sqlite3_stmt *stmt = NULL;
    const char *sql =
        "INSERT OR IGNORE INTO students "
        "(student_id, first_name, last_name, email) "
        "VALUES(?,?,?,?);";

    if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        die("Preparing student insert failed", db);
    }

    for (size_t i = 0; i < EDU_ARRAY_LEN(STUDENT_FIXTURES); ++i) {
        sqlite3_reset(stmt);
        sqlite3_bind_text(stmt, 1, STUDENT_FIXTURES[i][0], -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 2, STUDENT_FIXTURES[i][1], -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 3, STUDENT_FIXTURES[i][2], -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 4, STUDENT_FIXTURES[i][3], -1, SQLITE_STATIC);

        if (sqlite3_step(stmt) != SQLITE_DONE) {
            die("Inserting student failed", db);
        }
    }

    sqlite3_finalize(stmt);
    LOG_FMT(LOG_INFO, "Seeded %zu students", EDU_ARRAY_LEN(STUDENT_FIXTURES));
}

static void seed_accounts(sqlite3 *db)
{
    sqlite3_stmt *stmt = NULL;
    const char *sql =
        "INSERT OR IGNORE INTO accounts "
        "(account_id, student_id, currency, balance_cents) "
        "VALUES(?,?,?,?);";

    if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        die("Preparing account insert failed", db);
    }

    for (size_t i = 0; i < EDU_ARRAY_LEN(ACCOUNT_FIXTURES); ++i) {
        sqlite3_reset(stmt);
        sqlite3_bind_text(stmt, 1, ACCOUNT_FIXTURES[i][0], -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 2, ACCOUNT_FIXTURES[i][1], -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 3, ACCOUNT_FIXTURES[i][2], -1, SQLITE_STATIC);
        sqlite3_bind_int(stmt, 4, atoi(ACCOUNT_FIXTURES[i][3]));

        if (sqlite3_step(stmt) != SQLITE_DONE) {
            die("Inserting account failed", db);
        }
    }

    sqlite3_finalize(stmt);
    LOG_FMT(LOG_INFO, "Seeded %zu accounts", EDU_ARRAY_LEN(ACCOUNT_FIXTURES));
}

static void seed_transactions(sqlite3 *db)
{
    sqlite3_stmt *stmt = NULL;
    const char *sql =
        "INSERT OR IGNORE INTO transactions "
        "(tx_id, account_id, amount_cents, kind, description) "
        "VALUES(?,?,?,?,?);";

    if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        die("Preparing transaction insert failed", db);
    }

    for (size_t i = 0; i < EDU_ARRAY_LEN(TX_FIXTURES); ++i) {
        sqlite3_reset(stmt);
        sqlite3_bind_text(stmt, 1, TX_FIXTURES[i][0], -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 2, TX_FIXTURES[i][1], -1, SQLITE_STATIC);
        sqlite3_bind_int(stmt, 3, atoi(TX_FIXTURES[i][2]));
        sqlite3_bind_text(stmt, 4, TX_FIXTURES[i][3], -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 5, TX_FIXTURES[i][4], -1, SQLITE_STATIC);

        if (sqlite3_step(stmt) != SQLITE_DONE) {
            die("Inserting transaction failed", db);
        }
    }

    sqlite3_finalize(stmt);
    LOG_FMT(LOG_INFO, "Seeded %zu transactions", EDU_ARRAY_LEN(TX_FIXTURES));
}

static void seed_audit(sqlite3 *db, const char *actor)
{
    sqlite3_stmt *stmt = NULL;
    const char *sql =
        "INSERT INTO audit_log (actor, action, entity_id) "
        "VALUES(?,?,?);";

    if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        die("Preparing audit insert failed", db);
    }

    /* Log one entry per major entity type */
    const char *entities[] = { "students", "accounts", "transactions" };
    for (size_t i = 0; i < EDU_ARRAY_LEN(entities); ++i) {
        sqlite3_reset(stmt);
        sqlite3_bind_text(stmt, 1, actor, -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 2, "SEED_DATA", -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 3, entities[i], -1, SQLITE_STATIC);

        if (sqlite3_step(stmt) != SQLITE_DONE) {
            die("Writing audit trail failed", db);
        }
    }

    sqlite3_finalize(stmt);
    LOG_FMT(LOG_INFO, "Audit trail recorded");
}

/*----------------------------------------------------------------------*/
/*                           CLI PARSER                                 */
/*----------------------------------------------------------------------*/

typedef struct {
    const char *db_path;
    bool reset;
    bool quiet;
} cli_opts_t;

static void print_banner(void)
{
    if (g_quiet) return;
    printf("EduPay Ledger Academy – Seed Data %s (%s)\n",
           EDU_SEED_VERSION, EDU_COMMIT_DATE);
    printf("--------------------------------------------------\n");
}

static void usage(FILE *out)
{
    fprintf(out,
        "Usage: seed_data [OPTIONS]\n"
        "\n"
        "Options:\n"
        "  -d, --db <path>     Path to SQLite database file (default: %s)\n"
        "  -r, --reset         Drop tables before seeding\n"
        "  -q, --quiet         Suppress output (except errors)\n"
        "  -h, --help          Show this help message and exit\n",
        EDU_DEFAULT_DB_PATH
    );
}

static cli_opts_t parse_cli(int argc, char **argv)
{
    cli_opts_t opts = {
        .db_path = EDU_DEFAULT_DB_PATH,
        .reset   = false,
        .quiet   = false
    };

    const struct option long_opts[] = {
        { "db",    required_argument, 0, 'd' },
        { "reset", no_argument,       0, 'r' },
        { "quiet", no_argument,       0, 'q' },
        { "help",  no_argument,       0, 'h' },
        { 0, 0, 0, 0 }
    };

    int c;
    while ((c = getopt_long(argc, argv, "d:rqh", long_opts, NULL)) != -1) {
        switch (c) {
            case 'd':
                opts.db_path = optarg;
                break;
            case 'r':
                opts.reset = true;
                break;
            case 'q':
                opts.quiet = true;
                g_quiet = true;
                break;
            case 'h':
                usage(stdout);
                exit(EXIT_SUCCESS);
            default:
                usage(stderr);
                exit(EXIT_FAILURE);
        }
    }

    return opts;
}

/*----------------------------------------------------------------------*/
/*                                MAIN                                  */
/*----------------------------------------------------------------------*/

int main(int argc, char **argv)
{
    cli_opts_t opts = parse_cli(argc, argv);
    print_banner();

    sqlite3 *db = NULL;
    if (sqlite3_open(opts.db_path, &db) != SQLITE_OK) {
        die("Opening database failed", db);
    }

    /* Execute seeding inside a transaction for atomicity */
    exec_or_die(db, "BEGIN IMMEDIATE TRANSACTION;");

    apply_schema(db, opts.reset);
    seed_students(db);
    seed_accounts(db);
    seed_transactions(db);
    seed_audit(db, "seed_data");

    exec_or_die(db, "COMMIT;");

    LOG_FMT(LOG_INFO, "Database seeding completed successfully ✅");
    sqlite3_close(db);
    return EXIT_SUCCESS;
}
```