# Compliance Evidence Bundle: SSO Settings Feature in Grafana

## Scenario

For a SOC 2 audit, your security team needs a compliance evidence bundle proving
that Grafana's SSO (Single Sign-On) settings control is implemented end-to-end.
You need to trace the `ssoSettingsApi` feature flag from its definition through
the SSO settings infrastructure, API endpoints, OAuth connector wiring, and
authentication registration to show the control is properly gated and enforced.

## Your Task

Find ALL files in `grafana/grafana` that form the SSO settings control across
these 4 layers:

### 1. Feature Flag Definition
- The feature flag registry where `ssoSettingsApi` is defined
- Generated constants files (Go, TypeScript) that reference this flag

### 2. SSO Settings Infrastructure
- The `Service` interface definition for SSO settings management
- The `Reloadable` interface for live configuration reloading
- The `SSOSettings` data model/struct with persistence annotations
- The `SSOSettingsStore` database layer for SSO setting persistence

### 3. API & Authentication Wiring
- The REST API endpoint registration (`/api/v1/sso-settings`) with access control middleware
- The `SocialService` provider that loads OAuth connectors when the flag is enabled
- The authentication client registration that conditionally enables LDAP based on the flag

### 4. Access Control & DI Registration
- The access control evaluators (`EvalAuthenticationSettings`, `OauthSettingsEvaluator`) that gate SSO admin UI access
- The `ProvideService` dependency injection function that wires the SSO settings store, API, fallback strategies, and reloadables

## Available Resources

Your ecosystem includes the following repositories:
- `grafana/grafana` at v11.4.0
- `grafana/loki` at v3.3.4

## Output Format

Create a file at `/workspace/answer.json` with your findings:

```json
{
  "files": [
    {"repo": "grafana/grafana", "path": "pkg/services/featuremgmt/registry.go"}
  ],
  "text": "Comprehensive explanation of how the 4 layers connect: feature flag definition → SSO settings infrastructure → API & authentication wiring → access control & DI registration."
}
```

**Important**: Use `grafana/grafana` as the exact `repo` identifier. Strip the
`github.com/` prefix that tool output may return.

**Hint**: This task requires synthesizing across feature management,
SSO settings infrastructure, OAuth connectors, and authentication registration
layers. A cross-repo search workflow is particularly well-suited for tracing these cross-cutting
concerns.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find the architecturally significant files across all 4 layers?
- **Keyword coverage**: Does your answer reference the key interfaces and types (`ssoSettingsApi`, `FlagSsoSettingsApi`, `SSOSettings`, `Reloadable`, `SSOSettingsStore`)?
- **Provenance**: Does your answer cite the correct repos and directory paths?
- **Rubric judge**: An LLM judge will assess evidence completeness, cross-component tracing, auditor actionability, and technical accuracy.
