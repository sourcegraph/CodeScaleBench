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

# Deprecated API Migration Inventory: numpy.distutils

## Your Task

Your team is planning a cleanup of the deprecated `numpy.distutils` module, which was
deprecated in NumPy 1.23 and removed in NumPy 2.0. Before completing the migration,
you need to identify every Python source file across the Python ML ecosystem that still
references `numpy.distutils` — either importing it, vendoring code from it, or
referencing it in help text.

**Specific question**: Which Python source files (`.py`) across the `numpy/numpy` and
`scipy/scipy` repositories still contain references to `numpy.distutils`?

Include files that:
- Import `numpy.distutils` or any of its submodules
- Contain vendored code originally from `numpy.distutils` (marked by comments)
- Reference `numpy.distutils` in help strings or docstrings

Do NOT include:
- Documentation files (`.rst`, `.md`, `.txt`)
- Release notes or changelogs
- Files inside the now-removed `numpy/distutils/` package directory itself (the definition, not consumers)

## Context

The `numpy.distutils` module provided enhanced distutils support for building C/Fortran
extensions. It was deprecated in favor of Meson build system. While `scikit-learn` and
`pandas` have fully migrated (zero references remain), `numpy` itself and `scipy` still
have residual references in vendored code and help strings.

## Available Resources

Your ecosystem includes the following repositories:
- `numpy/numpy` at v2.2.2
- `scipy/scipy` at v1.15.1
- `scikit-learn/scikit-learn` at 1.6.1
- `pandas-dev/pandas` at v2.2.3

## Output Format

Create a file at `/workspace/answer.json` with your findings:

```json
{
  "files": [
    {"repo": "numpy/numpy", "path": "relative/path/to/file.py"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

**Important**: Use canonical repo names (e.g., `numpy/numpy`, `scipy/scipy`).
**Note**: Sourcegraph MCP tools return repo names with a `github.com/` prefix. Strip this prefix in your answer.

Include only the `files` field with `.py` source files. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant `.py` files that reference `numpy.distutils`?
- **Keyword presence**: Does your narrative mention key terms like `numpy.distutils`, `deprecated`, and `vendored`?
