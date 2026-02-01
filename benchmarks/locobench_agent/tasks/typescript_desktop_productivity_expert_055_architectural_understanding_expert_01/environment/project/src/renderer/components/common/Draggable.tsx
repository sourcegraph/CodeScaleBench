```tsx
// PaletteFlow Studio
// File: src/renderer/components/common/Draggable.tsx

import React, {
  CSSProperties,
  FC,
  ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import throttle from 'lodash/throttle';

/**
 * 2-D cartesian coordinate.
 */
export interface Position {
  x: number;
  y: number;
}

/**
 * Shape of the callback object emitted during drag lifecycle events.
 */
export interface DragEventData {
  /**
   * Optional consumer-provided identifier that will be echoed back
   * in every drag event—handy when multiple Draggables are managed
   * in an array.
   */
  id?: string;

  /**
   * Position at drag start (after snapping, axis locking, etc.).
   */
  startPosition: Position;

  /**
   * Last emitted position prior to this event.
   */
  prevPosition: Position;

  /**
   * New position for this event.
   */
  position: Position;

  /**
   * Delta applied since previous event.  `delta = position - prevPosition`
   */
  delta: Position;

  /**
   * The native Pointer / Mouse event for advanced consumers.
   */
  originalEvent: PointerEvent | MouseEvent;
}

/**
 * Props accepted by the Draggable component.
 */
export interface DraggableProps {
  children: ReactNode;

  /**
   * Optional identifier forwarded to drag event payloads.
   */
  id?: string;

  /**
   * Starting coordinate (defaults to {0,0}).
   */
  initialPosition?: Position;

  /**
   * Invoked once, when pointer/touch first begins dragging.
   */
  onDragStart?: (e: DragEventData) => void;

  /**
   * Throttled callback fired as the element moves.
   */
  onDrag?: (e: DragEventData) => void;

  /**
   * Fired at the very end of the interaction.
   */
  onDragEnd?: (e: DragEventData) => void;

  /**
   * Snap increments. e.g. [10,10] only allows multiples of 10px.
   */
  grid?: [number, number];

  /**
   * Constrain movement to one axis, or allow movement on both axes.
   */
  axis?: 'x' | 'y' | 'both';

  /**
   * Prevent dragging entirely.  The element will still render.
   */
  disabled?: boolean;

  /**
   * Constrain movement so the element never leaves its offset parent.
   */
  constrainToParent?: boolean;

  /**
   * Extra style forwarded to the root <div>.
   */
  style?: CSSProperties;

  /**
   * Optional className forwarded to the root <div>.
   */
  className?: string;
}

/**
 * Production-ready, high-performance Draggable wrapper.
 *
 * Handles pointer, mouse, and touch events in a single unified code-path.
 *
 * - Uses CSS `transform: translate(...)` for buttery-smooth 60fps movement.
 * - Throttles onDrag callback to avoid spamming React’s reconciliation loop.
 * - Prevents text selection & unwanted scrolling while dragging.
 * - Cleans up all listeners to avoid memory leaks.
 */
export const Draggable: FC<DraggableProps> = ({
  id,
  children,
  initialPosition = { x: 0, y: 0 },
  onDragStart,
  onDrag,
  onDragEnd,
  grid,
  axis = 'both',
  disabled = false,
  constrainToParent = false,
  style,
  className,
}) => {
  // --- Refs -----------------------------------------------------------------
  const nodeRef = useRef<HTMLDivElement | null>(null);
  const posRef = useRef<Position>(initialPosition); // current position
  const dragStartRef = useRef<{ pointerStart: Position; posStart: Position }>();
  const prevPosRef = useRef<Position>(initialPosition);
  const rafRef = useRef<number>();
  const mountedRef = useRef<boolean>(false);

  // --- State (used only for external rendering) -----------------------------
  const [, forceRender] = useState(0); // we store nothing—just trigger rerenders

  // --- Helpers --------------------------------------------------------------

  /**
   * Snaps the provided position to the user-supplied grid (if any).
   */
  const snapToGrid = useCallback(
    (p: Position): Position => {
      if (!grid) return p;
      const [gx, gy] = grid;
      return {
        x: Math.round(p.x / gx) * gx,
        y: Math.round(p.y / gy) * gy,
      };
    },
    [grid]
  );

  /**
   * Applies axis locking according to prop.
   */
  const applyAxisConstraint = useCallback(
    (p: Position, original: Position): Position => {
      if (axis === 'both') return p;
      if (axis === 'x') return { x: p.x, y: original.y };
      if (axis === 'y') return { x: original.x, y: p.y };
      return p;
    },
    [axis]
  );

  /**
   * When constrainToParent is true, clamp the position so that the node
   * always visually sits inside its offsetParent.
   */
  const applyParentConstraint = useCallback(
    (p: Position): Position => {
      if (!constrainToParent || !nodeRef.current) return p;

      const el = nodeRef.current;
      const parent = el.offsetParent as HTMLElement;
      if (!parent) return p;

      const parentRect = parent.getBoundingClientRect();
      const elRect = el.getBoundingClientRect();

      const minX = 0;
      const minY = 0;
      const maxX = parentRect.width - elRect.width;
      const maxY = parentRect.height - elRect.height;

      return {
        x: Math.min(Math.max(p.x, minX), maxX),
        y: Math.min(Math.max(p.y, minY), maxY),
      };
    },
    [constrainToParent]
  );

  /**
   * Core function applying grid, axis, and parent constraint.
   */
  const normalizePosition = useCallback(
    (p: Position, original: Position) => {
      let out = snapToGrid(p);
      out = applyAxisConstraint(out, original);
      out = applyParentConstraint(out);
      return out;
    },
    [snapToGrid, applyAxisConstraint, applyParentConstraint]
  );

  /**
   * Updates the DOM transform once per animation frame.
   */
  const flushPositionToDom = useCallback(() => {
    if (!nodeRef.current) return;
    const { x, y } = posRef.current;
    (nodeRef.current.style as any).transform = `translate3d(${x}px, ${y}px, 0)`;
  }, []);

  /**
   * Emits the given drag event to consumer callbacks.
   */
  const emitEvent = useCallback(
    (
      type: 'start' | 'drag' | 'end',
      event: PointerEvent | MouseEvent,
      nextPos: Position
    ) => {
      const payload: DragEventData = {
        id,
        startPosition: dragStartRef.current!.posStart,
        prevPosition: prevPosRef.current,
        position: nextPos,
        delta: {
          x: nextPos.x - prevPosRef.current.x,
          y: nextPos.y - prevPosRef.current.y,
        },
        originalEvent: event,
      };

      if (type === 'start') onDragStart?.(payload);
      if (type === 'drag') onDrag?.(payload);
      if (type === 'end') onDragEnd?.(payload);

      prevPosRef.current = nextPos;
    },
    [id, onDragStart, onDrag, onDragEnd]
  );

  // --- Event Handlers -------------------------------------------------------

  /**
   * Handler for pointerdown / mousedown / touchstart
   */
  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (disabled || e.button !== 0) return; // Left mouse only
      // capture pointer so future events come to us even if out of bounds
      nodeRef.current?.setPointerCapture(e.pointerId);

      dragStartRef.current = {
        pointerStart: { x: e.clientX, y: e.clientY },
        posStart: posRef.current,
      };

      prevPosRef.current = posRef.current;

      // Disable default behaviors
      (e.target as HTMLElement).style.userSelect = 'none';

      emitEvent('start', e.nativeEvent, posRef.current);
    },
    [disabled, emitEvent]
  );

  /**
   * During drag, we throttle updates to 60fps (or user’s refresh rate).
   */
  const throttledDrag = useRef(
    throttle((ev: PointerEvent) => {
      if (!dragStartRef.current) return;

      const { pointerStart, posStart } = dragStartRef.current;

      const delta = {
        x: ev.clientX - pointerStart.x,
        y: ev.clientY - pointerStart.y,
      };

      let nextPos = {
        x: posStart.x + delta.x,
        y: posStart.y + delta.y,
      };

      nextPos = normalizePosition(nextPos, posStart);
      posRef.current = nextPos;

      // Defer DOM write to next animation frame for maximum performance.
      cancelAnimationFrame(rafRef.current!);
      rafRef.current = requestAnimationFrame(flushPositionToDom);

      emitEvent('drag', ev, nextPos);
    }, 16) // ~60fps
  ).current;

  /**
   * End the drag operation—clean up listeners, reset state, fire callbacks.
   */
  const handlePointerUp = useCallback(
    (ev: PointerEvent) => {
      if (!dragStartRef.current) return;

      throttledDrag.cancel();
      document.removeEventListener('pointermove', throttledDrag);
      document.removeEventListener('pointerup', handlePointerUp);
      nodeRef.current?.releasePointerCapture(ev.pointerId);

      const finalPos = posRef.current;
      emitEvent('end', ev, finalPos);

      dragStartRef.current = undefined;
      // Force one last rerender (useful if consumer repositions via props)
      forceRender((c) => c + 1);
    },
    [emitEvent, throttledDrag]
  );

  // --- Lifecycle ------------------------------------------------------------
  useEffect(() => {
    mountedRef.current = true;
    // Initial DOM paint
    flushPositionToDom();

    return () => {
      mountedRef.current = false;
      throttledDrag.cancel();
      document.removeEventListener('pointermove', throttledDrag);
      document.removeEventListener('pointerup', handlePointerUp);
      cancelAnimationFrame(rafRef.current!);
    };
  }, [flushPositionToDom, throttledDrag, handlePointerUp]);

  // Update transform when external initialPosition prop changes
  useEffect(() => {
    if (!mountedRef.current) return;
    posRef.current = initialPosition;
    prevPosRef.current = initialPosition;
    flushPositionToDom();
  }, [initialPosition, flushPositionToDom]);

  // Attach global listeners lazily on first pointerdown
  useEffect(() => {
    if (!dragStartRef.current) return;

    document.addEventListener('pointermove', throttledDrag);
    document.addEventListener('pointerup', handlePointerUp);

    return () => {
      document.removeEventListener('pointermove', throttledDrag);
      document.removeEventListener('pointerup', handlePointerUp);
    };
  }, [throttledDrag, handlePointerUp]);

  // --- Render ---------------------------------------------------------------
  return (
    <div
      ref={nodeRef}
      className={className}
      onPointerDown={handlePointerDown}
      style={{
        position: 'absolute',
        touchAction: 'none', // Prevents default scroll/zoom on touch devices.
        transform: `translate3d(${initialPosition.x}px, ${initialPosition.y}px, 0)`,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

export default Draggable;
```