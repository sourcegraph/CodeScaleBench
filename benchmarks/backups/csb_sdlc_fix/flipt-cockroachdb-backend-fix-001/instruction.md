# Support CockroachDB as a First-Class Database Backend

**Repository:** flipt-io/flipt
**Language:** Go
**Difficulty:** hard

## Problem

CockroachDB uses the same wire protocol as PostgreSQL, allowing it to work with existing PostgreSQL-compatible drivers. However, Flipt does not recognize CockroachDB as a distinct backend in configuration or database migrations. Flipt's internal logic currently assumes PostgreSQL when using the Postgres driver, which causes issues when targeting CockroachDB without explicit support. This prevents seamless setup and deployment of Flipt with CockroachDB, even though technical compatibility exists.

## Key Components

- Configuration parsing — where database protocol/driver is resolved from config
- Database migration logic — uses `golang-migrate` with driver-specific handling
- SQL driver initialization — where the PostgreSQL driver is selected and configured

## Task

1. Add `cockroachdb` as a supported database protocol in Flipt's configuration schema
2. Enable migrations using the CockroachDB driver in `golang-migrate`
3. Ensure the CockroachDB backend reuses PostgreSQL SQL driver logic where appropriate
4. Add or update configuration validation to accept the new backend
5. Run existing tests to ensure no regressions with PostgreSQL and other backends

## Success Criteria

- `cockroachdb` is accepted as a valid database protocol in configuration
- Migrations run correctly with the CockroachDB driver
- CockroachDB backend shares appropriate SQL logic with the PostgreSQL backend
- Existing database backends (PostgreSQL, MySQL, SQLite) are unaffected
- All existing tests pass

