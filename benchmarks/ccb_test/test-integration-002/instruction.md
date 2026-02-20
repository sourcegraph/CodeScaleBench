# Task: Write Integration Tests for Navidrome Media Scanner

**Repository:** navidrome/navidrome
**Output:** Write your test file to `/workspace/scanner/scanner_integration_test.go`

## Objective

Author integration tests for Navidrome's media scanning pipeline. Navidrome scans a music library directory, extracts metadata from audio files, and persists track/album/artist records to a database.

## Scope

Explore the scanner package (`scanner/`) and its dependencies. Key areas:
- `scanner/scanner.go` — top-level scanner entry point
- `scanner/metadata/` — audio file metadata extraction
- `core/artwork/` — artwork extraction
- Database persistence via the store interfaces

Your integration tests must cover:
- Full scan of a test fixture directory with mock audio files
- Metadata extraction (title, artist, album, year, track number)
- Album and artist record creation
- Incremental scan (re-scan with no changes produces no DB updates)
- File deletion detection (missing file removes DB record)

## Output Format

Write a Go test file at:
```
/workspace/scanner/scanner_integration_test.go
```

Use Go's `testing` package. Each test function must start with `Test`. Use test fixtures (small audio files or mock file system) where needed.

## Quality Bar

- At least 5 test functions
- Cover at least 3 pipeline stages (file discovery, metadata extraction, DB persistence)
- Include at least one negative case (deleted file, corrupt metadata)
- Do not fabricate package names or function signatures — inspect the actual codebase first
- Do NOT run the tests yourself — write the test file and the evaluation system validates independently
