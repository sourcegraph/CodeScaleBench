# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/kubernetes--2e534d6`
- Use `repo:^github.com/sg-evals/kubernetes--2e534d6$` filter in keyword_search
- Use `github.com/sg-evals/kubernetes--2e534d6` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Investigation: DRA AllocationMode API Change Impact Analysis

**Repository:** github.com/sg-evals/kubernetes--2e534d6 (mirror of kubernetes/kubernetes)
**Task Type:** Impact Analysis (investigation only — no code changes)

## Scenario

The Dynamic Resource Allocation (DRA) scheduler plugin is being modified to allow `AllocationMode: All` from multi-node resource pools. Previously, this allocation mode was restricted to single-node pools only. Before this change ships, the team needs a comprehensive impact analysis.

## Your Task

Produce an impact analysis report at `/logs/agent/investigation.md`.

Your report MUST cover:
1. All source files that reference `AllocationMode` or the DRA allocation logic
2. Which controllers and schedulers are affected
3. What test files cover the current allocation behavior
4. What performance implications exist (scheduler hot paths affected)
5. Which downstream consumers (kubelet, device plugins) would see changed behavior
6. Risk assessment: what could break if this change has bugs

## Output Requirements

Write your investigation report to `/logs/agent/investigation.md` with these sections:

```
# Investigation Report

## Summary
<1-2 sentence finding>

## Root Cause
<Scope of the change — what components are affected and why>

## Evidence
<Code references with file paths and line numbers>

## Affected Components
<List of packages/modules impacted, categorized by risk level>

## Recommendation
<Risk mitigation strategy and testing plan>
```

## Constraints

- Do NOT write any code
- Do NOT modify any source files
- Your job is investigation and analysis only
- Focus on tracing `AllocationMode` through the DRA plugin, scheduler framework, and kubelet
