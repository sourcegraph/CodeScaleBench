# Team Handoff: Envoy ext_authz Filter

You are taking over ownership of the **ext_authz HTTP filter** from a departing team member. Your task is to produce a comprehensive handoff document that will help you (and future maintainers) understand this component.

## Context

The ext_authz filter is one of Envoy's authorization extensions. Your predecessor maintained it for the past year but is moving to a different project. You need to quickly build a working mental model of this component.

## Your Task

Explore the Envoy codebase and produce a handoff document at `/logs/agent/onboarding.md` covering the following sections:

### 1. Purpose
What does the ext_authz filter do? What problems does it solve? When would someone use it?

### 2. Dependencies
- **Upstream dependencies**: What other Envoy components or libraries does ext_authz depend on?
- **Downstream consumers**: What uses or integrates with ext_authz? How is it configured in Envoy's filter chain?

### 3. Relevant Components
List the most important source files for this filter. For each file, explain its role (e.g., "configuration parsing", "request handling", "gRPC client implementation").

### 4. Failure Modes
What can go wrong? What are common failure scenarios? How does the filter handle errors (e.g., authorization service unavailable, timeout, network failure)?

### 5. Testing
How is this filter tested? Where are the tests located? Are there integration tests, unit tests, or both?

### 6. Debugging
If something goes wrong with ext_authz in production, how would you debug it? What logs, metrics, or traces would you look at?

## Deliverable

Write your findings to `/logs/agent/onboarding.md` using the following structure:

```
# ext_authz Filter Handoff Document

## 1. Purpose
[Your findings here]

## 2. Dependencies
### Upstream Dependencies
[What ext_authz depends on]

### Downstream Consumers
[What depends on ext_authz]

## 3. Relevant Components
- **path/to/file.cc**: [Role/responsibility]
- **path/to/file.h**: [Role/responsibility]
...

## 4. Failure Modes
[Failure scenarios and error handling]

## 5. Testing
[Test locations, test types, how to run tests]

## 6. Debugging
[Debugging strategies, observability]
```

## Guidelines

- Be specific. Reference actual file paths, class names, function names.
- Focus on understanding the **system's behavior**, not just describing the code.
- This is analysis only — do not modify any code.
- Use code search and file exploration tools to explore the codebase efficiently.
