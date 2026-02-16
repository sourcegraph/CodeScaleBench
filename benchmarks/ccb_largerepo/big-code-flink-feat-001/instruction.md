# big-code-flink-feat-001: Implement PricingSessionWindow for Financial Trading

## Task

Implement a custom `PricingSessionWindow` assigner in Apache Flink that groups trading events by market session boundaries (e.g., NYSE 09:30-16:00 ET, LSE 08:00-16:30 GMT) rather than fixed time intervals. This is a common requirement in capital markets streaming analytics where aggregations must align with trading sessions.

The implementation must follow Flink's existing windowing architecture:

1. **PricingSessionWindow** (`flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/assigners/PricingSessionWindow.java`):
   - Extends `MergingWindowAssigner<Object, TimeWindow>`
   - `assignWindows()`: Given an element's timestamp, determines which trading session it belongs to and returns a `TimeWindow(sessionOpen, sessionClose)` for that session
   - `mergeWindows()`: Delegates to `TimeWindow.mergeWindows()` for overlapping window consolidation
   - Factory method: `PricingSessionWindow.forMarket(String marketId, ZoneId timezone, LocalTime open, LocalTime close)`
   - Must handle pre/post-market sessions and overnight sessions (e.g., futures markets)
   - Returns `EventTimeTrigger` as default trigger

2. **PricingSessionTrigger** (`flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/triggers/PricingSessionTrigger.java`):
   - Extends `Trigger<Object, TimeWindow>`
   - Fires at market close (window end) via event-time timer
   - Supports early firing on configurable events (e.g., circuit breaker halts)
   - `canMerge()` returns `true`, `onMerge()` re-registers timers
   - `clear()` cleans up all registered timers

3. **TradingSessionExtractor** (`flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/assigners/TradingSessionExtractor.java`):
   - Functional interface for extracting market ID from stream elements
   - Modeled after `SessionWindowTimeGapExtractor`
   - Enables dynamic session assignment based on element content

Study existing window implementations, particularly `EventTimeSessionWindows` and `DynamicEventTimeSessionWindows`, for the complete pattern.

## Context

- **Repository**: apache/flink (Java, ~2M LOC)
- **Category**: Feature Implementation
- **Difficulty**: hard
- **Subsystem Focus**: flink-streaming-java windowing, flink-runtime windowing base classes

## Requirements

1. Identify all files that need creation or modification
2. Follow existing Flink windowing patterns (`WindowAssigner`, `MergingWindowAssigner`, `Trigger`)
3. Implement the window assigner with actual code changes
4. Ensure the implementation compiles within the flink-streaming-java module

## Expected Output

Write your analysis to `/logs/agent/solution.md` with the following structure:

```markdown
## Files Examined
- path/to/file1.ext — examined to understand [pattern/API/convention]
- path/to/file2.ext — modified to add [feature component]
...

## Dependency Chain
1. Define types/interfaces: path/to/types.ext
2. Implement core logic: path/to/impl.ext
3. Wire up integration: path/to/integration.ext
4. Add tests: path/to/tests.ext
...

## Code Changes
### path/to/file1.ext
```diff
- old code
+ new code
```

### path/to/file2.ext
```diff
- old code
+ new code
```

## Analysis
[Explanation of implementation strategy, design decisions, and how the feature
integrates with existing architecture]
```

## Evaluation Criteria

- Compilation: Does the code compile after changes?
- File coverage: Did you modify all necessary files?
- Pattern adherence: Do changes follow existing codebase conventions?
- Feature completeness: Is the feature fully implemented?
