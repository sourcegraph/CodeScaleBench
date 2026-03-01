# Bug Investigation: Application Crashes When Ad-Blocker Cache Is Corrupted

**Repository:** qutebrowser/qutebrowser
**Task Type:** Find and Prove (write a regression test)

## Reported Issue

When qutebrowser starts up and attempts to load the ad-blocker filter cache, the application crashes if the cache file is corrupted or contains invalid data.

The expected behavior is that the application handles corrupted cache files gracefully — it should log an error, discard the invalid cache, and continue running normally (allowing the user to browse without ad blocking until the cache is rebuilt).

Instead, the deserialization error propagates as an unhandled exception, causing a crash before the browser window even appears. Users who encounter a corrupted cache file cannot use qutebrowser at all until they manually delete the cache file.

This is particularly problematic because cache corruption can happen for reasons outside the user's control, such as a system crash or disk error during a cache write.

## Your Task

1. Investigate the codebase to find the root cause of the unhandled exception during cache loading
2. Write a regression test as a single file at `/workspace/regression_test.py`
3. Your test must be self-contained and runnable with `python3 -m pytest -c /dev/null --timeout=60 /workspace/regression_test.py`

## Constraints

- Do NOT fix the bug — only write a test that demonstrates it
- Your test must fail on the current (buggy) code for the RIGHT reason
- The test should simulate a corrupted cache file and verify the crash occurs
- Test timeout: 60 seconds
