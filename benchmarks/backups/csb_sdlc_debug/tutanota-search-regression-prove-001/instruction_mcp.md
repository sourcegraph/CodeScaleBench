# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/tutanota--f373ac38`
- Use `repo:^github.com/sg-evals/tutanota--f373ac38$` filter in keyword_search
- Use `github.com/sg-evals/tutanota--f373ac38` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Bug Investigation: Non-legacy mail content fails to decrypt

**Repository:** github.com/sg-evals/tutanota--f373ac38 (mirror of tutao/tutanota)
**Task Type:** Find and Prove (write a regression test)

## Reported Issue

Users who have accounts with the new (non-legacy) permission model report that opening certain emails results in blank message bodies, missing reply-to addresses, and missing attachment listings. The browser console shows "Missing decryption key" errors when these mails are opened.

The issue specifically affects mails that use owner-encrypted session keys under the new permission model. Legacy mails continue to work correctly. The problem manifests when:

1. Opening a non-legacy mail in the inbox — the body fails to render
2. Opening a draft with reply-to recipients — the reply-to list cannot be loaded
3. The mail indexer/search encounters non-legacy mails — indexing fails silently with decryption errors

The root cause involves how encrypted session keys are propagated when loading related entities. When the application loads supplementary mail data (body content, draft details), the session key needed for decryption is available from the parent mail object but is not being passed through to the entity loading and caching layers. This means the loaded entities cannot be decrypted even though the necessary key exists.

Additionally, batch loading of multiple entities has the same propagation gap — when loading several related items at once, the per-entity session keys are not forwarded to the decryption step.

## Your Task

1. Investigate the codebase to find the root cause of the missing key propagation
2. Write a regression test as a single file at `/workspace/regression_test.test.ts`
3. Your test must be self-contained and runnable with `npx jest --timeout=60000 /workspace/regression_test.test.ts`

## Constraints

- Do NOT fix the bug — only write a test that demonstrates it
- Your test must fail for the RIGHT reason (decryption key not propagated, not some other error)
- Test timeout: 60 seconds
