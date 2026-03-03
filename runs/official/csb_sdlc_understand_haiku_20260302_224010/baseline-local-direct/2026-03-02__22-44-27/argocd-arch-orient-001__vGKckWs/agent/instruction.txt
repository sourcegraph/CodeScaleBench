# Onboarding: Argo CD Codebase Orientation

**Repository:** argoproj/argo-cd
**Task Type:** Codebase Orientation (analysis only — no code changes)

## Scenario

You are a new engineer joining a team that works on Argo CD, a declarative GitOps continuous delivery tool for Kubernetes. Your manager has asked you to spend your first day exploring the codebase and answering key orientation questions so you can understand how the system works and start contributing effectively.

## Your Task

Explore the Argo CD codebase and answer the following questions. Write your answers to `/logs/agent/onboarding.md`.

### Questions

1. **Main Entry Points**: Argo CD is a multi-binary system with several core components. Identify the entry points (main functions) for at least 3 of the following components: API server, application controller, repo server, and ApplicationSet controller. For each component, explain its primary responsibility.

2. **Core Packages**: Identify at least 5 key packages and describe what each one is responsible for. Focus on packages that handle: application reconciliation, repository interaction, Kubernetes resource management, API types/CRDs, and utility functions.

3. **Configuration Loading**: How does each component load its configuration? Describe the configuration pipeline: what libraries are used for CLI flags and config files, and where are the main configuration structs defined?

4. **Test Structure**: How are tests organized in this project? Describe at least 3 different types of tests (e.g., unit tests, integration tests, E2E tests). Where do E2E tests live, and what testing frameworks are used?

5. **Application Sync Pipeline**: Trace the path of an Application resource from CRD definition to actual deployment in a Kubernetes cluster. Identify at least 4 stages in this pipeline and name the key packages or files involved at each stage (e.g., CRD types, controller reconciliation loop, repo server manifest generation, kubectl apply).

6. **Adding a New Sync Strategy**: If you needed to add a new sync strategy (e.g., a custom hook or wave behavior), which packages and files would you need to modify? Describe the sequence of changes required to implement a new sync option.

## Output Requirements

Write your answers to `/logs/agent/onboarding.md` with this structure:

```
# Argo CD Codebase Orientation

## 1. Main Entry Points
<Your answer>

## 2. Core Packages
<Your answer>

## 3. Configuration Loading
<Your answer>

## 4. Test Structure
<Your answer>

## 5. Application Sync Pipeline
<Your answer>

## 6. Adding a New Sync Strategy
<Your answer>
```

## Constraints

- Do NOT modify any source files
- Do NOT write any code changes
- Your job is exploration and documentation only
- Be specific — include file paths, package names, function names, and struct names where relevant
