# Add Validation for Plugin Identifiers in Plugin Activation

**Repository:** NodeBB/NodeBB
**Language:** JavaScript
**Difficulty:** hard

## Problem

NodeBB's plugin activation system processes malformed plugin identifiers without proper validation. Any string is accepted as a plugin identifier, including names with whitespace, special characters, or incorrect formats. Administrators receive no feedback when providing incorrect plugin names, making it difficult to identify errors and potentially causing unexpected behavior.

## Key Components

- Plugin management/activation code — where plugin identifiers are processed
- Plugin naming conventions and expected patterns (e.g., `nodebb-plugin-*`, `nodebb-widget-*`)

## Task

1. Locate the plugin activation code path in NodeBB
2. Add validation that checks plugin identifiers against established naming patterns
3. Reject invalid identifiers (whitespace, special characters, incorrect format) with clear error messages
4. Ensure administrators receive immediate feedback when providing malformed plugin names
5. Run existing tests to ensure no regressions

## Success Criteria

- Plugin activation rejects malformed identifiers with clear error messages
- Valid plugin identifiers (matching expected naming patterns) are accepted as before
- Administrators receive immediate feedback on invalid input
- All existing tests pass

