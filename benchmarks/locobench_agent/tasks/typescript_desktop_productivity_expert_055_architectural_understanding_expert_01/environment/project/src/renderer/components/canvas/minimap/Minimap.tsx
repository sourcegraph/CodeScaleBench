```tsx
/* PaletteFlow Studio – Minimap component
 *
 * This component renders a live “overview map” of the infinite canvas.
 * It subscribes to the CanvasViewModel to stay in sync with:
 *    – boundingRect$  : the total bounding box of all nodes on the canvas
 *    – viewport$      : the rectangle that is currently visible in the main view
 *
 * Users can click or drag inside the minimap to pan the main canvas.
 * A lightweight polling strategy is used to refresh the preview bitmap so
 * that expensive capture operations are performed sparingly.
 */

import React, {
  CSSProperties,
  PointerEvent,
  ReactElement,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { Observable, Subscription } from 'rxjs';

/* -------------------------------------------------------------------------- */
/*                                   Types                                    */
/* -------------------------------------------------------------------------- */

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface CanvasViewModel {
  /** Emits whenever the bounding box of all nodes changes. */
  readonly boundingRect$: Observable<Rect>;
  /** Emits whenever the viewport (visible area) changes. */
  readonly viewport$: Observable<Rect>;
  /** Captures an off-screen preview image of the whole canvas. */
  capturePreview(): Promise<string | null>; // returns a data-url (png) or null on failure
  /** Pans the canvas so that the viewport is centered on the given coordinates. */
  panTo(centerX: number, centerY: number): void;
}

export interface MinimapProps {
  viewModel: CanvasViewModel;
  width?: number; // px – defaults to 200
  height?: number; // px – defaults to 160
  className?: string;
}

/* -------------------------------------------------------------------------- */
/*                               Helper Hooks                                 */
/* -------------------------------------------------------------------------- */

function useObservableState<T>(source$: Observable<T>, initial: T): T {
  const [state, setState] = useState<T>(initial);

  useEffect(() => {
    const sub: Subscription = source$.subscribe({
      next: setState,
      error: err => console.error('[Minimap] observable error', err),
    });
    return () => sub.unsubscribe();
  }, [source$]);

  return state;
}

/* -------------------------------------------------------------------------- */
/*                                   Logic                                    */
/* -------------------------------------------------------------------------- */

const PREVIEW_REFRESH_INTERVAL_MS = 4_000; // capture preview at most every 4s

export const Minimap = ({
  viewModel,
  width = 200,
  height = 160,
  className = '',
}: MinimapProps): ReactElement => {
  /* ------------------------------ Observables ----------------------------- */
  // NB: Provide defaults until first emission to avoid NaN calculations
  const viewport = useObservableState<Rect>(viewModel.viewport$, {
    x: 0,
    y: 0,
    width: 1,
    height: 1,
  });

  const boundingRect = useObservableState<Rect>(viewModel.boundingRect$, {
    x: -0.5,
    y: -0.5,
    width: 1,
    height: 1,
  });

  /* ------------------------------- Preview -------------------------------- */
  const [previewSrc, setPreviewSrc] = useState<string | null>(null);

  // Only re-capture preview every N seconds (or when boundingRect changes)
  useEffect(() => {
    let cancelled = false;

    async function capture(): Promise<void> {
      try {
        const dataUrl = await viewModel.capturePreview();
        if (!cancelled && dataUrl) setPreviewSrc(dataUrl);
      } catch (err) {
        console.warn('[Minimap] Failed to capture preview', err);
      }
    }

    // immediate capture on mount / boundingRect change
    capture();

    const timer = setInterval(capture, PREVIEW_REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [viewModel, boundingRect]);

  /* ----------------------- Coordinate Transformation ---------------------- */
  // Scale factor that fits the entire boundingRect inside the minimap
  const scale = Math.min(
    width / Math.max(boundingRect.width, 1),
    height / Math.max(boundingRect.height, 1),
  );

  // Canvas origin offset once scaled
  const offsetX = (width - boundingRect.width * scale) / 2 - boundingRect.x * scale;
  const offsetY = (height - boundingRect.height * scale) / 2 - boundingRect.y * scale;

  // Viewport rectangle rendered inside minimap
  const viewportStyle: CSSProperties = {
    position: 'absolute',
    left: viewport.x * scale + offsetX,
    top: viewport.y * scale + offsetY,
    width: viewport.width * scale,
    height: viewport.height * scale,
    boxSizing: 'border-box',
    border: '2px solid var(--color-primary-500, #3B82F6)',
    background: 'rgba(59, 130, 246, 0.15)',
    borderRadius: 2,
    pointerEvents: 'none',
  };

  /* ------------------------------- Panning -------------------------------- */
  // When user clicks / drags inside minimap, pan main canvas to that point.
  const draggingRef = useRef<boolean>(false);

  const panToEvent = useCallback(
    (ev: PointerEvent) => {
      const rect = (ev.currentTarget as HTMLElement).getBoundingClientRect();
      const relX = ev.clientX - rect.left;
      const relY = ev.clientY - rect.top;

      // Map back to canvas coordinates
      const canvasX = (relX - offsetX) / scale;
      const canvasY = (relY - offsetY) / scale;

      viewModel.panTo(canvasX, canvasY);
    },
    [offsetX, offsetY, scale, viewModel],
  );

  const handlePointerDown = useCallback(
    (ev: PointerEvent) => {
      draggingRef.current = true;
      panToEvent(ev);
      // capture pointer for dragging across iframe boundaries
      (ev.currentTarget as HTMLElement).setPointerCapture(ev.pointerId);
    },
    [panToEvent],
  );

  const handlePointerMove = useCallback(
    (ev: PointerEvent) => {
      if (draggingRef.current) panToEvent(ev);
    },
    [panToEvent],
  );

  const handlePointerUp = useCallback(() => {
    draggingRef.current = false;
  }, []);

  /* -------------------------------- Render -------------------------------- */
  const containerStyle: CSSProperties = {
    position: 'relative',
    width,
    height,
    overflow: 'hidden',
    border: '1px solid var(--color-neutral-300, #e5e7eb)',
    background: '#f9fafb',
    borderRadius: 4,
    userSelect: 'none',
    touchAction: 'none',
  };

  const imgStyle: CSSProperties = {
    position: 'absolute',
    left: offsetX,
    top: offsetY,
    width: boundingRect.width * scale,
    height: boundingRect.height * scale,
    transformOrigin: 'top left',
    filter: 'brightness(0.96)',
    pointerEvents: 'none',
  };

  return (
    <div
      className={className}
      style={containerStyle}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerLeave={handlePointerUp}
      role="button"
      title="Minimap – click or drag to navigate"
    >
      {previewSrc && (
        <img
          src={previewSrc}
          style={imgStyle}
          alt="Canvas overview"
          draggable={false}
        />
      )}

      {/* Current viewport rectangle */}
      <div style={viewportStyle} />
    </div>
  );
};

export default Minimap;
```
