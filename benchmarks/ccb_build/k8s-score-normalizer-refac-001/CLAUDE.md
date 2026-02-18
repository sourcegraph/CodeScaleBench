# big-code-k8s-refac-001: Rename ScoreExtensions to ScoreNormalizer

This repository is large (~2.5M LOC). Use comprehensive search to find ALL references before making changes.

## Task Type: Cross-File Refactoring

Your goal is to rename the `ScoreExtensions` interface to `ScoreNormalizer` across the Kubernetes scheduler framework. Focus on:

1. **Complete identification**: Find ALL files that reference `ScoreExtensions` — the interface definition, the accessor method on `ScorePlugin`, all plugin implementations, the runtime framework, metrics constants, and test files
2. **Dependency ordering**: Change the interface definition first, then the runtime framework, then plugin implementations, then tests
3. **Consistency**: Ensure no stale references to `ScoreExtensions` remain after the refactoring
4. **Compilation**: Verify with `go build ./pkg/scheduler/...`

## Output Format

Write your analysis to `/logs/agent/solution.md` with these required sections:

```markdown
## Files Examined
- path/to/file.ext — why this file needs changes

## Dependency Chain
1. path/to/definition.ext (original definition)
2. path/to/user1.ext (direct reference)
3. path/to/user2.ext (transitive dependency)

## Code Changes
### path/to/file1.ext
\`\`\`diff
- old code
+ new code
\`\`\`

## Analysis
[Refactoring strategy and verification approach]
```

## Search Strategy

- Start with `pkg/scheduler/framework/interface.go` — this defines `ScoreExtensions`
- Use `find_references` on `ScoreExtensions` to find ALL usages across the scheduler
- Check `pkg/scheduler/framework/runtime/framework.go` for the runtime invocation
- Search `pkg/scheduler/framework/plugins/` for plugin implementations
- Check `pkg/scheduler/metrics/metrics.go` for the `ScoreExtensionNormalize` constant
- Search test files: `pkg/scheduler/framework/runtime/framework_test.go`, `pkg/scheduler/schedule_one_test.go`, `pkg/scheduler/testing/framework/`
- After changes, grep for `ScoreExtensions` to verify no stale references remain
