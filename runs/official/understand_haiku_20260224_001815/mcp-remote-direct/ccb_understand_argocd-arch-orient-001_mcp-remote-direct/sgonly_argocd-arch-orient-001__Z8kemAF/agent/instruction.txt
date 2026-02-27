# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/argo-cd--v2.13.2`
- Use `repo:^github.com/sg-evals/argo-cd--v2.13.2$` filter in keyword_search
- Use `github.com/sg-evals/argo-cd--v2.13.2` as the `repo` parameter for go_to_definition/find_references/read_file


## Required Workflow

1. **Search first** — Use MCP tools to find relevant files and understand existing patterns
2. **Read remotely** — Use `sg_read_file` to read full file contents from Sourcegraph
3. **Edit locally** — Use Edit, Write, and Bash to create or modify files in your working directory
4. **Verify locally** — Run tests with Bash to check your changes

## Tool Selection

| Goal | Tool |
|------|------|
| Exact symbol/string | `sg_keyword_search` |
| Concepts/semantic search | `sg_nls_search` |
| Trace usage/callers | `sg_find_references` |
| See implementation | `sg_go_to_definition` |
| Read full file | `sg_read_file` |
| Browse structure | `sg_list_files` |
| Find repos | `sg_list_repos` |
| Search commits | `sg_commit_search` |
| Track changes | `sg_diff_search` |
| Compare versions | `sg_compare_revisions` |

**Decision logic:**
1. Know the exact symbol? → `sg_keyword_search`
2. Know the concept, not the name? → `sg_nls_search`
3. Need definition of a symbol? → `sg_go_to_definition`
4. Need all callers/references? → `sg_find_references`
5. Need full file content? → `sg_read_file`

## Scoping (Always Do This)

```
repo:^github.com/ORG/REPO$           # Exact repo (preferred)
repo:github.com/ORG/                 # All repos in org
file:.*\.ts$                         # TypeScript only
file:src/api/                        # Specific directory
```

Start narrow. Expand only if results are empty.

## Efficiency Rules

- Chain searches logically: search → read → references → definition
- Don't re-search for the same pattern; use results from prior calls
- Prefer `sg_keyword_search` over `sg_nls_search` when you have exact terms
- Read 2-3 related files before synthesising, rather than one at a time
- Don't read 20+ remote files without writing code — once you understand the pattern, start implementing

## If Stuck

If MCP search returns no results:
1. Broaden the search query (synonyms, partial identifiers)
2. Try `sg_nls_search` for semantic matching
3. Use `sg_list_files` to browse the directory structure
4. Use `sg_list_repos` to verify the repository name

---

# Onboarding: Argo CD Codebase Orientation

**Repository:** github.com/sg-evals/argo-cd--v2.13.2 (mirror of argoproj/argo-cd)
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
