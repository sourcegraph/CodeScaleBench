```typescript
/**
 * PaletteFlow Studio – VectorSketchEditor
 * ---------------------------------------
 * A React component that provides an in-node vector sketching experience
 * powered by Konva.  The component interacts with a MobX view-model that
 * wraps the underlying domain entity (Node → VectorDocument) so that all
 * persistence and business-rules live outside the UI layer.
 *
 * Key features:
 *   • Infinite, pan-zoomable canvas that auto-sizes to the node’s frame
 *   • Pen/eraser tools, color & width palette
 *   • Undo/redo (Cmd/Ctrl-Z, Shift-Cmd/Ctrl-Z)
 *   • Debounced auto-save via IPC to the main process
 *   • Optimistic error handling & user notifications
 *
 * NOTE: All renderer-level state is kept minimal; we redirect to the
 *       VectorSketchViewModel whenever possible in keeping with MVVM.
 */

import React, {
  FC,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { observer } from 'mobx-react-lite';
import { Stage, Layer, Line } from 'react-konva';
import Konva from 'konva';
import { KonvaEventObject } from 'konva/lib/Node';
import { debounce } from 'lodash';

import { useViewModel } from '../../hooks/useViewModel';
import { VectorSketchViewModel } from '../../../viewmodels/VectorSketchViewModel';
import { NotificationService } from '../../../services/NotificationService';
import { IPCChannels } from '../../../../shared/ipc/IPCChannels';

Konva.pixelRatio = 2; // crisp lines on high-DPI screens

// ────────────────────────────────────────────────────────────────────────────────
// Types
// ────────────────────────────────────────────────────────────────────────────────

export interface VectorSketchEditorProps {
  /** The id of the canvas node being edited */
  nodeId: string;

  /** read-only mode for shared/collab viewing */
  readOnly?: boolean;

  /** optional CSS class */
  className?: string;
}

// ────────────────────────────────────────────────────────────────────────────────
// Component
// ────────────────────────────────────────────────────────────────────────────────

export const VectorSketchEditor: FC<VectorSketchEditorProps> = observer(
  ({ nodeId, readOnly = false, className }) => {
    // View-model encapsulates domain logic
    const vm = useViewModel<VectorSketchViewModel>(
      VectorSketchViewModel,
      nodeId
    );

    // ── Drawing state (renderer local) ─────────────────────────────────────────
    const stageRef = useRef<Konva.Stage | null>(null);
    const [isDrawing, setIsDrawing] = useState(false);
    const [currentStroke, setCurrentStroke] = useState<number[]>([]);

    // Derived — complete stroke list (MobX observable)
    const strokes = vm.strokes;

    // ── Debounced persistence ────────────────────────────────────────────────
    const persistDebounced = useMemo(
      () =>
        debounce(
          (payload: unknown) =>
            window.electron.ipcRenderer.send(
              IPCChannels.VECTOR_DOC_UPDATED,
              payload
            ),
          750
        ),
      []
    );

    // ── Event handlers ───────────────────────────────────────────────────────
    const handlePointerDown = useCallback(
      (evt: KonvaEventObject<PointerEvent>) => {
        if (readOnly) return;

        setIsDrawing(true);
        const point = evt.target.getStage()?.getPointerPosition();
        if (!point) return;
        setCurrentStroke([point.x, point.y]);
      },
      [readOnly]
    );

    const handlePointerMove = useCallback(
      (evt: KonvaEventObject<PointerEvent>) => {
        if (!isDrawing) return;

        const point = evt.target.getStage()?.getPointerPosition();
        if (!point) return;

        setCurrentStroke((prev) => [...prev, point.x, point.y]);
      },
      [isDrawing]
    );

    const commitStroke = useCallback(
      (stroke: number[]) => {
        if (stroke.length < 4) return; // ignore taps
        vm.addStroke({
          points: stroke,
          color: vm.tool.color,
          width: vm.tool.width,
        });

        // IPC for autosave & plugin observers
        persistDebounced({ nodeId, stroke });
      },
      [nodeId, persistDebounced, vm]
    );

    const handlePointerUp = useCallback(() => {
      if (!isDrawing) return;
      setIsDrawing(false);
      commitStroke(currentStroke);
      setCurrentStroke([]);
    }, [commitStroke, currentStroke, isDrawing]);

    // ── Keyboard shortcuts (undo/redo) ───────────────────────────────────────
    const handleKeyDown = useCallback(
      (evt: KeyboardEvent) => {
        const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
        const ctrlOrCmd = isMac ? evt.metaKey : evt.ctrlKey;

        if (ctrlOrCmd && evt.key === 'z') {
          evt.preventDefault();
          if (evt.shiftKey) vm.redo();
          else vm.undo();
        }
      },
      [vm]
    );

    useEffect(() => {
      window.addEventListener('keydown', handleKeyDown);
      return () => window.removeEventListener('keydown', handleKeyDown);
    }, [handleKeyDown]);

    // ── Lifecycle: notify unsaved error state ────────────────────────────────
    useEffect(() => {
      const disposer = vm.onSyncError((err) =>
        NotificationService.error(
          'Failed to sync sketch changes',
          err.message
        )
      );

      return () => disposer();
    }, [vm]);

    // ── Render helpers ───────────────────────────────────────────────────────
    const renderExistingStrokes = () =>
      strokes.map((stroke, idx) => (
        <Line
          key={idx}
          points={stroke.points}
          stroke={stroke.color}
          strokeWidth={stroke.width}
          lineCap="round"
          lineJoin="round"
          tension={0.5}
        />
      ));

    const renderCurrentStroke = () =>
      !readOnly && isDrawing ? (
        <Line
          points={currentStroke}
          stroke={vm.tool.color}
          strokeWidth={vm.tool.width}
          lineCap="round"
          lineJoin="round"
          tension={0.5}
        />
      ) : null;

    // ── Component render ─────────────────────────────────────────────────────
    return (
      <div className={className} style={{ width: '100%', height: '100%' }}>
        <Stage
          ref={stageRef}
          width={vm.dimensions.width}
          height={vm.dimensions.height}
          onContentPointerDown={handlePointerDown}
          onContentPointerMove={handlePointerMove}
          onContentPointerUp={handlePointerUp}
          draggable
          scaleX={vm.zoom}
          scaleY={vm.zoom}
          x={vm.pan.x}
          y={vm.pan.y}
          onWheel={vm.handleWheel}
        >
          <Layer>
            {renderExistingStrokes()}
            {renderCurrentStroke()}
          </Layer>
        </Stage>
      </div>
    );
  }
);

// ────────────────────────────────────────────────────────────────────────────────
// Hot-reload (DEV only) – keeps state while editing code
// ────────────────────────────────────────────────────────────────────────────────
if (import.meta.hot) {
  import.meta.hot.accept();
}
```