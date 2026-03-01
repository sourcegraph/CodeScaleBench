# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repositories (version-pinned mirrors):**

- `github.com/sg-evals/terraform--7637a921` — use `repo:^github.com/sg-evals/terraform--7637a921$` filter
- `github.com/sg-evals/terraform--24236f4f` — use `repo:^github.com/sg-evals/terraform--24236f4f$` filter

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

**Sourcegraph Repositories:** `github.com/sg-evals/terraform--7637a921`, `github.com/sg-evals/terraform--24236f4f`

# Task: Terraform v1.9.0 to v1.10.0 Migration Guide

## Objective

Analyze the changes between Terraform v1.9.0 and v1.10.0 and produce a comprehensive migration guide for users upgrading from v1.9.0 to v1.10.0.

## Context

The workspace contains two versions of the Terraform codebase:
- **v1.9.0**: implemented in `/workspace/terraform-v1.9.0/` (commit 7637a92)
- **v1.10.0**: implemented in `/workspace/terraform-v1.10.0/` (commit 24236f4)

Your task is to identify breaking changes and behavioral changes that affect users, then document migration steps.

## Required Analysis

Your migration guide must cover:

1. **S3 Backend Changes**
   - Removal of deprecated IAM role assumption attributes
   - Migration to `assume_role` block syntax
   - New S3 native state locking support

2. **Moved Blocks Syntax Changes**
   - New requirement to prepend `resource.` identifier when referencing resources with type names matching top-level blocks/keywords
   - Impact on existing `moved` blocks in configurations

3. **Sensitive Value Handling**
   - Changes to mark propagation in conditional expressions
   - When sensitive marks are now preserved (previously lost)
   - How to use `nonsensitive()` to override when needed

4. **Ephemeral Resources and Values** (new feature with migration implications)
   - Introduction of ephemeral input variables and outputs
   - New ephemeral resource mode
   - Impact on secret handling in state files

## Expected Output

Write your migration guide to `/workspace/documentation.md` with the following structure:

1. **Overview** - Summary of the upgrade and major themes
2. **Breaking Changes** - Each breaking change with:
   - What changed and why
   - Before/after code examples
   - Step-by-step migration instructions
   - Common pitfalls to avoid
3. **New Features with Migration Impact** - Features that change how users should write Terraform
4. **Testing Your Migration** - How to validate the upgrade was successful
5. **Rollback Guidance** - How to safely rollback if needed

## Evaluation

Your review will be evaluated on detection accuracy and fix quality.

## Tips

- Compare the two version directories to identify changes in specific files
- Look for UPGRADE notes in release documentation
- Examine test files to understand behavioral changes
- Check for deprecation warnings and removed features
- Pay attention to changes in internal/backend/remote-state/s3/, internal/terraform/node_resource_abstract.go, and lang/marks/ directories

Good luck!
