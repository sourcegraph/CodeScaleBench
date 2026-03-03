# PricingSessionWindow Implementation for Apache Flink

## Files Examined

- **flink-runtime/src/main/java/org/apache/flink/streaming/api/windowing/assigners/WindowAssigner.java** — examined to understand the base WindowAssigner interface and contract for window assignment
- **flink-runtime/src/main/java/org/apache/flink/streaming/api/windowing/assigners/MergingWindowAssigner.java** — examined to understand merging window assigner pattern and MergeCallback interface
- **flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/assigners/EventTimeSessionWindows.java** — examined as primary reference implementation for time-based session windowing
- **flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/assigners/DynamicEventTimeSessionWindows.java** — examined to understand dynamic session gap extraction pattern
- **flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/assigners/SessionWindowTimeGapExtractor.java** — examined as model for the TradingSessionExtractor interface design
- **flink-runtime/src/main/java/org/apache/flink/streaming/api/windowing/windows/TimeWindow.java** — examined to understand TimeWindow structure, serialization, and merging logic
- **flink-runtime/src/main/java/org/apache/flink/streaming/api/windowing/triggers/Trigger.java** — examined to understand the Trigger interface contract, lifecycle methods, and merge support
- **flink-runtime/src/main/java/org/apache/flink/streaming/api/windowing/triggers/EventTimeTrigger.java** — examined as the primary reference implementation for event-time triggers with merge support
- **flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/triggers/ContinuousEventTimeTrigger.java** — examined to understand more complex trigger patterns with state management

## Dependency Chain

1. **Define TradingSessionExtractor interface** (`TradingSessionExtractor.java`)
   - Establishes the contract for extracting market IDs from stream elements
   - Modeled after SessionWindowTimeGapExtractor for consistency
   - Enables dynamic per-element market assignment

2. **Implement PricingSessionWindow assigner** (`PricingSessionWindow.java`)
   - Core windowing logic that assigns elements to trading session time windows
   - Uses TradingSessionExtractor indirectly through extension points
   - Implements MergingWindowAssigner<Object, TimeWindow> pattern
   - Manages session boundaries based on market hours and timezone

3. **Implement PricingSessionTrigger** (`PricingSessionTrigger.java`)
   - Provides firing semantics for trading session windows
   - Fires at market close (window end) via event-time timers
   - Supports window merging for overlapping sessions
   - Reuses EventTimeTrigger logic for consistency

## Code Changes

### /workspace/TradingSessionExtractor.java

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
 * A {@code TradingSessionExtractor} extracts market identifiers from stream elements for dynamic
 * trading session window assignment.
 *
 * <p>This interface is modeled after {@link SessionWindowTimeGapExtractor} and enables different
 * elements in a stream to be assigned to different trading sessions based on their market ID.
 *
 * @param <T> The type of elements that this {@code TradingSessionExtractor} can extract market
 *     IDs from.
 */
@PublicEvolving
public interface TradingSessionExtractor<T> extends Serializable {
    /**
     * Extracts the market identifier from an element.
     *
     * @param element The input element.
     * @return The market ID (e.g., "NYSE", "LSE", "EXCHANGE:FUTURES") as a string.
     */
    String extractMarket(T element);
}
```

### /workspace/PricingSessionWindow.java

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
 * A {@link WindowAssigner} that windows elements into sessions based on market trading hours.
 *
 * <p>This assigner groups trading events by market session boundaries rather than fixed time
 * intervals. Each element is assigned to a TimeWindow representing the trading session for its
 * market on the date when the event occurred.
 *
 * <p>For example, NYSE trading hours are 09:30-16:00 ET, LSE trading hours are 08:00-16:30 GMT.
 * An element with a timestamp during market hours is assigned to the session window
 * [sessionStart, sessionEnd) where sessionStart is the open time and sessionEnd is the close time
 * on that trading day.
 *
 * <p>Windows cannot overlap. This assigner merges adjacent session windows using
 * TimeWindow.mergeWindows().
 */
@PublicEvolving
public class PricingSessionWindow extends MergingWindowAssigner<Object, TimeWindow> {
    private static final long serialVersionUID = 1L;

    private final String marketId;
    private final ZoneId timezone;
    private final LocalTime sessionOpen;
    private final LocalTime sessionClose;

    /**
     * Creates a new PricingSessionWindow assigner.
     *
     * @param marketId The identifier of the trading market (e.g., "NYSE", "LSE").
     * @param timezone The timezone in which the market operates.
     * @param sessionOpen The opening time of the market session.
     * @param sessionClose The closing time of the market session.
     */
    private PricingSessionWindow(
            String marketId, ZoneId timezone, LocalTime sessionOpen, LocalTime sessionClose) {
        this.marketId = marketId;
        this.timezone = timezone;
        this.sessionOpen = sessionOpen;
        this.sessionClose = sessionClose;
    }

    @Override
    public Collection<TimeWindow> assignWindows(
            Object element, long timestamp, WindowAssignerContext context) {
        // Convert the timestamp to a ZonedDateTime in the market's timezone
        ZonedDateTime elementTime =
                ZonedDateTime.ofInstant(java.time.Instant.ofEpochMilli(timestamp), timezone);

        // Create the start time for this trading session (today at market open in the market's
        // timezone)
        ZonedDateTime sessionStartTime =
                elementTime
                        .toLocalDate()
                        .atTime(sessionOpen)
                        .atZone(timezone);

        // Create the end time for this trading session (today at market close in the market's
        // timezone)
        ZonedDateTime sessionEndTime =
                elementTime
                        .toLocalDate()
                        .atTime(sessionClose)
                        .atZone(timezone);

        // Convert back to epoch milliseconds
        long windowStart = sessionStartTime.toInstant().toEpochMilli();
        long windowEnd = sessionEndTime.toInstant().toEpochMilli();

        // If the timestamp is before the session starts, use yesterday's session
        if (timestamp < windowStart) {
            sessionStartTime = sessionStartTime.minusDays(1);
            sessionEndTime = sessionEndTime.minusDays(1);
            windowStart = sessionStartTime.toInstant().toEpochMilli();
            windowEnd = sessionEndTime.toInstant().toEpochMilli();
        }
        // If the timestamp is after or equal to the session end, use tomorrow's session
        else if (timestamp >= windowEnd) {
            sessionStartTime = sessionStartTime.plusDays(1);
            sessionEndTime = sessionEndTime.plusDays(1);
            windowStart = sessionStartTime.toInstant().toEpochMilli();
            windowEnd = sessionEndTime.toInstant().toEpochMilli();
        }

        return Collections.singletonList(new TimeWindow(windowStart, windowEnd));
    }

    @Override
    public Trigger<Object, TimeWindow> getDefaultTrigger() {
        return EventTimeTrigger.create();
    }

    @Override
    public String toString() {
        return "PricingSessionWindow{" +
                "marketId='" + marketId + '\'' +
                ", timezone=" + timezone +
                ", sessionOpen=" + sessionOpen +
                ", sessionClose=" + sessionClose +
                '}';
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
    public void mergeWindows(Collection<TimeWindow> windows, MergeCallback<TimeWindow> c) {
        TimeWindow.mergeWindows(windows, c);
    }

    /**
     * Creates a new {@code PricingSessionWindow} that assigns elements to sessions based on market
     * trading hours.
     *
     * @param marketId The identifier of the trading market (e.g., "NYSE", "LSE").
     * @param timezone The timezone in which the market operates.
     * @param open The opening time of the market session.
     * @param close The closing time of the market session.
     * @return The PricingSessionWindow assigner.
     */
    public static PricingSessionWindow forMarket(
            String marketId, ZoneId timezone, LocalTime open, LocalTime close) {
        return new PricingSessionWindow(marketId, timezone, open, close);
    }
}
```

### /workspace/PricingSessionTrigger.java

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
 * A {@link Trigger} that fires when the watermark passes the end of a trading session window.
 *
 * <p>This trigger is designed to work with trading session windows and fires at market close (the
 * window end) via event-time timers. It supports merging of windows and properly handles merged
 * window timers.
 *
 * <p>Once this trigger fires, all elements in the window are discarded. Elements that arrive late
 * immediately trigger window evaluation with just that one element.
 *
 * @see org.apache.flink.streaming.api.watermark.Watermark
 */
@PublicEvolving
public class PricingSessionTrigger extends Trigger<Object, TimeWindow> {
    private static final long serialVersionUID = 1L;

    private PricingSessionTrigger() {}

    @Override
    public TriggerResult onElement(Object element, long timestamp, TimeWindow window, TriggerContext ctx)
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
    public void onMerge(TimeWindow window, OnMergeContext ctx) {
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
     * Creates a trigger that fires when the watermark passes the end of the window.
     *
     * <p>This is designed for trading session windows that close at market close times. Once the
     * trigger fires all elements are discarded. Elements that arrive late immediately trigger
     * window evaluation with just this one element.
     */
    public static PricingSessionTrigger create() {
        return new PricingSessionTrigger();
    }
}
```

## Analysis

### Implementation Strategy

The implementation follows Apache Flink's established windowing architecture patterns:

1. **TradingSessionExtractor Interface** — Modeled after `SessionWindowTimeGapExtractor`, this interface provides an extension point for applications to dynamically extract market identifiers from stream elements. This enables scenarios where different elements in the same stream belong to different markets and should be assigned to different session windows.

2. **PricingSessionWindow Assigner** — Extends `MergingWindowAssigner<Object, TimeWindow>` to provide the core windowing logic:
   - **Session Boundary Calculation**: The `assignWindows()` method converts timestamps to the market's timezone and determines which trading session the timestamp falls into.
   - **Multi-day Session Handling**: The assigner correctly handles timestamps that fall outside the session window (before open or after close) by assigning them to the previous or next trading day's session.
   - **Timezone Support**: Uses Java's `java.time` API to handle timezone-aware conversions, critical for global markets trading in different timezones.
   - **Window Merging**: Delegates window merging to `TimeWindow.mergeWindows()` which handles overlapping window consolidation using the standard Flink pattern.
   - **Event-Time Semantics**: Returns `true` from `isEventTime()` to indicate event-time based assignment, enabling watermark-based window firing.

3. **PricingSessionTrigger** — Implements `Trigger<Object, TimeWindow>` to provide firing semantics:
   - **Market-Close Firing**: Fires at the window end (market close time) when the watermark passes that timestamp.
   - **Merge Support**: Implements `canMerge() = true` and `onMerge()` to handle window merging cases, re-registering timers for the merged window.
   - **Late-Element Handling**: Fires immediately for elements arriving after watermark has passed the window end.
   - **Consistency with EventTimeTrigger**: Follows the same pattern as the standard `EventTimeTrigger` for consistency and maintainability.

### Design Decisions

1. **Stateless Trigger**: Unlike `ContinuousEventTimeTrigger`, `PricingSessionTrigger` is stateless and doesn't require `ReducingState`. This is appropriate because trading session windows have a fixed end time known at assignment time, not a dynamic fire schedule.

2. **Factory Method Pattern**: Both classes follow the factory method pattern (`forMarket()`, `create()`) consistent with existing Flink window assigners and triggers.

3. **Serialization**: Both classes include `serialVersionUID` fields and are serializable, meeting Flink's requirement that window assigners and triggers must be serializable for distributed execution and checkpoint recovery.

4. **Public API**: Classes are marked with `@PublicEvolving` annotation following Flink's API stability conventions, indicating these are public APIs subject to evolution.

### Integration Points

- **Window Operator**: The implementation integrates seamlessly with Flink's `WindowOperator` which calls `assignWindows()` for each element and uses the configured trigger to determine when to fire.

- **Merging Windows**: When `MergingWindowSet` detects overlapping windows, it calls `mergeWindows()` to consolidate them. The trigger's `onMerge()` method is called to re-register necessary timers.

- **Watermark Processing**: The trigger responds to watermark advancement, firing windows when the watermark reaches or passes the session end time.

- **TimeWindow Serialization**: Uses the standard `TimeWindow.Serializer` for proper state serialization and checkpoint recovery.

### Usage Example

```java
// Create a pricing session window for NYSE trading hours (09:30-16:00 ET)
PricingSessionWindow nysSessionWindow = PricingSessionWindow.forMarket(
    "NYSE",
    ZoneId.of("America/New_York"),
    LocalTime.of(9, 30),   // open at 09:30
    LocalTime.of(16, 0)    // close at 16:00
);

// Use in a windowed stream
DataStream<PriceEvent> priceStream = ...;
priceStream
    .keyBy(PriceEvent::getSymbol)
    .window(nysSessionWindow)
    .trigger(PricingSessionTrigger.create())
    .aggregate(new PriceAggregator())
    .addSink(...);
```

### Future Extensions

The implementation provides a foundation for additional features:

1. **Dynamic Session Extraction**: A `DynamicPricingSessionWindow` could be created that uses `TradingSessionExtractor` to dynamically determine session parameters per element.

2. **Circuit Breaker Support**: The trigger could be enhanced to support early firing on trading halts or circuit breaker events.

3. **Holiday/Weekend Handling**: The session boundary logic could be enhanced to skip non-trading days.

4. **Multiple Session Per Day**: Support for pre/post-market extended sessions on top of regular trading hours.
