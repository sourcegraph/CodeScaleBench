# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-benchmarks/pytorch--cbe1a35d`
- Use `repo:^github.com/sg-benchmarks/pytorch--cbe1a35d$` filter in keyword_search
- Use `github.com/sg-benchmarks/pytorch--cbe1a35d` as the `repo` parameter for go_to_definition/find_references/read_file


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

# [dynamo] fix keyerror in resume_execution,  fix store attr

**Repository:** github.com/sg-benchmarks/pytorch--cbe1a35d (mirror of pytorch)  
**Difficulty:** MEDIUM  
**Category:** cross_module_bug_fix



## Description

This task fixes two related bugs in PyTorch's Dynamo compiler: a `KeyError` crash during resume code generation on Python 3.11+ and incorrect handling of `STORE_ATTR` instructions in `with` blocks after graph breaks. The `KeyError` occurs in `resume_execution.py` when Dynamo tries to reconstruct bytecode for resuming execution after a graph break inside nested context managers (e.g., nested `torch.no_grad()` blocks), because the exception table entry remapping fails to find target offsets.

The fix restructures the offset remapping logic in `torch/_dynamo/resume_execution.py` and adjusts `symbolic_convert.py` to correctly handle exception table entries and store-attribute operations, moving test cases from `test_repros.py` to the more appropriate `test_ctx_manager.py`. Without the fix, any `torch.compile`-d function with graph breaks inside nested context managers crashes on Python 3.11+.

## Task

Changes:
- 4 files modified (resume_execution.py, symbolic_convert.py, test_repros.py, test_ctx_manager.py)
- 153 additions, 89 deletions

Tasks:
1. Fix offset remapping logic in `torch/_dynamo/resume_execution.py`
2. Adjust `symbolic_convert.py` for correct exception table entry and STORE_ATTR handling
3. Move and update test cases in test_ctx_manager.py
4. Verify your changes compile and match the expected fix

## Success Criteria

Code changes match the expected ground-truth fix.
Code follows repository conventions.
No regressions in existing functionality.
All 4 modified files updated correctly.

## Testing

Your implementation will be automatically verified:

```
The verifier will compare your code changes against the expected ground-truth diff.
Score = 0.35 * file_recall + 0.45 * line_recall + 0.20 * line_precision
```

**Time Limit:** 10 minutes  
**Estimated Context:** 8000 tokens
