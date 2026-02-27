# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-benchmarks/ansible--b2a289dc`
- Use `repo:^github.com/sg-benchmarks/ansible--b2a289dc$` filter in keyword_search
- Use `github.com/sg-benchmarks/ansible--b2a289dc` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Bug Investigation: Galaxy Collection Tar Directory Extraction Fails for Certain Archive Layouts

**Repository:** github.com/sg-benchmarks/ansible--b2a289dc (mirror of ansible/ansible)
**Task Type:** Find and Prove (write a regression test)

## Reported Issue

When installing Ansible Galaxy collections from tarball archives, the extraction process fails or behaves incorrectly for archives where directory entries have trailing path separators in their member names.

Specifically:

1. **Directory lookup uses a custom cache instead of standard tarfile API**: The collection installation code builds a private normalized-name index of tar members and uses that for directory lookups, rather than using the standard library's member lookup. This custom cache strips trailing path separators from names, which creates a fragile mismatch between how directories are looked up versus how they're actually stored in the archive.

2. **Extraction breaks when member names don't match the normalized form**: If a tar archive stores a directory entry with its canonical name (without a trailing separator), but the custom cache was built expecting to strip separators, the lookup can silently retrieve the wrong member or fail entirely.

3. **The workaround is no longer necessary**: The custom cache was originally added as a workaround for a CPython tarfile bug. On current Python versions, the standard `getmember()` API handles directory member lookups correctly, making the workaround unnecessary overhead that adds fragility.

These issues affect `ansible-galaxy collection install` when processing collection tarballs.

## Your Task

1. Investigate the codebase to find the root cause of the tar directory extraction fragility
2. Write a regression test as a single file at `/workspace/regression_test.py`
3. Your test must be self-contained and runnable with `python3 -m pytest --timeout=60 /workspace/regression_test.py`

## Constraints

- Do NOT fix the bug — only write a test that demonstrates it
- Your test must fail on the current (buggy) code for the RIGHT reason
- The test should cover: directory extraction behavior with standard tar member names, demonstrating the fragility of the custom cache approach
- Test timeout: 60 seconds
