# Bug Investigation: Dark Mode Text Threshold Setting Has No Effect on Qt 6.4

**Repository:** qutebrowser/qutebrowser
**Task Type:** Find and Prove (write a regression test)

## Reported Issue

When users configure the dark mode text brightness threshold setting (`colors.webpage.darkmode.threshold.text`) and qutebrowser is running with Qt version 6.4, the setting has no effect on dark mode rendering.

Users report that setting the threshold to any value (for example, `100`) does not change the dark mode behavior. The exact same configuration works correctly on Qt 6.3 and earlier versions.

This only affects the text/foreground threshold setting. Other dark mode settings (algorithm, grayscale, image policy) work correctly on the same Qt version.

## Your Task

1. Investigate the codebase to find the root cause of the ignored threshold setting
2. Write a regression test as a single file at `/workspace/regression_test.py`
3. Your test must be self-contained and runnable with `python3 -m pytest -c /dev/null --timeout=60 /workspace/regression_test.py`

## Constraints

- Do NOT fix the bug — only write a test that demonstrates it
- Your test must fail on the current (buggy) code for the RIGHT reason
- The test should verify that the text threshold setting produces the expected configuration output for Qt 6.4
- Test timeout: 60 seconds
