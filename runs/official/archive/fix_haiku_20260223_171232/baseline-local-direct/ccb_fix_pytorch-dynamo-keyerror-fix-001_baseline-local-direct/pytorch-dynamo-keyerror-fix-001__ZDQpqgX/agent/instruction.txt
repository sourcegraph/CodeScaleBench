# [dynamo] fix keyerror in resume_execution,  fix store attr

**Repository:** pytorch  
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
