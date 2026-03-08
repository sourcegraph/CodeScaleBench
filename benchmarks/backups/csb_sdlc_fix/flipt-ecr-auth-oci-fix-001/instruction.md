# Dynamic AWS ECR Authentication for OCI Bundles

**Repository:** flipt-io/flipt
**Language:** Go
**Difficulty:** hard

## Problem

Flipt configured with OCI storage cannot continuously pull bundles from AWS ECR when using temporary credentials. Only static `username/password` authentication is supported today; AWS-issued tokens (e.g., via ECR) expire (commonly ~12h). After expiry, pulls to the OCI repository fail until credentials are manually rotated. A configuration-driven way to support non-static (provider-backed) authentication is needed so bundles continue syncing without manual intervention.

## Key Components

- `internal/oci/` — OCI storage implementation and authentication
- `cmd/flipt/` — bundle command handling
- `internal/storage/fs/` — filesystem storage layer
- Config schema — where OCI storage authentication options are defined

## Task

1. Add support for AWS credentials chain authentication in the OCI storage backend
2. Implement automatic token refresh so pulls continue succeeding across token expiries
3. Maintain backward compatibility with existing static `username/password` authentication
4. Add configuration option to select authentication type (static credentials vs. AWS provider chain)
5. Run existing tests to ensure no regressions

## Success Criteria

- OCI storage supports AWS credentials chain authentication
- Tokens refresh automatically before expiry
- Existing static credential authentication continues to work
- Configuration accepts the new authentication type
- All existing tests pass

