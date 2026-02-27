# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/vscode--1.96.0`
- Use `repo:^github.com/sg-evals/vscode--1.96.0$` filter in keyword_search
- Use `github.com/sg-evals/vscode--1.96.0` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Code Review: VS Code Editor Core

- **Repository**: github.com/sg-evals/vscode--1.96.0 (mirror of microsoft/vscode)
- **Difficulty**: hard
- **Category**: code-review
- **Task Type**: repo-clone

## Description

You are reviewing a recently merged pull request that modifies VS Code's editor core. The PR touches the Range and Position geometry classes, the text search engine, the language feature provider registry, and shared string utilities. The stated goal was to improve search boundary handling and optimize provider sorting, but several defects were introduced during the merge — both functional bugs and cross-component interaction errors.

Your task is to **find the defects and produce a structured review report with proposed fixes**.

## Context

The changes span five core areas of VS Code's editor infrastructure:

1. **`src/vs/editor/common/core/range.ts`** — Range class: fundamental geometry primitive for the editor. `containsPosition()` checks whether a position falls within a range (inclusive on edges). Used by virtually every editor feature: selections, decorations, find-and-replace highlighting, bracket matching, and code lens.

2. **`src/vs/base/common/strings.ts`** — Shared string utilities: provides `createRegExp()` which converts search strings to RegExp objects with case sensitivity, whole-word, and multiline flags. Called by `textModelSearch.ts` for find/replace, by `richEditBrackets.ts` for bracket matching, and by search workers.

3. **`src/vs/editor/common/model/textModelSearch.ts`** — Text search engine: implements find-and-replace in the text model. Contains `SearchParams`, `isMultilineRegexSource()` for detecting multiline patterns, `isValidMatch()` for whole-word boundary checks, and the `Searcher` class. Uses `Range`, `Position`, `strings.createRegExp()`, and `WordCharacterClassifier`.

4. **`src/vs/editor/common/languageFeatureRegistry.ts`** — Language feature provider registry: manages registration and scoring/sorting of language feature providers (completions, hover, diagnostics, etc.). Providers are scored against documents via `languageSelector.ts` and sorted by `_compareByScoreAndTime()` to determine priority. Higher scores should appear first.

5. **`src/vs/editor/common/core/position.ts`** — Position class: represents a line/column coordinate. `isBefore()` returns true only when position a is strictly before position b (equal positions return false). Used by Range, Selection, cursor movement, and undo/redo.

## Task

Review the files listed above for the following types of defects:

- **Functional bugs**: Logic errors that cause incorrect behavior (e.g., inverted conditions, wrong operators, missing checks).
- **Cross-file interaction bugs**: Defects where a change in one file breaks assumptions in another file (e.g., string utility flag inversion affects all search consumers).
- **Boundary condition bugs**: Off-by-one errors in position/range comparisons that subtly break containment and ordering contracts.

For each defect you find:

1. **Describe the defect** in your review report.
2. **Write a fix** as a unified diff in the `fix_patch` field.

**Do NOT edit source files directly.** Express all fixes as unified diffs in your review report. The evaluation system will apply your patches and verify correctness.

### Expected Output

After completing your review, write a JSON file at `/workspace/review.json` containing an array of defect objects:

```json
[
  {
    "file": "src/vs/editor/common/core/range.ts",
    "line": 97,
    "severity": "critical",
    "description": "Brief description of what is wrong and why",
    "fix_patch": "--- a/src/vs/editor/common/core/range.ts\n+++ b/src/vs/editor/common/core/range.ts\n@@ -94,5 +94,5 @@\n-    old line\n+    new line\n"
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
