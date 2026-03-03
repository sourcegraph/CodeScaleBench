# Task: Implement COPY FROM CSV WITH HEADER MATCH for PostgreSQL

## Objective
Add a `HEADER MATCH` option to PostgreSQL's `COPY FROM` command that validates the CSV file's header row column names match the target table's column names (in order and spelling). Currently `COPY ... WITH (HEADER)` simply skips the first row; `HEADER MATCH` should verify it matches.

## Requirements

1. **Extend the COPY grammar** (`src/backend/parser/gram.y`):
   - Add `MATCH` as a valid keyword after `HEADER` in COPY options
   - The option should be: `HEADER MATCH` (two tokens) as an alternative to `HEADER` / `HEADER TRUE`
   - Store the distinction in the CopyStmt or DefElem representation

2. **Update COPY option processing** (`src/backend/commands/copy.c` or `src/backend/commands/copyfrom.c`):
   - Parse the `HEADER MATCH` option and set a flag (e.g., `header_line` enum: OFF, ON, MATCH)
   - Only valid for CSV format with COPY FROM (not COPY TO)
   - Raise an error if HEADER MATCH is used with non-CSV format or COPY TO

3. **Implement header validation** in the COPY FROM reader:
   - After reading the first line of the CSV file, compare each column name to the corresponding column in the target table's column list
   - Column comparison should be case-insensitive
   - If extra/missing/mismatched columns are found, raise an ERROR with a descriptive message listing the mismatched column names

4. **Add a regression test** in `src/test/regress/sql/copy.sql` (or a new file):
   - Test HEADER MATCH with matching headers (should succeed)
   - Test HEADER MATCH with mismatched headers (should fail with appropriate error)
   - Test HEADER MATCH with wrong column count (should fail)

## Key Reference Files
- `src/backend/parser/gram.y` — SQL grammar (search for `copy_opt_list` and `HEADER`)
- `src/backend/commands/copy.c` — COPY command entry point, option processing
- `src/backend/commands/copyfrom.c` — COPY FROM implementation
- `src/include/commands/copy.h` — CopyHeaderChoice enum and CopyFormatOptions
- `src/include/parser/kwlist.h` — keyword list (MATCH may need adding)
- `src/test/regress/sql/copy.sql` — existing COPY regression tests

## Success Criteria
- HEADER MATCH syntax accepted in SQL grammar
- CopyHeaderChoice enum or equivalent extended with MATCH value
- Header validation logic reads CSV header and compares to table columns
- Appropriate error raised on mismatch
- Regression test file exists with match/mismatch test cases
