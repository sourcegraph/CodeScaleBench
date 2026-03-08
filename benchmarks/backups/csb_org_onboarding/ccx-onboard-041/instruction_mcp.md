# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repositories (version-pinned mirrors):**

- `github.com/sg-evals/numpy` — use `repo:^github.com/sg-evals/numpy$` filter
- `github.com/sg-evals/pandas` — use `repo:^github.com/sg-evals/pandas$` filter
- `github.com/sg-evals/scikit-learn` — use `repo:^github.com/sg-evals/scikit-learn$` filter
- `github.com/sg-evals/scipy` — use `repo:^github.com/sg-evals/scipy$` filter

Scope ALL keyword_search/nls_search queries to these repos.
Use the repo name as the `repo` parameter for read_file/go_to_definition/find_references.


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

**Sourcegraph Repositories:** `github.com/sg-evals/numpy`, `github.com/sg-evals/pandas`, `github.com/sg-evals/scikit-learn`, `github.com/sg-evals/scipy`

# Onboarding Audit: scipy.stats API Call Sites in pandas

## Your Task

You are a new engineer joining the pandas-dev team. As part of onboarding, you've been asked
to audit which pandas source files have runtime dependencies on `scipy.stats`. These call sites
are important to document because they determine where pandas degrades gracefully when scipy
is not installed.

**Specific question**: Which Python source files in `pandas-dev/pandas` contain a
`from scipy.stats import` statement (i.e., directly import functions or classes from
`scipy.stats` at runtime)?

Include files in any part of the `pandas-dev/pandas` codebase — production code **and** test
files. Do not include files that only mention `scipy.stats` in docstrings or comments.

## Context

You are onboarding to a polyrepo Python scientific stack. Your ecosystem includes
`scikit-learn/scikit-learn` as a reference implementation of a well-maintained scipy consumer.

Your ecosystem includes the following repositories:
- `scikit-learn/scikit-learn` (ML algorithms)
- `pandas-dev/pandas` (dataframe-library)
- `numpy/numpy` (array-computing)
- `scipy/scipy` (scientific-computing)

## Output Format

Create a file at `/workspace/answer.json` with your findings:

```json
{
  "files": [
    {"repo": "pandas-dev/pandas", "path": "relative/path/to/file.py"}
  ],
  "text": "Narrative summary of your findings, citing the repos and file paths."
}
```

List all files that contain `from scipy.stats import`. Your answer is evaluated against
a closed-world oracle — completeness matters.

**Important**: Use exact repo identifiers as they appear in Sourcegraph. The oracle expects `repo` values of `pandas-dev/pandas`. The `repo` field must match exactly.
**Note**: Sourcegraph MCP tools return repo names with a `github.com/` prefix (e.g., `github.com/sg-evals/kubernetes-client-go`). Strip this prefix in your answer — use `sg-evals/kubernetes-client-go`, NOT `github.com/sg-evals/kubernetes-client-go`.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all pandas files that `from scipy.stats import`?
- **Provenance**: Does your narrative cite the repo and file paths found?
