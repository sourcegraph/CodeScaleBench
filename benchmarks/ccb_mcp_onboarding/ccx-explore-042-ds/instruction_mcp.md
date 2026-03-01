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

# Architecture Map: Scientific Computing Data Flow

## Your Task

You are onboarding to a scientific computing team that uses the Python ML stack.
A senior engineer has asked you to produce a technical map of how data flows from
**raw array creation through scientific computation** across the three core libraries:
numpy, pandas, and scipy.

**Your question**: Map the data flow from raw array creation through scientific
computation across these repos. Your explanation must trace through all three layers:

1. **Array computation layer** — What function in `numpy/numpy` is the canonical
   entry point for array-level aggregation on raw ndarray objects?
2. **Data structure layer** — What class in `pandas-dev/pandas` wraps a NumPy ndarray
   as a pandas extension array, enabling interoperability between the two libraries?
3. **Scientific computation layer** — What function in `scipy/scipy` accepts numpy
   arrays (or pandas Series) as inputs for statistical analysis?

For each step, cite the specific repository, file path, and function/class name.

## Context

You are working with the Python ML stack in a cross-org environment:

- `scikit-learn/scikit-learn` (ML algorithms)
- `numpy/numpy` (array-computing)
- `pandas-dev/pandas` (dataframe-library)
- `scipy/scipy` (scientific-computing)

This question is specifically designed to benefit from cross-repo synthesis. The
data flow spans multiple organizations and can only be fully understood by examining
all three repos together.

## Output Format

Create a file at `/workspace/answer.json` with your findings:

```json
{
  "chain": [
    {
      "repo": "numpy/numpy",
      "path": "relative/path/to/file.py",
      "symbol": "FunctionOrClassName",
      "description": "What role this plays in the data flow"
    }
  ],
  "text": "Comprehensive narrative explaining how data flows from raw array creation through scientific computation, citing specific files and functions from each repo."
}
```

**Important**: Use exact repo identifiers as they appear in Sourcegraph. The oracle expects `repo` values of `numpy/numpy` (array layer), `pandas-dev/pandas` (data structure layer), and `scipy/scipy` (scientific computation layer). The `repo` field must match these exactly.
**Note**: Sourcegraph MCP tools return repo names with a `github.com/` prefix (e.g., `github.com/sg-evals/kubernetes-client-go`). Strip this prefix in your answer — use `sg-evals/kubernetes-client-go`, NOT `github.com/sg-evals/kubernetes-client-go`.
**Provenance**: Your `text` narrative is evaluated for completeness. It must include repository names verbatim in `org/repo` format (e.g., `numpy/numpy`, `pandas-dev/pandas`, `scipy/scipy`) and file paths using slash notation (e.g., `numpy/_core/fromnumeric.py`), not Python module dot notation.

The `chain` should contain at least 3 steps representing the 3 layers described above.

## Evaluation

Your answer will be scored on:
- **Flow coverage**: Does the chain include key steps from all 3 layers (array creation → pandas integration → scipy computation)?
- **Technical accuracy**: Are the cited file paths and function/class names correct?
- **Provenance**: Does your narrative reference all three repositories with specific file paths?
- **Synthesis quality** (supplementary): Does the explanation connect the layers in a way that reveals the ecosystem architecture?
