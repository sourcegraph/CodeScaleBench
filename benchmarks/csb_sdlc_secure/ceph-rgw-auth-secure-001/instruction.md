# Task: Security Audit of Ceph RADOS Gateway S3 Authentication

## Objective
Perform a security audit of the S3 authentication implementation in Ceph's RADOS Gateway (RGW) and create a findings report with remediation recommendations.

## Steps
1. Find the S3 authentication implementation in `src/rgw/` (look for AWS Signature V4 handling)
2. Identify the request signing and verification flow
3. Check for common S3 auth vulnerabilities:
   - Signature version fallback (V2 vs V4)
   - Timing attacks in signature comparison
   - Request replay prevention (timestamp validation window)
   - Secret key storage and access patterns
4. Create `security_audit.md` in `/workspace/` documenting:
   - Authentication flow overview (file paths and key functions)
   - Each finding with severity, description, file location, and remediation
   - At least 3 specific findings with code references
   - Summary risk assessment

## Key Reference Files
- `src/rgw/rgw_auth_s3.h` and `src/rgw/rgw_auth_s3.cc` — S3 auth
- `src/rgw/rgw_rest_s3.cc` — S3 REST handler
- `src/rgw/rgw_auth.h` — auth framework

## Success Criteria
- security_audit.md exists
- Contains file paths from src/rgw/
- Identifies at least 3 security findings
- Includes remediation recommendations
