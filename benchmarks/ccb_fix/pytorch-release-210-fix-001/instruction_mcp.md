# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/pytorch--863edc78`
- Use `repo:^github.com/sg-evals/pytorch--863edc78$` filter in keyword_search
- Use `github.com/sg-evals/pytorch--863edc78` as the `repo` parameter for go_to_definition/find_references/read_file


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

# [RELEASE 2.10] Release only changes

**Repository:** github.com/sg-evals/pytorch--863edc78 (mirror of pytorch)  
**Difficulty:** HARD  
**Category:** cross_module_bug_fix



## Description

This is the PyTorch 2.10 release branch CI/CD configuration update. It updates approximately 110 GitHub Actions workflow files under `.github/workflows/` to pin versions, update build matrix references, and adjust CI runner configurations for the 2.10 release branch. The changes are primarily mechanical: updating branch references, Docker image tags, and workflow trigger conditions. This also includes ROCm/HIP-related adjustments for AMD GPU support in the release. Release branch CI configuration must be precise: incorrect workflow pins or build matrix entries can cause nightly builds to fail, release binaries to be built against wrong CUDA/ROCm versions, or tests to run on incorrect infrastructure.

## Task

Changes:
- 110 files modified (primarily `.github/workflows/*.yml`)
- 345 additions, 463 deletions

Tasks:
1. Understand the release branch CI configuration pattern (see PR #162493 for the 2.9 equivalent)
2. Update workflow files with correct branch references and Docker image tags
3. Adjust build matrix entries for CUDA and ROCm versions
4. Verify your changes compile and match the expected fix

## Success Criteria

Code changes match the expected ground-truth fix.
Code follows repository conventions.
No regressions in existing functionality.
All 110 modified files updated correctly.

## Testing

Your implementation will be automatically verified:

```
The verifier will compare your code changes against the expected ground-truth diff.
Score = 0.35 * file_recall + 0.45 * line_recall + 0.20 * line_precision
```

**Time Limit:** 10 minutes  
**Estimated Context:** 8000 tokens
