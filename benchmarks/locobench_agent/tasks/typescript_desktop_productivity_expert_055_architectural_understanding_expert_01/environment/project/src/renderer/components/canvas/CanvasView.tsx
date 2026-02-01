```tsx
/**************************************************************************************************
 * File: CanvasView.tsx
 * Description: High-performance, interactive canvas surface that renders Canvas nodes/links,                              
 *              handles pan/zoom/selection, and delegates node rendering to plugin renderers.       
 *                                                                                                 
 * NOTE: This file lives in the renderer layer; it purposefully depends on React/electron-specific 
 *       details but treats domain entities as opaque records coming from the presentation layer.  
 **************************************************************************************************/

import React, {
  memo,
  useCallback,
  useEffect,
  useRef,
  useState,
  WheelEvent,
  PointerEvent,
} from 'react';
import styled from 'styled-components';

/* ───────────────────────────────────────────── Types ─────────────────────────────────────────── */

import type { CanvasViewModel, NodeVM, LinkVM } from '../../viewmodels/CanvasViewModel';
import { useCanvasViewModel } from '../../viewmodels/useCanvasViewModel';
import { PluginRendererRegistry } from '../../plugins/PluginRendererRegistry';
import { assertUnreachable } from '../../utils/assertUnreachable';

/* ─────────────────────────────────────────── Constants ───────────────────────────────────────── */

const MIN_ZOOM = 0.25;
const MAX_ZOOM = 4;

/* ───────────────────────────────────────────── Utils ─────────────────────────────────────────── */

/**
 * Compute a new zoom level, clamped to a sensible range, given wheel delta.
 */
function computeNextZoom(currentZoom: number, wheelDeltaY: number): number {
  // A factor of ‑0.001 gives a good “zoom speed” feel.
  const nextZoom = currentZoom * (1 - wheelDeltaY * 0.001);
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, nextZoom));
}

/* ────────────────────────────────────────── Styled Nodes ─────────────────────────────────────── */

const CanvasSurface = styled.div`
  position: relative;
  flex: 1 1 auto;
  overflow: hidden;
  background-color: var(--pf-surface-canvas);
  /* Use GPU to make transforms silky-smooth */
  transform: translateZ(0);
  cursor: grab;
  &.panning {
    cursor: grabbing;
  }
`;

const SvgOverlay = styled.svg`
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none; /* Everything interactive occurs on DOM nodes, not the SVG */
`;

/* ─────────────────────────────────────────── Component ───────────────────────────────────────── */

export interface CanvasViewProps {
  /** The logical canvas ID we want to render */
  canvasId: string;
  /** Optional flag that disables user interaction (used for export previews) */
  readonly?: boolean;
}

/**
 * CanvasView
 * ----------
 * Renders the interactive, infinite canvas surface and orchestrates events like pan/zoom,
 * node dragging, selection, and link creation. All node rendering is delegated to plugins
 * registered through the PluginRendererRegistry.
 */
export const CanvasView: React.FC<CanvasViewProps> = memo(({ canvasId, readonly }) => {
  /************************** View-model binding **************************/

  // The view-model abstracts away domain specifics and exposes an immutable snapshot.
  const vm: CanvasViewModel = useCanvasViewModel(canvasId);

  /**************************** Pan / Zoom *******************************/

  // Current 2D translation (in screen pixels) and scale factor.
  const [translation, setTranslation] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);

  const isPanningRef = useRef(false);
  const panOriginRef = useRef<{ x: number; y: number } | null>(null);

  const canvasRef = useRef<HTMLDivElement | null>(null);

  const handleWheel = useCallback(
    (evt: WheelEvent<HTMLDivElement>) => {
      if (readonly) {
        return;
      }
      evt.preventDefault();
      const nextZoom = computeNextZoom(zoom, evt.deltaY);

      // Zoom to cursor position — translate so that the point under the cursor stays still.
      const rect = (evt.currentTarget as HTMLDivElement).getBoundingClientRect();
      const cursorX = evt.clientX - rect.left;
      const cursorY = evt.clientY - rect.top;

      const scaleDelta = nextZoom / zoom;

      setTranslation((prev) => ({
        x: cursorX - scaleDelta * (cursorX - prev.x),
        y: cursorY - scaleDelta * (cursorY - prev.y),
      }));
      setZoom(nextZoom);
    },
    [zoom, readonly]
  );

  const handlePointerDown = useCallback(
    (evt: PointerEvent<HTMLDivElement>) => {
      if (readonly) return;
      if (evt.button !== 0 /* primary button */) return;

      // Start panning. For simplicity we treat every primary-button drag as a pan unless
      // it targets a node (node drag logic lives inside individual renderers).
      isPanningRef.current = true;
      panOriginRef.current = { x: evt.clientX, y: evt.clientY };
      (evt.currentTarget as HTMLElement).setPointerCapture(evt.pointerId);
      (evt.currentTarget as HTMLElement).classList.add('panning');
    },
    [readonly]
  );

  const handlePointerMove = useCallback((evt: PointerEvent<HTMLDivElement>) => {
    if (!isPanningRef.current || !panOriginRef.current) {
      return;
    }
    const dx = evt.clientX - panOriginRef.current.x;
    const dy = evt.clientY - panOriginRef.current.y;

    panOriginRef.current = { x: evt.clientX, y: evt.clientY };

    setTranslation((prev) => ({ x: prev.x + dx, y: prev.y + dy }));
  }, []);

  const handlePointerUp = useCallback((evt: PointerEvent<HTMLDivElement>) => {
    if (!isPanningRef.current) {
      return;
    }
    isPanningRef.current = false;
    panOriginRef.current = null;
    (evt.currentTarget as HTMLElement).releasePointerCapture(evt.pointerId);
    (evt.currentTarget as HTMLElement).classList.remove('panning');
  }, []);

  /**************************** Window resize logic ******************************/

  // Keep an SVG overlay sized to fill the DOM element at all times.
  const [svgSize, setSvgSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        setSvgSize({ width, height });
      }
    });
    resizeObserver.observe(el);
    return () => resizeObserver.disconnect();
  }, []);

  /**************************** Node rendering ****************************/

  /**
   * Renders a single NodeVM by looking up its renderer through the plugin system.
   * If no renderer is found, we fallback to a default “unknown” component.
   */
  const renderNode = useCallback(
    (node: NodeVM) => {
      const Renderer =
        PluginRendererRegistry.get(node.type) ??
        (() => {
          // eslint-disable-next-line react/display-name
          const Unknown = () => (
            <div
              style={{
                padding: 8,
                border: '1px solid var(--pf-border)',
                borderRadius: 4,
                background: 'var(--pf-surface-node)',
                color: 'var(--pf-text-muted)',
              }}
            >
              ⚠ Unknown node type: {node.type}
            </div>
          );
          return Unknown;
        })();

      return (
        <div
          key={node.id}
          style={{
            position: 'absolute',
            left: node.position.x,
            top: node.position.y,
          }}
          data-node-id={node.id}
        >
          <Renderer node={node} readonly={readonly} />
        </div>
      );
    },
    [readonly]
  );

  /**************************** Link rendering ****************************/

  /**
   * Very naive link renderer for now: straight line between node centers.
   * Plugins can register more advanced link types (Bezier curves, arrows, etc.)
   */
  const renderLink = useCallback(
    (link: LinkVM) => {
      const from = vm.nodeMap.get(link.from);
      const to = vm.nodeMap.get(link.to);
      if (!from || !to) {
        // Should never happen; keep robust in production.
        console.warn('Link refers to non-existent node(s)', link);
        return null;
      }

      return (
        <line
          key={link.id}
          x1={from.position.x + from.dimensions.width / 2}
          y1={from.position.y + from.dimensions.height / 2}
          x2={to.position.x + to.dimensions.width / 2}
          y2={to.position.y + to.dimensions.height / 2}
          stroke="var(--pf-border-link)"
          strokeWidth={2}
        />
      );
    },
    [vm.nodeMap]
  );

  /**************************** Render ******************************/

  const transformStyle = {
    transform: `translate(${translation.x}px, ${translation.y}px) scale(${zoom})`,
    transformOrigin: '0 0',
  } as const;

  return (
    <CanvasSurface
      ref={canvasRef}
      onWheel={handleWheel}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      role="application"
      aria-label="Canvas workspace"
    >
      {/* Links are rendered in an SVG underlay to avoid z-index headaches */}
      <SvgOverlay
        width={svgSize.width}
        height={svgSize.height}
        style={transformStyle}
      >
        {vm.links.map(renderLink)}
      </SvgOverlay>

      {/* All nodes live in a single translated/zoomed div for a GPU-accelerated transform */}
      <div style={transformStyle}>{vm.nodes.map(renderNode)}</div>
    </CanvasSurface>
  );
});

CanvasView.displayName = 'CanvasView';

/* ───────────────────────────────────── Development Hot-Reload ───────────────────────────────── */

if (import.meta.hot) {
  import.meta.hot.accept();
}

/* ─────────────────────────────────────────- End of file ‑────────────────────────────────────── */
```