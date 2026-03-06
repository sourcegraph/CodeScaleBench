# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/ClickHouse--v24.12`
- Use `repo:^github.com/sg-evals/ClickHouse--v24.12$` filter in keyword_search
- Use `github.com/sg-evals/ClickHouse--v24.12` as the `repo` parameter for go_to_definition/find_references/read_file


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

**Sourcegraph Repository:** `github.com/sg-evals/ClickHouse--v24.12`

# Task: Understand ClickHouse MergeTree Storage Engine Architecture

## Objective
Produce a comprehensive architecture analysis of the MergeTree storage engine, the core table engine in ClickHouse, covering its data organization, merge process, and query execution path.

## Steps
1. Find the MergeTree implementation in `src/Storages/MergeTree/`
2. Trace the write path: how INSERTs create new data parts
3. Trace the merge path: how background merges combine parts
4. Trace the read path: how SELECT queries scan parts with index skipping
5. Create `architecture_analysis.md` in `/workspace/` documenting:
   - High-level MergeTree architecture diagram (text-based)
   - Data part structure (columns, marks, primary index, skip indices)
   - Write path: from INSERT to committed part
   - Merge path: merge selection, merge algorithm, part replacement
   - Read path: part pruning, mark selection, column reading
   - Key source files with their roles
   - At least 10 specific file paths referenced

## Key Reference Files
- `src/Storages/MergeTree/MergeTreeData.h` — base class
- `src/Storages/MergeTree/MergeTreeDataWriter.cpp` — write path
- `src/Storages/MergeTree/MergeTreeDataMergerMutator.cpp` — merge logic
- `src/Storages/MergeTree/MergeTreeDataSelectExecutor.cpp` — read path

## Success Criteria
- architecture_analysis.md exists
- Covers write, merge, and read paths
- References at least 10 specific source files
- Describes data part structure
