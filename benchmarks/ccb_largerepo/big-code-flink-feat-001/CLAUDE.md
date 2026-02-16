# big-code-flink-feat-001: Implement PricingSessionWindow

This repository is large (~2M LOC). Use comprehensive search to understand existing patterns before implementing.

## Task Type: Feature Implementation

Your goal is to implement a new window assigner for financial trading sessions. Focus on:

1. **Pattern discovery**: Study existing window assigners (EventTimeSessionWindows, TumblingEventTimeWindows) to understand conventions
2. **File identification**: Identify ALL files that need creation or modification
3. **Implementation**: Write code that follows existing Flink windowing patterns
4. **Verification**: Ensure the implementation compiles within flink-streaming-java

## Key Reference Files

**Base classes (in flink-runtime):**
- `flink-runtime/src/main/java/org/apache/flink/streaming/api/windowing/assigners/WindowAssigner.java` — abstract base
- `flink-runtime/src/main/java/org/apache/flink/streaming/api/windowing/assigners/MergingWindowAssigner.java` — merging extension (extend this)
- `flink-runtime/src/main/java/org/apache/flink/streaming/api/windowing/windows/TimeWindow.java` — concrete window with Serializer
- `flink-runtime/src/main/java/org/apache/flink/streaming/api/windowing/triggers/Trigger.java` — trigger contract
- `flink-runtime/src/main/java/org/apache/flink/streaming/api/windowing/triggers/EventTimeTrigger.java` — reference trigger

**Reference implementations (in flink-streaming-java):**
- `flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/assigners/EventTimeSessionWindows.java` — primary model
- `flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/assigners/DynamicEventTimeSessionWindows.java` — dynamic gap pattern
- `flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/assigners/SessionWindowTimeGapExtractor.java` — extractor interface

**Integration:**
- `flink-runtime/src/main/java/org/apache/flink/streaming/api/datastream/KeyedStream.java` — `.window()` entry point
- `flink-runtime/src/main/java/org/apache/flink/streaming/api/datastream/WindowedStream.java` — operator wiring

## Flink Windowing Architecture (2.2.0)

- Base classes in `flink-runtime/`, concrete assigners in `flink-streaming-java/`
- Session-style windows extend `MergingWindowAssigner` (NOT plain `WindowAssigner`)
- `assignWindows()` creates `TimeWindow(start, end)` instances
- `mergeWindows()` delegates to `TimeWindow.mergeWindows()` utility
- Custom triggers implement `Trigger<T, W>` with `onElement()`, `onEventTime()`, `onProcessingTime()`
- Merging triggers must have `canMerge()=true` and implement `onMerge()`

## Output Format

Write your analysis to `/logs/agent/solution.md` with these required sections:

```markdown
## Files Examined
- path/to/file.ext — examined to understand [pattern/API/convention]

## Dependency Chain
1. Base classes: flink-runtime windowing
2. Reference implementations: flink-streaming-java assigners
3. New implementation: PricingSessionWindow, PricingSessionTrigger
4. Tests: PricingSessionWindowTest

## Code Changes
### path/to/file1.ext
\`\`\`diff
- old code
+ new code
\`\`\`

## Analysis
[Implementation strategy, design decisions, integration approach]
```

## Search Strategy

- Search for `MergingWindowAssigner` to find all merging window implementations
- Search for `EventTimeSessionWindows` to understand the session window pattern
- Search for `SessionWindowTimeGapExtractor` to understand the extractor interface
- Use `find_references` on `WindowAssigner` to see how assigners are used
