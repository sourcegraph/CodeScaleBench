```typescript
// PaletteFlow Studio — NodeComponent
// src/renderer/components/canvas/NodeComponent.tsx

/**
 * React renderer for a single Canvas Node.
 *
 * Responsibilities
 * ─────────────────
 * • Resolve and mount the correct “mini-editor” (renderer) for the node’s type
 *   using the plugin registry.
 * • Provide ergonomic drag-n-drop, selection and inline-editing behaviour.
 * • Keep the View (React) in sync with the View-Model (MobX) while remaining
 *   framework-agnostic for the Domain layer.
 * • Emit high-level canvas events so higher-order tools (selection marquee,
 *   history, command palette, etc.) can react in a decoupled way.
 */

import React, {
  CSSProperties,
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import { observer } from 'mobx-react-lite';
import { autorun } from 'mobx';

import { NodeViewModel } from '../../viewModels/NodeViewModel';
import { useCanvasContext } from '../../contexts/CanvasContext';
import { PluginRegistry } from '../../../core/plugin-system/PluginRegistry';
import { CanvasEventBus, CanvasEventType } from '../../services/CanvasEventBus';

import { logger } from '../../services/logger';

// Styling is kept local to prevent CSS bleed-through
import {
  NodeRoot,
  NodeSelectionOverlay,
  InlineEditorContainer,
} from './styles/NodeComponent.styles';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface NodeComponentProps {
  nodeId: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * NodeComponent
 *
 * A robust, production-ready renderer for a single node on the infinite canvas.
 * The component is memoised, MobX-observed, and carefully manages event
 * listeners to avoid memory leaks in large canvases (10K+ nodes).
 */
const NodeComponentInner: React.FC<NodeComponentProps> = ({ nodeId }) => {
  /* ────────────────────────────
   * Context & Dependency Lookup
   * ──────────────────────────── */
  const canvasVM = useCanvasContext();
  const nodeVM = canvasVM.getNodeById(nodeId) as NodeViewModel;

  // Fail fast: node could have been deleted by another view
  if (!nodeVM) {
    logger.warn('NodeComponent mounted for non-existent node:', nodeId);
    return null;
  }

  // Resolve the correct renderer via Plugin Registry
  const Renderer = PluginRegistry.instance().getNodeRenderer(nodeVM.type);

  /* ────────────────────────────
   * Local State & Refs
   * ──────────────────────────── */
  const rootRef = useRef<HTMLDivElement>(null);
  const [isDragging, setDragging] = useState(false);
  const [isEditing, setEditing] = useState(false);
  const dragOrigin = useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  /* ────────────────────────────
   * Computed Styles (cached)
   * ──────────────────────────── */
  const computedStyle: CSSProperties = {
    position: 'absolute',
    left: nodeVM.x,
    top: nodeVM.y,
    width: nodeVM.width,
    height: nodeVM.height,
    transform: `rotate(${nodeVM.rotation}deg)`,
    opacity: nodeVM.isFadingOut ? 0 : 1,
    pointerEvents: isEditing ? 'none' : 'auto',
  };

  /* ────────────────────────────
   * Drag & Drop Handlers
   * ──────────────────────────── */

  const handlePointerDown = useCallback<React.PointerEventHandler<HTMLDivElement>>(
    (e) => {
      if (e.button !== 0) return; // Only main button
      if (isEditing) return;

      setDragging(true);
      dragOrigin.current = { x: e.clientX - nodeVM.x, y: e.clientY - nodeVM.y };
      // Capture pointer to continue receiving events outside the node bounds
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      CanvasEventBus.emit(CanvasEventType.NODE_DRAG_START, nodeVM);
    },
    [isEditing, nodeVM],
  );

  const handlePointerMove = useCallback<React.PointerEventHandler<HTMLDivElement>>(
    (e) => {
      if (!isDragging) return;
      nodeVM.setPosition(e.clientX - dragOrigin.current.x, e.clientY - dragOrigin.current.y);
    },
    [isDragging, nodeVM],
  );

  const handlePointerUp = useCallback<React.PointerEventHandler<HTMLDivElement>>(
    (e) => {
      if (!isDragging) return;
      setDragging(false);
      (e.target as HTMLElement).releasePointerCapture(e.pointerId);
      CanvasEventBus.emit(CanvasEventType.NODE_DRAG_END, nodeVM);
    },
    [isDragging, nodeVM],
  );

  /* ────────────────────────────
   * Selection + Inline Editing
   * ──────────────────────────── */

  const handleDoubleClick = useCallback<React.MouseEventHandler<HTMLDivElement>>(() => {
    if (!nodeVM.supportsInlineEditing) return;
    setEditing(true);
  }, [nodeVM]);

  const handleBlurInlineEditor = useCallback(() => {
    setEditing(false);
  }, []);

  /* ────────────────────────────
   * Lifecycle: autorun binding → keep dom inline-size in sync with nodeVM
   * --------------------------------------------------------------------- */
  useLayoutEffect(() => {
    const disposer = autorun(() => {
      const { width, height } = nodeVM;
      if (rootRef.current) {
        rootRef.current.style.width = `${width}px`;
        rootRef.current.style.height = `${height}px`;
      }
    });

    return () => disposer();
  }, [nodeVM]);

  /* ────────────────────────────
   * Context Menu
   * ──────────────────────────── */
  const handleContextMenu = useCallback<React.MouseEventHandler<HTMLDivElement>>(
    (e) => {
      e.preventDefault();
      CanvasEventBus.emit(CanvasEventType.NODE_CONTEXT_MENU, { node: nodeVM, x: e.clientX, y: e.clientY });
    },
    [nodeVM],
  );

  /* ────────────────────────────
   * Keyboard (delete, duplicate, etc.)
   * Node captures keydown only when it owns focus.
   * ──────────────────────────── */
  const handleKeyDown = useCallback<React.KeyboardEventHandler<HTMLDivElement>>(
    (e) => {
      switch (e.key) {
        case 'Delete':
        case 'Backspace':
          canvasVM.requestDeleteNode(nodeVM.id);
          break;
        case 'D':
          if (e.metaKey || e.ctrlKey) {
            canvasVM.requestDuplicateNode(nodeVM.id);
          }
          break;
        default:
          break;
      }
    },
    [canvasVM, nodeVM.id],
  );

  /* ────────────────────────────
   * Render
   * ──────────────────────────── */
  return (
    <NodeRoot
      ref={rootRef}
      style={computedStyle}
      data-node-id={nodeVM.id}
      data-node-type={nodeVM.type}
      tabIndex={0} // make focusable for keyboard
      className={nodeVM.isSelected ? 'selected' : undefined}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onDoubleClick={handleDoubleClick}
      onContextMenu={handleContextMenu}
      onKeyDown={handleKeyDown}
      role="group"
      aria-label={`Canvas node ${nodeVM.type}`}
    >
      {/* Visual selection overlay (activated by global selection manager) */}
      {nodeVM.isSelected && <NodeSelectionOverlay />}

      {/* Mini-editor renderer provided by plugin system */}
      <Renderer node={nodeVM} isEditing={isEditing} />

      {/* Optional generic inline editor fallback */}
      {isEditing && nodeVM.supportsInlineEditing && (
        <InlineEditorContainer
          onBlur={handleBlurInlineEditor}
          contentEditable
          suppressContentEditableWarning
          autoFocus
          spellCheck
        >
          {nodeVM.rawContent}
        </InlineEditorContainer>
      )}
    </NodeRoot>
  );
};

// Memoise AND Observer to prevent unnecessary re-renders
export const NodeComponent = memo(observer(NodeComponentInner));
```

