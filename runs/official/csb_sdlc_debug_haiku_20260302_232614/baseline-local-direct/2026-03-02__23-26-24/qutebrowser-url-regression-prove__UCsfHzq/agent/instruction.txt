# Bug Investigation: URL Number Increment/Decrement Modifies Encoded Characters

**Repository:** qutebrowser/qutebrowser
**Task Type:** Find and Prove (write a regression test)

## Reported Issue

When users use qutebrowser's URL increment/decrement feature (the keyboard shortcuts to increase or decrease numeric values in URLs), the following incorrect behaviors occur:

1. **Encoded sequences are corrupted**: URLs containing percent-encoded characters with digits (such as `%3A` which represents a colon) have those digits incorrectly modified. For example, incrementing `http://localhost/%3A5` should only change the trailing `5`, but the operation also corrupts the `%3A` sequence.

2. **Negative values are allowed**: Decrementing a small number by a large count (e.g., decrementing `1` by `2`) produces a negative value in the URL instead of raising an error. For example, `http://example.com/page_1` decremented by 2 should produce an error, not `http://example.com/page_-1`.

3. **URL-encoded data is lost**: In some URL segments (host, path, query, anchor), the increment/decrement operation improperly decodes encoded characters, causing information loss. For example, `%20` (encoded space) may be decoded to a literal space, breaking the URL.

These issues affect all URL segments where increment/decrement operates: the host, path, query string, and anchor/fragment.

## Your Task

1. Investigate the codebase to find the root cause of these URL number manipulation bugs
2. Write a regression test as a single file at `/workspace/regression_test.py`
3. Your test must be self-contained and runnable with `python3 -m pytest -c /dev/null --timeout=60 /workspace/regression_test.py`

## Constraints

- Do NOT fix the bug — only write a test that demonstrates it
- Your test must fail on the current (buggy) code for the RIGHT reason
- The test should cover at least: encoded sequence corruption and negative value handling
- Test timeout: 60 seconds
