# Fix Windows Log Output Line Ending Normalization

**Repository:** navidrome/navidrome
**Language:** Go
**Difficulty:** hard

## Problem

Navidrome does not format log output correctly for Windows users. Logs use only line feed characters (`\n`), which makes them hard to read in standard Windows text editors. When existing carriage return + line feed sequences (`\r\n`) are present, they may not be preserved correctly. Logs written in multiple partial steps can also produce inconsistent line endings.

## Reproduction

1. Start Navidrome on Windows and generate some log output
2. Open the log file in Notepad and check the line endings
3. Write logs that include only line feeds, as well as logs with existing carriage returns and line feeds
4. Observe that the formatting is incorrect or inconsistent

## Key Components

- Log output/formatting code — where log lines are written to output
- Platform-specific line ending handling (Windows vs. Unix)

## Task

1. Locate the log output formatting code in Navidrome
2. On Windows, convert `\n` line endings to `\r\n` in log output
3. Preserve existing `\r\n` sequences without double-conversion (don't produce `\r\r\n`)
4. Ensure correct behavior when logs are written in multiple partial steps
5. Run existing tests to ensure no regressions

## Success Criteria

- Log output on Windows uses `\r\n` line endings
- Existing `\r\n` sequences are preserved unchanged
- Partial/multi-step log writes produce consistent line endings
- Unix behavior is unchanged
- All existing tests pass

