# Task: Fix Late Data Side Output Handling for Merging Windows in Flink

## Objective
Fix a bug in Apache Flink's windowing operator where late-arriving data elements that should be emitted to a side output (via `OutputTag`) are silently dropped when using session windows (merging windows). The bug occurs because the merging window operator's `processElement()` method checks lateness BEFORE merging, so an element that arrives after the watermark but could extend a session window is incorrectly classified as late and then the side output emission is skipped because the output tag is null at that point in the code path.

## Bug Description
When using event-time session windows with `allowedLateness(Time.seconds(0))` and a `sideOutputLateData(lateTag)` configuration:
1. An element arrives with a timestamp past the current watermark
2. The `WindowOperator.processElement()` method calls `isElementLate()` which returns true
3. For merging windows, this element could have been merged into an existing window that hasn't been cleaned up yet
4. The late element handling code path attempts `sideOutput()` but the output collector may not have the tag registered, causing the element to be silently dropped

## Requirements

1. **Locate the root cause** in the window operator:
   - Find `WindowOperator.processElement()` or `EvictingWindowOperator.processElement()`
   - Identify where `isElementLate()` is called relative to the merge operation
   - Trace how `sideOutputLateData` interacts with the `OutputTag` in the late path

2. **Fix the late element handling**:
   - Ensure late elements for merging windows check whether the element could be merged into an existing (non-expired) window BEFORE marking as late
   - OR ensure the side output path correctly emits the element via the registered OutputTag
   - The fix should be in `flink-runtime/src/main/java/org/apache/flink/streaming/runtime/operators/windowing/`

3. **Ensure correct OutputTag wiring**:
   - Verify that `sideOutput()` receives the correct `OutputTag<T>` for late data
   - Check `AbstractStreamOperator` or `Output` interface for side output dispatch

4. **Write a test case**:
   - Create or extend a test in `flink-streaming-java/src/test/java/.../windowing/`
   - Test: session window with `sideOutputLateData(tag)` + element arriving after watermark
   - Verify: late element appears in the side output stream, not silently dropped

## Key Reference Files
- `flink-runtime/src/main/java/org/apache/flink/streaming/runtime/operators/windowing/WindowOperator.java` — main window operator
- `flink-runtime/src/main/java/org/apache/flink/streaming/runtime/operators/windowing/EvictingWindowOperator.java` — evicting variant
- `flink-runtime/src/main/java/org/apache/flink/streaming/api/windowing/assigners/MergingWindowAssigner.java` — merging window base
- `flink-streaming-java/src/main/java/org/apache/flink/streaming/api/datastream/SingleOutputStreamOperator.java` — sideOutputLateData API
- `flink-runtime/src/main/java/org/apache/flink/streaming/api/operators/AbstractStreamOperator.java` — base operator with output handling
- `flink-streaming-java/src/test/java/org/apache/flink/streaming/runtime/operators/windowing/WindowOperatorTest.java` — existing tests

## Success Criteria
- Root cause identified: late element check order relative to window merge
- Fix applied to window operator's processElement or late-element path
- OutputTag correctly wired for side output emission
- Side output late data emission works for merging windows
- Test case added covering the late data + session window scenario
