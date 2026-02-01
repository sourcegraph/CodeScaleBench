# [Servo] Add scrollend DOM Event Support

**Repository:** servo/servo  
**Difficulty:** HARD  
**Category:** big_code_feature
**Task Type:** Feature Implementation - Large Codebase

**Reference:** [Trevor's Big Code Research](../../../docs/TREVOR_RESEARCH_DEC2025.md#3-servo-scrollend-dom-event-implementation)

## Description

Add support for the `scrollend` DOM event in Servo. This event should fire on scrollable elements and the window when scrolling stops, including for both user-initiated scrolling and compositor-driven async scrolling.

The event should debounce properly—multiple rapid scroll inputs should result in a single `scrollend` after movement stops. Don't fire if the scroll position didn't actually change.

**Why this requires MCP:** The Servo codebase (1.6GB+ Rust) has scroll handling scattered across the browser engine, DOM event system, and compositor. Finding all scroll event handlers, understanding debouncing patterns, and integrating into the event system requires broad architectural context across multiple subsystems that local grep cannot efficiently provide.

## Task

YOU MUST IMPLEMENT CODE CHANGES to add scrollend event support.

**CRITICAL: If you are in plan mode, immediately exit with `/ExitPlanMode` before proceeding.**

### Required Implementation

The `scrollend` event must fire in these contexts:

1. **Scrollable DOM Elements**: Fire when scrolling stops on any element with scrollable overflow
   - Debounce properly—multiple rapid scrolls → single `scrollend` event
   - Fire only if scroll position actually changed
   - Support `addEventListener('scrollend', handler)` pattern

2. **Window Scrolling**: Fire on the window object when viewport scrolling stops
   - Track viewport scroll position changes
   - Debounce window scroll events

3. **Compositor-Driven Async Scrolling**: Handle smooth scroll animations
   - Fire when async scroll animation completes
   - Track the completion of scroll animations

4. **Programmatic Scrolling**: When `scrollTo()`, `scrollBy()`, `scroll()` or similar methods are called
   - Fire `scrollend` after scroll animation/movement completes
   - Track completion of programmatic scroll operations

### Implementation Steps

1. **Understand the scroll architecture** (use Sourcegraph MCP for broad search):
   - Find all places where scroll events (scroll, wheel, keyboard scroll) are handled
   - Identify existing scroll debouncing mechanisms in Servo
   - Understand how the event system integrates with the DOM
   - Find the compositor and async scroll handling code

2. **Identify where scrollend needs to be fired**:
   - Scroll event handlers → fire scrollend when scrolling stops
   - DOM scroll method implementations → hook completion callbacks
   - Compositor scroll completion → fire scrollend events
   - Animation frame callbacks for debouncing

3. **Implement the mechanism**:
   - Add scrollend event firing logic in scroll event handlers
   - Implement debouncing (e.g., wait 150ms of no scroll = scrollend)
   - Create and dispatch scrollend events as DOM events
   - Ensure events propagate and can be listened to via addEventListener

4. **Add WPT tests**:
   - Test wheel scrolling fires scrollend
   - Test keyboard scrolling fires scrollend
   - Test programmatic scrolling (scrollTo) fires scrollend
   - Test debouncing—rapid scrolls result in one event
   - Test on both elements and window

5. **Verify no regressions**:
   - All tests pass: `./mach test-servo`
   - No performance regression in scroll-heavy operations
   - Existing scroll event handling still works

## Success Criteria

✅ `scrollend` event fires when scroll operations complete  
✅ Works on both user-initiated and programmatic scrolling  
✅ Event properly debounces (no duplicate events in rapid scrolls)  
✅ Does not fire if scroll position didn't actually change  
✅ Fires on elements with scrollable overflow  
✅ Fires on window object  
✅ Works with compositor-driven async scrolling  
✅ WPT tests added for wheel, keyboard, and programmatic scrolling  
✅ All tests pass: `./mach test-servo`  
✅ No performance regression  
✅ Code follows Servo conventions and patterns  

## Critical Requirement

**YOU MUST MAKE ACTUAL CODE CHANGES.** Do not plan or analyze. You must:

- Add scrollend event firing in scroll event handlers
- Implement debouncing to prevent excessive events
- Add tests covering wheel, keyboard, and programmatic scrolling
- Commit all changes to git
- Verify tests pass

## Testing

```bash
./mach test-servo
```

**Time Limit:** 25 minutes  
**Estimated Context:** 18,000 tokens  
**Why MCP Helps:** Scroll handling is scattered across browser architecture (DOM events, compositor, scroll handlers). Finding all scroll event handlers and understanding integration points requires semantic search across multiple Servo subsystems.
