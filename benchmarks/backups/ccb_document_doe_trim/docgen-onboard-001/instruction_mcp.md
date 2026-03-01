# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/istio--f8af3cae`
- Use `repo:^github.com/sg-evals/istio--f8af3cae$` filter in keyword_search
- Use `github.com/sg-evals/istio--f8af3cae` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Task: Generate Developer Onboarding Guide for Istio Control Plane

**Repository:** github.com/sg-evals/istio--f8af3cae (mirror of istio/istio)
**Output:** Write your guide to `/workspace/documentation.md`

## Objective

Produce a developer onboarding guide for Istio's control plane. This guide should help a new contributor understand how to build Istio, navigate the codebase, and make their first contribution.

## Scope

Your guide must cover all of the following:

### 1. Build Prerequisites
- Required Go version, tools, and environment variables
- How to clone the repository with all submodules
- How to build the core control plane binaries (`pilot-discovery`, `istiod`)
- How to run the test suite

### 2. Architecture Overview
- Istio's control plane components and their responsibilities (Pilot, Citadel, Galley — now merged into istiod)
- The xDS protocol and how istiod pushes configuration to Envoy proxies
- Key packages: `pilot/pkg/`, `security/pkg/`, `galley/pkg/`
- How the service registry integrates with Kubernetes

### 3. First Contribution Workflow
- How to find good first issues
- How to run linters and pre-commit checks
- How to write and run unit tests for a change
- How to submit a PR (required reviewers, CI gates)

## Quality Bar

- Reference specific Makefile targets, Go packages, or scripts
- Architecture section must explain at least one data flow end-to-end (e.g., service discovery to xDS push)
- Do not fabricate commands — verify against actual Makefile and scripts in the repo

## Anti-Requirements

- Do not simply reproduce the README
- Do not include Kubernetes operator/installation instructions (focus on developer workflow only)
