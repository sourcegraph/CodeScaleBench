# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/bazel--8.0.0`
- Use `repo:^github.com/sg-evals/bazel--8.0.0$` filter in keyword_search
- Use `github.com/sg-evals/bazel--8.0.0` as the `repo` parameter for go_to_definition/find_references/read_file


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

**Sourcegraph Repository:** `github.com/sg-evals/bazel--8.0.0`

# Task: Write Unit Tests for Bazel Starlark Rule Evaluation

## Objective
Write comprehensive unit tests for the Starlark evaluation of rule() calls in BUILD files, covering rule instantiation, attribute validation, and error handling.

## Steps
1. Study the Starlark rule evaluation in `src/main/java/com/google/devtools/build/lib/packages/`
2. Understand how `RuleClass` and `RuleFactory` process rule() calls
3. Study existing tests in `src/test/java/com/google/devtools/build/lib/packages/`
4. Create a test file `StarlarkRuleEvalTest.java` in the test directory with tests for:
   - Basic rule instantiation with required attributes
   - Missing required attribute produces error
   - Attribute type validation (string vs list vs label)
   - Default attribute values are applied
   - Visibility attribute handling
   - Rule name validation (valid and invalid names)

## Key Reference Files
- `src/main/java/com/google/devtools/build/lib/packages/RuleClass.java`
- `src/main/java/com/google/devtools/build/lib/packages/RuleFactory.java`
- `src/test/java/com/google/devtools/build/lib/packages/` — existing tests

## Success Criteria
- Test file exists in the test directory
- Tests cover rule instantiation
- Tests cover attribute validation
- Tests cover error cases
