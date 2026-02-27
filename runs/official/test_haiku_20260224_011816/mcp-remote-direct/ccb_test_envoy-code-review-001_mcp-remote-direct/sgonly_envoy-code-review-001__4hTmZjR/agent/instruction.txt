# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/envoy--v1.33.0`
- Use `repo:^github.com/sg-evals/envoy--v1.33.0$` filter in keyword_search
- Use `github.com/sg-evals/envoy--v1.33.0` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Code Review: Envoy Proxy HTTP Filter Chain

- **Repository**: github.com/sg-evals/envoy--v1.33.0 (mirror of envoyproxy/envoy)
- **Difficulty**: hard
- **Category**: code-review
- **Task Type**: repo-clone

## Description

You are reviewing a recently merged pull request that modifies Envoy's HTTP filter chain. The PR touches the fault injection filter, external authorization filter, header utility functions, and the core filter manager. The stated goal was to add observability improvements and fix edge cases in filter chain iteration, but several defects were introduced during the merge — both functional bugs and cross-component interaction errors.

Your task is to **find the defects and produce a structured review report with proposed fixes**.

## Context

The changes span four core areas of Envoy's HTTP filter infrastructure:

1. **`source/extensions/filters/http/fault/fault_filter.cc`** — Fault injection filter: intercepts requests to inject delays and aborts based on configuration. Returns `StopIteration` to pause the filter chain during delay, then calls `continueDecoding()` when the timer fires. Manages an `active_faults_` gauge for tracking in-flight faults.

2. **`source/extensions/filters/http/ext_authz/ext_authz.cc`** — External authorization filter: sends requests to an external auth service, then modifies request headers based on the response. Clears the route cache when headers change so downstream filters see the updated route.

3. **`source/common/http/header_utility.cc`** — Header matching and validation utilities: provides `matchHeaders()` used by fault filter and RBAC, `checkRequiredResponseHeaders()` used by filter manager, and `isRemovableHeader()` used by ext_authz.

4. **`source/common/http/filter_manager.cc`** — Core filter chain orchestrator: iterates decoder/encoder filter chains, handles `StopIteration` vs `Continue` return values, checks required response headers after encoding, and manages the `decoder_filter_chain_aborted_` flag for local reply short-circuiting.

## Task

Review the files listed above for the following types of defects:

- **Functional bugs**: Logic errors that cause incorrect behavior (e.g., inverted conditions, wrong return values, missing state updates).
- **Cross-file interaction bugs**: Defects where a change in one file breaks assumptions in another file (e.g., header matching logic change affects which requests fault filter intercepts).
- **Resource management bugs**: Gauge leaks, missing cleanup, or double-counting of active resources.

For each defect you find:

1. **Describe the defect** in your review report.
2. **Write a fix** as a unified diff in the `fix_patch` field.

**Do NOT edit source files directly.** Express all fixes as unified diffs in your review report. The evaluation system will apply your patches and verify correctness.

### Expected Output

After completing your review, write a JSON file at `/workspace/review.json` containing an array of defect objects:

```json
[
  {
    "file": "source/extensions/filters/http/fault/fault_filter.cc",
    "line": 155,
    "severity": "critical",
    "description": "Brief description of what is wrong and why",
    "fix_patch": "--- a/source/extensions/filters/http/fault/fault_filter.cc\n+++ b/source/extensions/filters/http/fault/fault_filter.cc\n@@ -153,5 +153,5 @@\n-    old line\n+    new line\n"
  }
]
```

Each entry must include:
- `file` — Relative path from repository root
- `line` — Approximate line number where the defect occurs
- `severity` — One of: `critical`, `high`, `medium`, `low`
- `description` — What the defect is and what impact it has
- `fix_patch` — Unified diff showing the proposed fix (use `--- a/` and `+++ b/` prefix format)

## Evaluation

Your review will be evaluated on:
- **Detection accuracy** (50%): Precision and recall of reported defects
- **Fix quality** (50%): Whether your proposed patches correctly resolve the defects

## Constraints

- **Time limit**: 1200 seconds
- Do NOT edit source files directly — express fixes only in `fix_patch`
- Do NOT run tests — the evaluation system handles verification
