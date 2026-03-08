# Align Solr Boolean Clause Limit with Reading-Log Filter Cap

**Repository:** internetarchive/openlibrary
**Language:** Python
**Difficulty:** hard

## Problem

The reading-log search can generate very large boolean queries. The application enforces a maximum cap defined in `openlibrary/core/bookshelves.py`, while Solr enforces its own maximum via the `-Dsolr.max.booleanClauses=30000` option inside the `SOLR_OPTS` environment variable in `docker-compose.yml`. If these values drift out of sync, searches may fail or behave inconsistently. When Solr's configured limit is lower than the backend cap, large reading-log searches trigger errors or return incomplete results.

## Key Components

- `openlibrary/core/bookshelves.py` — backend cap for reading-log boolean clause count
- `docker-compose.yml` — Solr service definition with `SOLR_OPTS` environment variable containing `-Dsolr.max.booleanClauses`

## Task

1. Locate the boolean clause cap in `openlibrary/core/bookshelves.py`
2. Locate the Solr boolean clause limit in `docker-compose.yml` under `SOLR_OPTS`
3. Align both values to ensure consistency (both should be 30000)
4. Verify that large reading-log queries can execute without errors
5. Run existing tests to ensure no regressions

## Success Criteria

- `bookshelves.py` and `docker-compose.yml` define the same boolean clause limit
- Large reading-log searches execute without Solr errors
- All existing tests pass

