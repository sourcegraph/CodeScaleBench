# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-benchmarks/linux--07cc49f6`
- Use `repo:^github.com/sg-benchmarks/linux--07cc49f6$` filter in keyword_search
- Use `github.com/sg-benchmarks/linux--07cc49f6` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Fault Localization: NFS Mount Disappears Due to Inode Revalidate Failure

- **Repository**: github.com/sg-benchmarks/linux--07cc49f6 (mirror of torvalds/linux)
- **Kernel Version**: 4.1.15
- **Difficulty**: expert
- **Category**: fault_localization
- **Subsystem**: File System
- **Component**: NFS / SunRPC

## Bug Report

**Bug ID**: 117651
**Summary**: Root NFS and autofs - mount disappears due to inode revalidate failed
**Regression**: Yes (works on 3.14.12, broken on 4.1.15)

After upgrading from 3.14.12 to 4.1.15 I've got strange behaviour with autofs.

It happens on diskless machine with root on NFS. There is autofs indirect mount on /storage, where NFS volumes are mounted on demand.

Everything mounts normally, but after mount expiration (during unmount) autofs mount disappears - that is, not only /storage/<volume> unmounts, but /storage is also unmounted. This happens quite often - usually on the very first expiration.

automount logs umount error in such cases.

Without autofs, mount/umount of the same NFS volume works correctly.

With NFS debug enabled, I've got following errors:

```
NFS reply getattr: -512
nfs_revalidate_inode: (0:15/6291480) getattr failed, error=-512
NFS: nfs_lookup_revalidate(/storage) is invalid
```

After inode revalidate failure all mounts on this inode are unmounted and so autofs mount disappears, while automount daemon itself continue to run.

tcpdump shows, that server replies to getattr without error, but client doesn't see this reply, and returning error instead.

I am ready to supply additional information.

## Task

You are a fault localization agent. Given the bug report above, your task is to identify the **exact source file(s)** and **function(s)/data structure(s)** in the Linux kernel source tree (at `/workspace`) that need to be modified to fix this bug.

You must:
1. Analyze the bug report to understand the symptoms and context
2. Search the kernel source code to identify the relevant subsystem and files
3. Narrow down to the specific file(s) and function(s)/data structure(s) that contain the bug or need modification
4. Write your findings to `/workspace/fault_localization_result.json` in the following format:

```json
{
  "buggy_files": ["path/to/file.c"],
  "buggy_functions": ["function_or_struct_name"],
  "confidence": 0.8,
  "reasoning": "Brief explanation of why these locations are the fault"
}
```

**Important**: Paths should be relative to the kernel source root (e.g., `kernel/sched/core.c`, not `/workspace/kernel/sched/core.c`).

## Success Criteria

- [ ] Correctly identify the buggy file(s)
- [ ] Correctly identify the buggy function(s) or data structure(s)
- [ ] Write results to `/workspace/fault_localization_result.json`
- [ ] Provide reasoning for the localization

## Testing

- **Time limit**: 1800 seconds
- Run `bash /tests/test.sh` to verify your findings
