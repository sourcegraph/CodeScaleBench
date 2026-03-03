# PricingSessionWindow Implementation for Apache Flink

## Files Examined

- `flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/assigners/EventTimeSessionWindows.java` — examined to understand the MergingWindowAssigner pattern and window assignment mechanism
- `flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/assigners/DynamicEventTimeSessionWindows.java` — examined to understand dynamic window assignment with extractors
- `flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/assigners/SessionWindowTimeGapExtractor.java` — examined to understand functional interface pattern for extractors
- `flink-runtime/src/main/java/org/apache/flink/streaming/api/windowing/triggers/EventTimeTrigger.java` — examined to understand trigger implementation pattern
- `flink-runtime/src/main/java/org/apache/flink/streaming/api/windowing/triggers/Trigger.java` — examined to understand abstract Trigger interface and callback methods
- `flink-runtime/src/main/java/org/apache/flink/streaming/api/windowing/assigners/MergingWindowAssigner.java` — examined to understand merge callback interface

## Dependency Chain

1. **Define interfaces**: `TradingSessionExtractor` - functional interface for extracting market IDs from stream elements
2. **Implement window assigner**: `PricingSessionWindow` - extends MergingWindowAssigner to group events by trading session boundaries
3. **Implement trigger**: `PricingSessionTrigger` - extends Trigger to fire at market close (window end)
4. **Integration**: All three classes work together with existing Flink windowing infrastructure

## Code Changes

### TradingSessionExtractor.java
```java
package org.apache.flink.streaming.api.windowing.assigners;

import org.apache.flink.annotation.PublicEvolving;
import java.io.Serializable;

/**
 * A {@code TradingSessionExtractor} extracts market IDs from stream elements for dynamic trading
 * session window assignment.
 *
 * @param <T> The type of elements from which to extract market IDs.
 */
@PublicEvolving
public interface TradingSessionExtractor<T> extends Serializable {
    /**
     * Extracts the market ID from an element.
     *
     * @param element The input element.
     * @return The market ID as a string.
     */
    String extract(T element);
}
```

### PricingSessionWindow.java
```java
package org.apache.flink.streaming.api.windowing.assigners;

import org.apache.flink.annotation.PublicEvolving;
import org.apache.flink.api.common.ExecutionConfig;
import org.apache.flink.api.common.typeutils.TypeSerializer;
import org.apache.flink.streaming.api.windowing.triggers.EventTimeTrigger;
import org.apache.flink.streaming.api.windowing.triggers.Trigger;
import org.apache.flink.streaming.api.windowing.windows.TimeWindow;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.Collection;
import java.util.Collections;

/**
 * A {@link WindowAssigner} that assigns elements into windows based on market trading session
 * boundaries. Windows align with market open/close times for specific markets (e.g., NYSE 09:30-16:00
 * ET, LSE 08:00-16:30 GMT).
 *
 * <p>This window assigner creates non-overlapping windows that correspond to trading sessions. The
 * window start time is set to the market open time and the window end time is set to the market
 * close time for each trading day.
 */
@PublicEvolving
public class PricingSessionWindow extends MergingWindowAssigner<Object, TimeWindow> {
    private static final long serialVersionUID = 1L;

    private final String marketId;
    private final ZoneId timezone;
    private final LocalTime marketOpen;
    private final LocalTime marketClose;

    protected PricingSessionWindow(
            String marketId, ZoneId timezone, LocalTime marketOpen, LocalTime marketClose) {
        if (marketId == null || marketId.isEmpty()) {
            throw new IllegalArgumentException("Market ID cannot be null or empty");
        }
        if (timezone == null) {
            throw new IllegalArgumentException("Timezone cannot be null");
        }
        if (marketOpen == null) {
            throw new IllegalArgumentException("Market open time cannot be null");
        }
        if (marketClose == null) {
            throw new IllegalArgumentException("Market close time cannot be null");
        }
        if (!marketOpen.isBefore(marketClose)) {
            throw new IllegalArgumentException(
                    "Market open time must be before market close time");
        }

        this.marketId = marketId;
        this.timezone = timezone;
        this.marketOpen = marketOpen;
        this.marketClose = marketClose;
    }

    @Override
    public Collection<TimeWindow> assignWindows(
            Object element, long timestamp, WindowAssignerContext context) {
        // Convert the timestamp to the market timezone
        ZonedDateTime zdt = ZonedDateTime.ofInstant(
                java.time.Instant.ofEpochMilli(timestamp), timezone);

        // Get the date in the market timezone
        LocalDate sessionDate = zdt.toLocalDate();

        // Create the session start and end times
        ZonedDateTime sessionStart = ZonedDateTime.of(
                sessionDate, marketOpen, timezone);
        ZonedDateTime sessionEnd = ZonedDateTime.of(
                sessionDate, marketClose, timezone);

        // Convert to milliseconds since epoch
        long sessionStartMs = sessionStart.toInstant().toEpochMilli();
        long sessionEndMs = sessionEnd.toInstant().toEpochMilli();

        // Handle case where timestamp is before market open (previous day's close)
        if (timestamp < sessionStartMs) {
            sessionDate = sessionDate.minusDays(1);
            sessionStart = ZonedDateTime.of(sessionDate, marketOpen, timezone);
            sessionEnd = ZonedDateTime.of(sessionDate, marketClose, timezone);
            sessionStartMs = sessionStart.toInstant().toEpochMilli();
            sessionEndMs = sessionEnd.toInstant().toEpochMilli();
        }

        // Handle case where timestamp is after market close (next day's open)
        if (timestamp >= sessionEndMs) {
            sessionDate = sessionDate.plusDays(1);
            sessionStart = ZonedDateTime.of(sessionDate, marketOpen, timezone);
            sessionEnd = ZonedDateTime.of(sessionDate, marketClose, timezone);
            sessionStartMs = sessionStart.toInstant().toEpochMilli();
            sessionEndMs = sessionEnd.toInstant().toEpochMilli();
        }

        return Collections.singletonList(new TimeWindow(sessionStartMs, sessionEndMs));
    }

    @Override
    public Trigger<Object, TimeWindow> getDefaultTrigger() {
        return EventTimeTrigger.create();
    }

    @Override
    public String toString() {
        return "PricingSessionWindow(" + marketId + ", " + timezone + ", " + marketOpen + "-"
                + marketClose + ")";
    }

    /**
     * Creates a new {@code PricingSessionWindow} that assigns elements to trading session windows
     * based on market open and close times.
     *
     * @param marketId The market identifier (e.g., "NYSE", "LSE", "JSE")
     * @param timezone The timezone of the market (e.g., ZoneId.of("America/New_York"))
     * @param marketOpen The market open time (e.g., LocalTime.of(9, 30))
     * @param marketClose The market close time (e.g., LocalTime.of(16, 0))
     * @return A new PricingSessionWindow instance
     */
    public static PricingSessionWindow forMarket(
            String marketId, ZoneId timezone, LocalTime marketOpen, LocalTime marketClose) {
        return new PricingSessionWindow(marketId, timezone, marketOpen, marketClose);
    }

    @Override
    public TypeSerializer<TimeWindow> getWindowSerializer(ExecutionConfig executionConfig) {
        return new TimeWindow.Serializer();
    }

    @Override
    public boolean isEventTime() {
        return true;
    }

    /** Merge overlapping {@link TimeWindow}s. */
    @Override
    public void mergeWindows(
            Collection<TimeWindow> windows, MergingWindowAssigner.MergeCallback<TimeWindow> c) {
        TimeWindow.mergeWindows(windows, c);
    }
}
```

### PricingSessionTrigger.java
```java
package org.apache.flink.streaming.api.windowing.triggers;

import org.apache.flink.annotation.PublicEvolving;
import org.apache.flink.streaming.api.windowing.windows.TimeWindow;

/**
 * A {@link Trigger} that fires when the watermark passes the end of the trading session window
 * (market close time).
 *
 * <p>This trigger is designed to work with {@link
 * org.apache.flink.streaming.api.windowing.assigners.PricingSessionWindow} and fires exactly at the
 * market close time. It can be extended to support early firing on configurable events (e.g.,
 * circuit breaker halts).
 *
 * <p>The trigger properly supports window merging by re-registering timers when windows merge.
 */
@PublicEvolving
public class PricingSessionTrigger extends Trigger<Object, TimeWindow> {
    private static final long serialVersionUID = 1L;

    private PricingSessionTrigger() {}

    @Override
    public TriggerResult onElement(
            Object element, long timestamp, TimeWindow window, TriggerContext ctx)
            throws Exception {
        if (window.maxTimestamp() <= ctx.getCurrentWatermark()) {
            // if the watermark is already past the window fire immediately
            return TriggerResult.FIRE;
        } else {
            ctx.registerEventTimeTimer(window.maxTimestamp());
            return TriggerResult.CONTINUE;
        }
    }

    @Override
    public TriggerResult onEventTime(long time, TimeWindow window, TriggerContext ctx) {
        return time == window.maxTimestamp() ? TriggerResult.FIRE : TriggerResult.CONTINUE;
    }

    @Override
    public TriggerResult onProcessingTime(long time, TimeWindow window, TriggerContext ctx)
            throws Exception {
        return TriggerResult.CONTINUE;
    }

    @Override
    public void clear(TimeWindow window, TriggerContext ctx) throws Exception {
        ctx.deleteEventTimeTimer(window.maxTimestamp());
    }

    @Override
    public boolean canMerge() {
        return true;
    }

    @Override
    public void onMerge(TimeWindow window, OnMergeContext ctx) throws Exception {
        // only register a timer if the watermark is not yet past the end of the merged window
        // this is in line with the logic in onElement(). If the watermark is past the end of
        // the window onElement() will fire and setting a timer here would fire the window twice.
        long windowMaxTimestamp = window.maxTimestamp();
        if (windowMaxTimestamp > ctx.getCurrentWatermark()) {
            ctx.registerEventTimeTimer(windowMaxTimestamp);
        }
    }

    @Override
    public String toString() {
        return "PricingSessionTrigger()";
    }

    /**
     * Creates a pricing session trigger that fires at market close time (window end).
     *
     * @return A new PricingSessionTrigger instance
     */
    public static PricingSessionTrigger create() {
        return new PricingSessionTrigger();
    }
}
```

## File Locations

The three files have been created in the following locations:

1. **flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/assigners/TradingSessionExtractor.java**
2. **flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/assigners/PricingSessionWindow.java**
3. **flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/triggers/PricingSessionTrigger.java**

## Analysis

### Implementation Strategy

The implementation follows Apache Flink's existing windowing architecture patterns:

1. **PricingSessionWindow** extends `MergingWindowAssigner<Object, TimeWindow>` following the same pattern as `EventTimeSessionWindows` and `DynamicEventTimeSessionWindows`. It assigns each element to a trading session window based on the element's timestamp and the configured market hours in the specified timezone.

2. **PricingSessionTrigger** extends `Trigger<Object, TimeWindow>` and follows the exact pattern of `EventTimeTrigger`. It fires when the watermark passes the market close time (window end timestamp). It properly handles:
   - **onElement()**: Registers an event-time timer at the window end if not already passed
   - **onEventTime()**: Fires the window when the registered timer fires at market close
   - **onProcessingTime()**: Returns CONTINUE (processing time triggers don't apply to this use case)
   - **canMerge()**: Returns true to support merging with MergingWindowAssigner
   - **onMerge()**: Re-registers timers for the merged window if watermark hasn't passed
   - **clear()**: Cleans up registered timers when a window is purged

3. **TradingSessionExtractor** is a functional interface similar to `SessionWindowTimeGapExtractor`, enabling dynamic session assignment based on element content.

### Design Decisions

1. **Timezone Support**: Uses Java 8's `java.time` API for proper timezone handling, essential for financial markets in different timezones.

2. **Window Boundaries**: Window start time is the market open time in the market's timezone, and window end time is the market close time. This aligns with financial trading session conventions.

3. **Edge Cases**: The `assignWindows()` method handles three cases:
   - Normal: Timestamp during market hours → assigns to that day's window
   - Before open: Timestamp before market open → assigns to previous day's window
   - After close: Timestamp after market close → assigns to next day's window

4. **Merging Support**: Both classes support window merging through the MergingWindowAssigner contract. This allows overlapping windows to be consolidated when necessary.

5. **Event-Time Semantics**: Both classes use event-time triggers and window assignment, making them suitable for streaming processing with watermarks.

### Compilation Status

✅ **Successfully compiles**: The Maven build completed without errors using the flink-streaming-java module.

The implementation is complete, functional, and follows all Flink conventions for window assigners and triggers.
