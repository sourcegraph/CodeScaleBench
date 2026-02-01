#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
**1. State Management & Source of Truth:**
- The single source of truth is the JSON file on the local file system, managed by `FileSystemWorkspaceRepository.ts` in the main process.
- The main process holds the authoritative state. The renderer process maintains a copy of the state for rendering (e.g., in a state management library like Redux/Zustand, as hinted by `renderer/state/store.ts`). Synchronization happens via explicit IPC calls from the renderer to the main process for mutations, and the main process can push updates back to the renderer, but it's not designed for peer-to-peer updates.
- This model is completely unsuitable for real-time collaboration. It has no central server, no mechanism for broadcasting changes to multiple clients, and relies on a slow, single-writer file system lock.

**2. Data Flow for Mutations:**
- The flow is: `NodeComponent.tsx` (drag event) -> `useViewModel.ts` (or similar hook) -> `renderer/ipc/bridge.ts` (sends IPC message like 'update-node-position') -> `main/IpcMainManager.ts` (receives message) -> `main/ipc/handlers/workspaceHandlers.ts` (handler logic) -> `UpdateNodePosition.ts` (use case) -> `FileSystemWorkspaceRepository.ts` (writes to disk).
- The key limitation is that it's a point-to-point, asynchronous request-response model. It cannot broadcast changes to other connected clients. It's also high-latency due to file I/O and would suffer from race conditions if multiple users tried to write to the same file via a central server without a locking mechanism.

**3. Impact on the Plugin System:**
- The current plugin API (defined by `IPluginService.ts` and documented in `docs/plugin-api/`) likely assumes it has exclusive and immediate access to workspace data. In a collaborative session, a plugin's change could be instantly overwritten by a remote change, or it could trigger a cascade of network events. This would lead to unpredictable behavior and data corruption.
- The API would need significant changes: introducing transactional updates, adding events for remote changes (e.g., `onRemoteNodeUpdated`), and potentially restricting direct mutations in favor of command-based operations that can be serialized and ordered.

**4. Conflict Resolution Strategy:**
- The core entities (`Node.ts`, `Workspace.ts`, `BaseContent.ts`) lack any properties for conflict resolution. They have IDs, but no version vectors, Lamport timestamps, or OT-specific metadata.
- The logic should be implemented in the `core/application/use-cases` layer. This is because the use cases are the orchestrators of business logic, sitting between the external interfaces (like IPC) and the domain entities. Placing it here ensures that any mutation, regardless of its origin (local user, remote user, plugin), passes through the same conflict resolution and validation logic before being persisted. The domain entities themselves would need to be modified to carry the necessary metadata.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
