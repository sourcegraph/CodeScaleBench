# [Graph Partition] fix graph partition input signature for fallback kernels

**Repository:** pytorch  
**Difficulty:** EASY  
**Category:** cross_module_bug_fix



## Description

Scheduler relies on node.last_usage to free buffers. `last_usage` may contain a buffer that is allocated in previous graph partition AND not directly accessed in the current graph partition.


## Example
```python
def f(x):
    y = x + 1
    z = torch.ops.aten.view.dtype(y, torch.float8_e4m3fn)
    z_cpu = z.cpu()
    u_cuda = z_cpu.cuda()
    return u_cuda
```

In the generated code, we have
```
def partition_0(args):
    ...
    # Topologically Sorted Source Nodes: [y, z], Ori

## Task

Review the PR: [Graph Partition] fix graph partition input signature for fallback kernels

Description: Scheduler relies on node.last_usage to free buffers. `last_usage` may contain a buffer that is allocated in previous graph partition AND not directly accessed in the current graph partition.


## Example
```python
def f(x):
    y = x + 1
    z = torch.ops.aten.view.dtype(y, torch.float8_e4m3fn)
    z_cpu = z.cpu()
    u_cuda = z_cpu.cuda()
    return u_cuda
```

In the generated code, we have
```
def partition_0(args):
    ...
    # Topologically Sorted Source Nodes: [y, z], Ori

Changes:
- 2 files modified
- 26 additions, 0 deletions

Tasks:
1. Understand the issue being fixed
2. Review the solution in the merged PR
3. Implement the fix to pass all tests
4. Verify: run "make test" successfully

## Success Criteria

All tests pass: run "make test" successfully.
Code follows repository conventions.
No regressions in existing functionality.
All 2 modified files updated correctly.

## Testing

Run the test command to verify your implementation:

```bash
make test
```

**Time Limit:** 10 minutes  
**Estimated Context:** 8000 tokens
