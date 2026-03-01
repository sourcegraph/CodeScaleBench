# Task: Extract EndpointRegenerator from Endpoint Manager

## Objective
Extract the regeneration logic from `pkg/endpoint/manager.go` into a new
`EndpointRegenerator` struct in `pkg/endpoint/regenerator.go`, following the
single-responsibility principle.

## Requirements

1. **Create `pkg/endpoint/regenerator.go`**:
   - `EndpointRegenerator` struct with regeneration-related fields from manager
   - Move regeneration methods: `RegenerateAllEndpoints`, `WaitForEndpointRegeneration`
   - Keep manager as coordinator that delegates to regenerator

2. **Update `pkg/endpoint/manager.go`**:
   - Add `regenerator *EndpointRegenerator` field
   - Delegate regeneration calls to new struct
   - Remove extracted methods

3. **Update callers** that call regeneration methods through manager

## Key Reference Files
- `pkg/endpoint/manager.go` — current manager with regeneration logic
- `pkg/endpoint/endpoint.go` — Endpoint struct
- `pkg/endpoint/regeneration.go` — regeneration logic (if exists)

## Success Criteria
- EndpointRegenerator struct exists in a separate file
- Regeneration methods moved to EndpointRegenerator
- Manager delegates to EndpointRegenerator
- Callers updated
