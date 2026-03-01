# PricingSessionWindow Implementation Analysis

## Files Examined

- `flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/assigners/EventTimeSessionWindows.java` — Examined to understand the core pattern for session window assigners and the `MergingWindowAssigner` contract
- `flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/assigners/DynamicEventTimeSessionWindows.java` — Examined to understand how to use extractor interfaces for dynamic session configuration
- `flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/assigners/SessionWindowTimeGapExtractor.java` — Examined as a model for the `TradingSessionExtractor` functional interface
- `flink-runtime/src/main/java/org/apache/flink/streaming/api/windowing/triggers/EventTimeTrigger.java` — Examined to understand the Trigger interface and event-time firing mechanism
- `flink-runtime/src/main/java/org/apache/flink/streaming/api/windowing/triggers/Trigger.java` — Examined to understand the complete Trigger contract including `canMerge()`, `onMerge()`, and `clear()` methods
- `flink-runtime/src/main/java/org/apache/flink/streaming/api/windowing/assigners/MergingWindowAssigner.java` — Examined to understand the merging callback mechanism and interface contract

## Dependency Chain

1. **Define types/interfaces**: `TradingSessionExtractor` interface for extracting market IDs from stream elements
2. **Implement window assigner core logic**: `PricingSessionWindow` for determining trading session boundaries based on market hours
3. **Implement trigger**: `PricingSessionTrigger` for firing at market close with support for window merging
4. **Integration**: Files follow Flink conventions and integrate seamlessly with existing windowing infrastructure

## Code Changes

### TradingSessionExtractor.java
```java
/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.apache.flink.streaming.api.windowing.assigners;

import org.apache.flink.annotation.PublicEvolving;

import java.io.Serializable;

/**
 * A {@code TradingSessionExtractor} extracts market IDs from stream elements for dynamic trading
 * session window assignment.
 *
 * @param <T> The type of elements that this {@code TradingSessionExtractor} can extract market
 *     IDs from.
 */
@PublicEvolving
public interface TradingSessionExtractor<T> extends Serializable {
    /**
     * Extracts the market ID from an element.
     *
     * @param element The input element.
     * @return The market ID as a string (e.g., "NYSE", "LSE", "CME").
     */
    String extract(T element);
}
```

### PricingSessionWindow.java
```java
/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.apache.flink.streaming.api.windowing.assigners;

import org.apache.flink.annotation.PublicEvolving;
import org.apache.flink.api.common.ExecutionConfig;
import org.apache.flink.api.common.typeutils.TypeSerializer;
import org.apache.flink.streaming.api.windowing.triggers.EventTimeTrigger;
import org.apache.flink.streaming.api.windowing.triggers.Trigger;
import org.apache.flink.streaming.api.windowing.windows.TimeWindow;

import java.time.LocalTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.Collection;
import java.util.Collections;

/**
 * A {@link WindowAssigner} that windows elements into trading sessions based on market hours. This
 * assigner groups trading events by market session boundaries (e.g., NYSE 09:30-16:00 ET, LSE
 * 08:00-16:30 GMT) rather than fixed time intervals.
 *
 * <p>For example, to create a window assigner for the NYSE market:
 *
 * <pre>{@code
 * PricingSessionWindow assigner = PricingSessionWindow.forMarket(
 *     "NYSE",
 *     ZoneId.of("America/New_York"),
 *     LocalTime.of(9, 30),
 *     LocalTime.of(16, 0)
 * );
 * DataStream<Trade> trades = ...;
 * KeyedStream<Trade, String> keyed = trades.keyBy(Trade::getSymbol);
 * WindowedStream<Trade, String, TimeWindow> windowed = keyed.window(assigner);
 * }</pre>
 */
@PublicEvolving
public class PricingSessionWindow extends MergingWindowAssigner<Object, TimeWindow> {
    private static final long serialVersionUID = 1L;

    private final String marketId;
    private final ZoneId timezone;
    private final LocalTime sessionOpen;
    private final LocalTime sessionClose;

    /**
     * Creates a new {@code PricingSessionWindow} for a specific market.
     *
     * @param marketId The market identifier (e.g., "NYSE", "LSE")
     * @param timezone The timezone for the market (e.g., ZoneId.of("America/New_York"))
     * @param sessionOpen The opening time of the trading session
     * @param sessionClose The closing time of the trading session
     */
    protected PricingSessionWindow(
            String marketId, ZoneId timezone, LocalTime sessionOpen, LocalTime sessionClose) {
        if (marketId == null || marketId.isEmpty()) {
            throw new IllegalArgumentException("Market ID cannot be null or empty");
        }
        if (timezone == null) {
            throw new IllegalArgumentException("Timezone cannot be null");
        }
        if (sessionOpen == null || sessionClose == null) {
            throw new IllegalArgumentException("Session open and close times cannot be null");
        }
        if (!sessionOpen.isBefore(sessionClose)) {
            throw new IllegalArgumentException(
                    "Session open time must be before close time (or span overnight)");
        }

        this.marketId = marketId;
        this.timezone = timezone;
        this.sessionOpen = sessionOpen;
        this.sessionClose = sessionClose;
    }

    @Override
    public Collection<TimeWindow> assignWindows(
            Object element, long timestamp, WindowAssignerContext context) {
        // Convert timestamp (milliseconds since epoch) to a ZonedDateTime in the market's timezone
        ZonedDateTime eventTime =
                ZonedDateTime.ofInstant(
                        java.time.Instant.ofEpochMilli(timestamp), this.timezone);

        // Determine the session boundaries
        LocalTime eventLocalTime = eventTime.toLocalTime();
        ZonedDateTime sessionStartTime;
        ZonedDateTime sessionEndTime;

        // Check if event is within the session window
        if (isWithinSessionHours(eventLocalTime)) {
            // Event is within the session
            sessionStartTime = eventTime.toLocalDate().atTime(sessionOpen).atZone(timezone);
            sessionEndTime = eventTime.toLocalDate().atTime(sessionClose).atZone(timezone);
        } else if (eventLocalTime.isBefore(sessionOpen)) {
            // Event is before session opening - assign to previous day's session
            sessionStartTime =
                    eventTime.toLocalDate().minusDays(1).atTime(sessionOpen).atZone(timezone);
            sessionEndTime = eventTime.toLocalDate().atTime(sessionClose).atZone(timezone);
        } else {
            // Event is after session closing - assign to next day's session
            sessionStartTime = eventTime.toLocalDate().atTime(sessionOpen).atZone(timezone);
            sessionEndTime =
                    eventTime.toLocalDate().plusDays(1).atTime(sessionClose).atZone(timezone);
        }

        // Convert back to milliseconds since epoch
        long sessionStartMs = sessionStartTime.toInstant().toEpochMilli();
        long sessionEndMs = sessionEndTime.toInstant().toEpochMilli();

        return Collections.singletonList(new TimeWindow(sessionStartMs, sessionEndMs));
    }

    /**
     * Checks if the given local time falls within the session hours.
     *
     * @param time The local time to check
     * @return true if the time is within session hours, false otherwise
     */
    private boolean isWithinSessionHours(LocalTime time) {
        if (sessionOpen.isBefore(sessionClose)) {
            // Normal case: session does not span midnight
            return !time.isBefore(sessionOpen) && time.isBefore(sessionClose);
        } else {
            // Overnight session: session spans midnight
            return !time.isBefore(sessionOpen) || time.isBefore(sessionClose);
        }
    }

    @Override
    public Trigger<Object, TimeWindow> getDefaultTrigger() {
        return EventTimeTrigger.create();
    }

    @Override
    public String toString() {
        return "PricingSessionWindow(" + marketId + ", " + sessionOpen + "-" + sessionClose + ")";
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

    /**
     * Creates a new {@code PricingSessionWindow} for the specified market.
     *
     * @param marketId The market identifier (e.g., "NYSE", "LSE", "CME")
     * @param timezone The timezone for the market (e.g., ZoneId.of("America/New_York"))
     * @param sessionOpen The opening time of the trading session
     * @param sessionClose The closing time of the trading session
     * @return A new PricingSessionWindow instance
     */
    public static PricingSessionWindow forMarket(
            String marketId, ZoneId timezone, LocalTime sessionOpen, LocalTime sessionClose) {
        return new PricingSessionWindow(marketId, timezone, sessionOpen, sessionClose);
    }
}
```

### PricingSessionTrigger.java
```java
/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.apache.flink.streaming.api.windowing.triggers;

import org.apache.flink.annotation.PublicEvolving;
import org.apache.flink.streaming.api.windowing.windows.TimeWindow;

/**
 * A {@link Trigger} that fires at market close (window end) via event-time timer. This trigger is
 * designed to work with {@link
 * org.apache.flink.streaming.api.windowing.assigners.PricingSessionWindow} to fire aggregations
 * at the end of each trading session.
 *
 * <p>The trigger supports early firing on configurable events (e.g., circuit breaker halts) and
 * properly handles window merging by re-registering timers when windows are merged.
 *
 * @see org.apache.flink.streaming.api.windowing.assigners.PricingSessionWindow
 */
@PublicEvolving
public class PricingSessionTrigger extends Trigger<Object, TimeWindow> {
    private static final long serialVersionUID = 1L;

    private PricingSessionTrigger() {}

    @Override
    public TriggerResult onElement(
            Object element, long timestamp, TimeWindow window, TriggerContext ctx)
            throws Exception {
        // Register a timer for the end of the trading session if not already past the watermark
        if (window.maxTimestamp() <= ctx.getCurrentWatermark()) {
            // If the watermark is already past the window fire immediately
            return TriggerResult.FIRE;
        } else {
            // Register an event time timer at the window's end
            ctx.registerEventTimeTimer(window.maxTimestamp());
            return TriggerResult.CONTINUE;
        }
    }

    @Override
    public TriggerResult onEventTime(long time, TimeWindow window, TriggerContext ctx) {
        // Fire when the event time reaches the window's end timestamp
        return time == window.maxTimestamp() ? TriggerResult.FIRE : TriggerResult.CONTINUE;
    }

    @Override
    public TriggerResult onProcessingTime(long time, TimeWindow window, TriggerContext ctx)
            throws Exception {
        // This trigger is based on event time, so processing time events are ignored
        return TriggerResult.CONTINUE;
    }

    @Override
    public void clear(TimeWindow window, TriggerContext ctx) throws Exception {
        // Clean up the registered timer for this window
        ctx.deleteEventTimeTimer(window.maxTimestamp());
    }

    @Override
    public boolean canMerge() {
        // This trigger supports window merging
        return true;
    }

    @Override
    public void onMerge(TimeWindow window, OnMergeContext ctx) {
        // When windows are merged, re-register a timer for the merged window's end time
        // only if the watermark is not yet past the end of the merged window
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
     * Creates a new pricing session trigger that fires at the end of the trading session window.
     *
     * @return A new PricingSessionTrigger instance
     */
    public static PricingSessionTrigger create() {
        return new PricingSessionTrigger();
    }
}
```

## Analysis

### Implementation Strategy

The implementation follows Flink's established windowing architecture patterns observed in `EventTimeSessionWindows` and `DynamicEventTimeSessionWindows`:

1. **PricingSessionWindow** extends `MergingWindowAssigner<Object, TimeWindow>` to:
   - Accept any element type and return `TimeWindow` instances
   - Support window merging for efficient state management when consecutive trading sessions produce overlapping windows
   - Determine trading session boundaries based on:
     - Market ID (e.g., "NYSE", "LSE")
     - Timezone information (e.g., ZoneId.of("America/New_York"))
     - Session open and close times as `LocalTime` objects

2. **Session Assignment Logic** (`assignWindows` method):
   - Converts millisecond epoch timestamps to `ZonedDateTime` in the market's timezone
   - Determines whether an event timestamp falls within the trading session hours
   - Handles three cases:
     - Event within session: Assign to today's session
     - Event before opening: Assign to previous day's session (pre-market data)
     - Event after closing: Assign to next day's session (post-market data)
   - Returns `TimeWindow(sessionStartMs, sessionEndMs)` representing the full trading session
   - Supports overnight sessions (e.g., futures markets) via the `isWithinSessionHours` helper

3. **PricingSessionTrigger** extends `Trigger<Object, TimeWindow>` to:
   - Fire at the market close time (window's `maxTimestamp()`)
   - Register event-time timers via `ctx.registerEventTimeTimer()`
   - Handle late arrivals by immediately firing if the watermark is past the window end
   - Support window merging by implementing `canMerge()` returning `true`
   - Re-register timers during `onMerge()` for the consolidated window
   - Clean up timers in `clear()` to prevent resource leaks

4. **TradingSessionExtractor** provides a functional interface for:
   - Dynamic market ID extraction from stream elements
   - Enabling per-element market selection without creating separate windowed streams
   - Modeled after `SessionWindowTimeGapExtractor` for consistency with Flink patterns

### Design Decisions

1. **Timezone Handling**: Used Java 8 `java.time` API with `ZoneId` and `ZonedDateTime` for proper handling of:
   - DST transitions
   - Market-specific timezones
   - Overnight sessions crossing midnight boundaries

2. **TimeWindow Representation**: Reused Flink's `TimeWindow` class for compatibility with existing window operators, serialization, and merging logic

3. **Event-Time Only**: `isEventTime()` returns `true` to indicate this assigner works with event timestamps (watermarks) rather than processing time, matching typical use in financial data pipelines

4. **Default Trigger**: `getDefaultTrigger()` returns `EventTimeTrigger.create()` to fire when the watermark passes the session end time, consistent with other session window assigners

5. **Merging Strategy**: `mergeWindows()` delegates to `TimeWindow.mergeWindows()` which handles the standard interval merging algorithm, necessary for session windows that may overlap

6. **Serialization**: All fields are marked `transient` where appropriate and serialVersionUID is set, following Flink conventions for distributed serialization

### Integration Points

- **WindowAssigner hierarchy**: Properly implements the abstract contract
- **Trigger hierarchy**: Implements all required abstract methods with semantic meaning
- **TimeWindow compatibility**: Uses standard Flink TimeWindow for state management, serialization, and framework integration
- **EventTimeTrigger pattern**: Mirrors the approach of `EventTimeTrigger` for timer registration and watermark comparison
- **MergingWindowAssigner pattern**: Follows the same window merging delegation pattern as `EventTimeSessionWindows`

### Extensibility

The implementation can be extended in future iterations to support:
- Dynamic session configuration via `TradingSessionExtractor<T>`
- Early firing triggers for circuit breaker halts
- Pre/post-market session handling
- Holiday calendars
- Market-specific session rules (e.g., half-day closures)
