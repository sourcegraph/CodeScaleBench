# Task: Implement Bulk Silence Creation API for Prometheus

## Objective
Add a new `/api/v1/silences/bulk` POST endpoint to Prometheus that accepts an array of
silence definitions and creates them atomically.

## Requirements

1. **Create handler in `web/api/v1/api.go`** (or a new file `web/api/v1/silences_bulk.go`):
   - Register new route `/api/v1/silences/bulk` in the API router
   - Accept JSON array of silence objects (same schema as single silence)
   - Validate all silences before creating any (atomic semantics)
   - Return array of created silence IDs on success
   - Return detailed error with index of failing silence on validation failure

2. **Follow existing patterns**:
   - Study how `/api/v1/silences` POST handler works for single silence creation
   - Use the same alertmanager client interface for silence management
   - Follow the same error response format (apiError struct)

3. **Create test file** `web/api/v1/silences_bulk_test.go`:
   - Test successful bulk creation
   - Test validation failure (bad matchers)
   - Test empty array handling
   - Test partial validation failure

## Key Reference Files
- `web/api/v1/api.go` — API router registration and handler patterns
- `web/api/v1/api_test.go` — test patterns for API endpoints
- `silence/silence.go` — silence model and validation

## Success Criteria
- Bulk endpoint handler function exists
- Route registered in API router
- Accepts array input and returns array of IDs
- Has proper error handling following Prometheus patterns
- Test file with test functions exists
