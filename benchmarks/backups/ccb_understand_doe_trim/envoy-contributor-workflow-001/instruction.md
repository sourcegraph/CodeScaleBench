# Onboarding: Envoy Contributor Workflow Discovery

**Repository:** envoyproxy/envoy
**Task Type:** Workflow Discovery (analysis only — no code changes)

## Scenario

You want to contribute a bug fix to Envoy, but you've never worked with Bazel or the Envoy codebase before. Before you can submit a pull request, you need to understand the contributor workflow: how to build the project, run tests, understand the CI pipeline, and navigate the code review process.

## Your Task

Explore the Envoy repository and create a contributor guide covering the essential workflow steps. Write your guide to `/logs/agent/onboarding.md`.

### Questions to Answer

1. **Build Prerequisites**: What tools and dependencies must be installed before you can build Envoy? What versions are required? Where is this documented?

2. **Build System**: What build system does Envoy use? What are the key build commands to:
   - Build the entire project
   - Build a specific component or test
   - Build with different configurations (debug vs release)

3. **Running Tests**: How do you run tests in Envoy? Document:
   - Command to run all tests
   - Command to run a specific test or test suite
   - What test frameworks are used (unit tests, integration tests)
   - Where are test utilities and helpers located?

4. **CI Pipeline**: Describe Envoy's continuous integration system:
   - What CI platform(s) are used?
   - Where are CI configuration files located?
   - What checks run on pull requests (build, test, lint, coverage)?
   - How long does a typical CI run take?

5. **Code Review Process**: What is the code review workflow for Envoy?
   - Where is the contribution guide documented?
   - What are the requirements for submitting a PR (DCO sign-off, tests, docs)?
   - How are reviewers assigned?
   - What coding standards or style guides must be followed?

6. **Developer Workflow Example**: Walk through a concrete example workflow: "I want to fix a bug in the HTTP connection manager filter. What are the exact steps from cloning the repo to getting my PR merged?"

## Output Requirements

Write your contributor guide to `/logs/agent/onboarding.md` with this structure:

```
# Envoy Contributor Guide

## 1. Build Prerequisites
<Your answer>

## 2. Build System
<Your answer>

## 3. Running Tests
<Your answer>

## 4. CI Pipeline
<Your answer>

## 5. Code Review Process
<Your answer>

## 6. Developer Workflow Example
<Your answer>
```

## Constraints

- Do NOT modify any source files
- Do NOT write any code changes
- Your job is exploration and documentation only
- Be specific — include exact commands, file paths, configuration file names, and URLs where relevant
- Focus on practical workflow steps that a real contributor would need
