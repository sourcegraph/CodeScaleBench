# Compliance Evidence Bundle: SSO Settings Feature in Grafana

## Your Task

Find ALL files in `grafana/grafana` that form the SSO settings control across 4 layers: 1. Feature Flag Definition — the registry where `ssoSettingsApi` is defined and generated constants. 2. SSO Settings Infrastructure — Service interface, Reloadable interface, SSOSettings data model, and SSOSettingsStore database layer. 3. API and Authentication Wiring — REST API endpoint registration with access control middleware, SocialService provider, and authentication client registration. 4. Access Control and DI Registration — access control evaluators and the ProvideService dependency injection function.

## Context

You are working on a codebase task involving repos from the compliance domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/grafana--26d36ec.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/grafana--26d36ec` (grafana/grafana)
- `sg-evals/grafana-loki` (grafana/loki)
- `sg-evals/grafana-mimir` (grafana/mimir)

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "files": [
    {"repo": "repo-name", "path": "relative/path/to/file.go"}
  ],
  "symbols": [
    {"repo": "repo-name", "path": "relative/path/to/file.go", "symbol": "SymbolName"}
  ],
  "chain": [
    {"repo": "repo-name", "path": "relative/path/to/file.go", "symbol": "FunctionName"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

Include only the fields relevant to this task. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant files?
