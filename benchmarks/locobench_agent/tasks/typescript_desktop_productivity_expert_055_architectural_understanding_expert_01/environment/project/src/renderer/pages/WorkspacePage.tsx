```tsx
/**
 * WorkspacePage
 * --------------
 * The main renderer for a Workspace window.  It bootstraps the WorkspaceViewModel,
 * wires plugin-provided node renderers into React Flow, and handles global UI
 * concerns (error boundaries, command palette provider, toast notifications, etc.)
 *
 * NOTE: The heavy lifting is delegated to the ViewModel and the plugin registry, so
 * this file mostly focuses on composition and UI orchestration.
 */

import React, {
  KeyboardEvent,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
} from 'react';
import { observer } from 'mobx-react-lite';
import { useParams } from 'react-router-dom';
import { toJS } from 'mobx';
import {
  Box,
  Center,
  Spinner,
  useColorModeValue,
  useToast,
} from '@chakra-ui/react';
import { ErrorBoundary } from 'react-error-boundary';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  ReactFlowProvider,
} from 'reactflow';
import 'reactflow/dist/style.css';

import { useWorkspaceViewModel } from '../viewModels/useWorkspaceViewModel';
import { PluginRegistry } from '../../plugins/PluginRegistry';
import { CommandPaletteProvider } from '../../components/CommandPalette/CommandPaletteProvider';
import { useHotkeys } from '../../hooks/useHotkeys';

const FALLBACK_BG_COLOR = '#1e1e1e';

interface RouteParams {
  workspaceId: string;
}

const WorkspacePageComponent: React.FC = observer(() => {
  /* ----------------- Routing / ViewModel ----------------- */
  const { workspaceId } = useParams<RouteParams>();
  const vm = useWorkspaceViewModel(workspaceId);

  /* ---------------------- Plugins ------------------------ */
  // Memoise node/edge renderer maps to avoid re-creating them on every render.
  const nodeTypes = useMemo(
    () => PluginRegistry.instance.getAllNodeRenderers(),
    []
  );
  const edgeTypes = useMemo(
    () => PluginRegistry.instance.getAllEdgeRenderers(),
    []
  );

  /* ------------- Transformation: Domain → View ----------- */
  const nodes = useMemo(() => vm.flowNodes, [vm.flowNodes]);
  const edges = useMemo(() => vm.flowEdges, [vm.flowEdges]);

  /* ---------------- User-level feedback ------------------ */
  const toast = useToast();
  useEffect(() => {
    if (vm.error) {
      toast({
        status: 'error',
        title: 'Workspace Error',
        description: vm.error.message,
        isClosable: true,
      });
    }
  }, [toast, vm.error]);

  /* --------------- Global keyboard shortcuts ------------- */
  useHotkeys(
    'mod+K',
    () => vm.toggleCommandPalette(),
    [vm],
    { preventDefault: true }
  );

  /**
   * React Flow event: Node drag stop → persist position
   */
  const onNodeDragStop = useCallback(
    (_: unknown, node: any) => {
      vm.updateNodePosition(node.id, node.position);
    },
    [vm]
  );

  /**
   * React Flow event: Edge (re)connect → persist link
   */
  const onConnect = useCallback(
    (connection) => {
      vm.connectNodes(connection);
    },
    [vm]
  );

  /* -------------------- Render helpers ------------------- */
  const loadingSpinner = (
    <Center w="100%" h="100%">
      <Spinner size="xl" thickness="4px" speed="0.7s" />
    </Center>
  );

  const errorFallback = ({ error }: { error: Error }) => (
    <Center w="100%" h="100%" bg={FALLBACK_BG_COLOR} color="white">
      <Box textAlign="center">
        <Box fontSize="xl" mb={2}>
          😓 Workspace crashed
        </Box>
        <Box fontSize="sm" opacity={0.7}>
          {error.message}
        </Box>
      </Box>
    </Center>
  );

  if (vm.isInitialising) {
    return loadingSpinner;
  }

  return (
    <CommandPaletteProvider commands={vm.commandPaletteCommands}>
      <ErrorBoundary FallbackComponent={errorFallback}>
        <ReactFlowProvider>
          <Box
            w="100%"
            h="100%"
            bg={useColorModeValue('gray.100', 'gray.800')}
            onKeyDown={(e: KeyboardEvent) => vm.onGlobalKeyDown(e)}
            tabIndex={-1} // container must be focusable to capture key events
          >
            <Suspense fallback={loadingSpinner}>
              <ReactFlow
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                edgeTypes={edgeTypes}
                onNodeDragStop={onNodeDragStop}
                onConnect={onConnect}
                defaultViewport={vm.initialViewport}
                onMoveEnd={(e, viewport) => vm.persistViewport(viewport)}
              >
                <Background gap={16} />
                <MiniMap />
                <Controls />
              </ReactFlow>
            </Suspense>
          </Box>
        </ReactFlowProvider>
      </ErrorBoundary>
    </CommandPaletteProvider>
  );
});

/* -------------------------------------------------------------------------- */
/*                              EXPORT WRAPPER                                */
/* -------------------------------------------------------------------------- */

/**
 * The observer wrapper is required so MobX can re-render the WorkspacePage
 * whenever observable props on the ViewModel change.
 */
export const WorkspacePage = React.memo(WorkspacePageComponent);
```