# Bug Investigation: HSV Color Percentage Parsing Produces Wrong Hue Values

**Repository:** qutebrowser/qutebrowser
**Task Type:** Find and Prove (write a regression test)

## Reported Issue

When users specify colors in the qutebrowser configuration using HSV (Hue-Saturation-Value) notation with percentage values, the hue component is calculated incorrectly.

The hue channel in HSV color space has a valid range of 0-359 degrees. However, the color parser incorrectly scales hue percentages using a maximum of 255 instead of 359. This means:

- `hsv(100%, 100%, 100%)` is parsed as `(255, 255, 255)` instead of the correct `(359, 255, 255)`
- `hsv(50%, 50%, 50%)` produces hue 127 instead of the correct hue 179

The saturation and value channels (which correctly use 0-255 range) are not affected — only the hue channel has this scaling error.

The same bug affects HSVA notation (HSV with alpha channel). For example, `hsva(100%, 100%, 100%, 100%)` also produces the wrong hue value.

## Your Task

1. Investigate the codebase to find the root cause of the incorrect hue scaling
2. Write a regression test as a single file at `/workspace/regression_test.py`
3. Your test must be self-contained and runnable with `python3 -m pytest -c /dev/null --timeout=60 /workspace/regression_test.py`

## Constraints

- Do NOT fix the bug — only write a test that demonstrates it
- Your test must fail on the current (buggy) code for the RIGHT reason
- The test should verify both HSV and HSVA percentage parsing
- Test timeout: 60 seconds
