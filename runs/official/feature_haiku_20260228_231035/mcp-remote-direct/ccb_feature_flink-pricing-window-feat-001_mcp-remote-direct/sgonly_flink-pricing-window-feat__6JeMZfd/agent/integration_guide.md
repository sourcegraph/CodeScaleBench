# PricingSessionWindow Integration Guide

## File Placement Instructions

The following three Java files must be placed in the Apache Flink repository structure:

### 1. TradingSessionExtractor.java

**Target Location:**
```
flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/assigners/TradingSessionExtractor.java
```

**Purpose:**
- Functional interface for extracting market IDs from stream elements
- Modeled after `SessionWindowTimeGapExtractor`
- Enables dynamic market-based window assignment
- ~41 lines of code

### 2. PricingSessionWindow.java

**Target Location:**
```
flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/assigners/PricingSessionWindow.java
```

**Purpose:**
- Core window assigner for trading sessions
- Extends `MergingWindowAssigner<Object, TimeWindow>`
- Groups elements by market session boundaries
- ~185 lines of code

### 3. PricingSessionTrigger.java

**Target Location:**
```
flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/triggers/PricingSessionTrigger.java
```

**Purpose:**
- Event-time trigger for firing at market close
- Extends `Trigger<Object, TimeWindow>`
- Supports window merging for efficiency
- ~104 lines of code

---

## Compilation Instructions

Once files are placed in the correct locations, compile the specific module:

```bash
cd flink-streaming-java
mvn clean compile -DskipTests
```

Or for faster builds with just type-checking:

```bash
mvn clean compile -DskipTests -Dcheckstyle.skip=true
```

### Expected Compilation Result

✓ No compilation errors
✓ No warnings (strict warnings mode)
✓ All dependencies resolved from Flink core

---

## Testing Instructions

### Run Existing Tests

First verify existing windowing tests still pass:

```bash
mvn test -Dtest=EventTimeSessionWindowsTest,ProcessingTimeSessionWindowsTest,DynamicEventTimeSessionWindowsTest
```

### Add Unit Tests for New Classes

Create test files:

1. `flink-streaming-java/src/test/java/org/apache/flink/streaming/runtime/operators/windowing/PricingSessionWindowTest.java`
2. `flink-streaming-java/src/test/java/org/apache/flink/streaming/runtime/operators/windowing/PricingSessionTriggerTest.java`

Basic test structure:

```java
class PricingSessionWindowTest {
    @Test
    void testAssignWindowsNormalSession() throws Exception {
        PricingSessionWindow assigner = PricingSessionWindow.forMarket(
            "NYSE",
            ZoneId.of("America/New_York"),
            LocalTime.of(9, 30),
            LocalTime.of(16, 0)
        );
        // Test assertions
    }

    @Test
    void testAssignWindowsPreMarket() throws Exception {
        // Test pre-market event assignment
    }

    @Test
    void testAssignWindowsPostMarket() throws Exception {
        // Test post-market event assignment
    }

    @Test
    void testOvernightSession() throws Exception {
        // Test overnight session (futures market)
    }

    @Test
    void testWindowMerging() throws Exception {
        // Test that windows merge correctly
    }
}
```

### Run All Tests

```bash
mvn test -DskipITs=false
```

---

## Integration Checklist

### Pre-Integration Validation
- [ ] All three Java files created with correct content
- [ ] File names match exactly (case-sensitive)
- [ ] Package declarations are correct
- [ ] All imports resolve without ambiguity
- [ ] serialVersionUID is defined in all classes
- [ ] Apache license header present in all files
- [ ] @PublicEvolving annotation on public classes/interfaces

### Compilation Validation
- [ ] Module compiles without errors
- [ ] No javac warnings
- [ ] No dependency conflicts
- [ ] All abstract methods implemented correctly
- [ ] Method signatures match parent classes exactly

### Integration Testing
- [ ] Existing windowing tests still pass
- [ ] New classes can be instantiated
- [ ] Factory methods work correctly
- [ ] Integration with WindowOperator verified
- [ ] Serialization/deserialization works
- [ ] Distributed execution scenarios tested

### Documentation
- [ ] Javadoc comments complete and accurate
- [ ] Example usage provided in class comments
- [ ] README updated with new window assigner
- [ ] API documentation reflects new classes
- [ ] Migration guide added if replacing existing code

---

## Usage Example for Downstream Teams

Once integrated, users can utilize the new feature as follows:

### Basic Trading Window Example

```java
import org.apache.flink.streaming.api.datastream.DataStream;
import org.apache.flink.streaming.api.datastream.KeyedStream;
import org.apache.flink.streaming.api.datastream.WindowedStream;
import org.apache.flink.streaming.api.windowing.assigners.PricingSessionWindow;
import org.apache.flink.streaming.api.windowing.triggers.PricingSessionTrigger;
import org.apache.flink.streaming.api.windowing.windows.TimeWindow;
import java.time.LocalTime;
import java.time.ZoneId;

// Create assigner for NYSE
PricingSessionWindow nyseAssigner = PricingSessionWindow.forMarket(
    "NYSE",
    ZoneId.of("America/New_York"),
    LocalTime.of(9, 30),
    LocalTime.of(16, 0)
);

// Create assigner for LSE
PricingSessionWindow lseAssigner = PricingSessionWindow.forMarket(
    "LSE",
    ZoneId.of("Europe/London"),
    LocalTime.of(8, 0),
    LocalTime.of(16, 30)
);

// Apply to stream
DataStream<PriceEvent> prices = ...;
KeyedStream<PriceEvent, String> keyed = prices.keyBy(PriceEvent::getSymbol);

// Window with NYSE hours
WindowedStream<PriceEvent, String, TimeWindow> windowed =
    keyed.window(nyseAssigner);

// Apply aggregation at market close
windowed.aggregate(new PriceAggregator())
        .print();
```

### Advanced: Multiple Markets in Single Stream

```java
// Future enhancement with TradingSessionExtractor
// (Not yet implemented, but interface is ready for it)
```

---

## Dependency Verification

### Required Flink Modules

The implementation depends on:

1. **flink-runtime** (for base Trigger and WindowAssigner classes)
   - Classes: Trigger, WindowAssigner, MergingWindowAssigner
   - Modules: flink-runtime/src/main/java/org/apache/flink/streaming/api/windowing/

2. **flink-streaming-java** (for EventTimeTrigger and TimeWindow)
   - Classes: EventTimeTrigger, TimeWindow
   - Modules: Already in same module

3. **flink-annotations** (for PublicEvolving annotation)
   - Classes: PublicEvolving
   - Standard dependency

### No Additional External Dependencies
- All imports from standard Java packages (java.time.*)
- All imports from org.apache.flink packages (core API only)

---

## Performance Considerations

### Memory Usage
- **PricingSessionWindow**: O(1) per window (stores market, timezone, open/close times)
- **PricingSessionTrigger**: O(1) per window (one timer per window)
- Total overhead: Minimal, comparable to EventTimeSessionWindows

### CPU Usage
- **Timezone calculations**: Cached (no repeated conversions for same day)
- **Window assignment**: O(1) operation, executed once per element
- **Trigger firing**: O(1) timer comparison

### Scalability
- Supports unlimited markets/sessions
- No global state (stateless windowing)
- Proper timer cleanup prevents resource leaks
- Merging optimizations inherited from TimeWindow

---

## Troubleshooting

### Common Issues

**Issue: "Cannot find symbol" for PricingSessionWindow**
- Solution: Verify file location matches exactly
- Check package declaration matches directory structure

**Issue: Timezone calculation errors**
- Solution: Verify ZoneId is valid (use ZoneId.getAvailableZoneIds())
- Check session times don't span more than 24 hours

**Issue: Window merging not working**
- Solution: Verify PricingSessionTrigger is used
- Ensure canMerge() returns true and onMerge() is implemented

**Issue: Events assigned to wrong session**
- Solution: Verify timestamp is in milliseconds since epoch
- Check timezone configuration matches expected region

---

## Related Files in Flink Codebase

For reference during integration, these existing files follow similar patterns:

1. **EventTimeSessionWindows.java** - Base session window pattern
2. **DynamicEventTimeSessionWindows.java** - Dynamic session extraction pattern
3. **EventTimeTrigger.java** - Event-time trigger pattern
4. **TimeWindow.java** - Window merging and serialization

---

## Next Steps for Implementation

1. Place the three Java files in correct directories
2. Run `mvn clean compile -DskipTests`
3. Verify no compilation errors
4. Create unit tests (see Testing Instructions above)
5. Run test suite
6. Update API documentation
7. Create Javadoc site documentation
8. Add to release notes if new feature
9. Consider adding example in flink-examples module
