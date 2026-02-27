# VS Code Extension Host Isolation

## Q1: Process Isolation Architecture

VS Code uses **Electron's `utilityProcess` API** to spawn the extension host as a completely separate operating system process. This is the fundamental mechanism that provides isolation.

**Key Implementation Details:**

1. **Process Creation** (`src/vs/platform/utilityProcess/electron-main/utilityProcess.ts:1-100`):
   - The `WindowUtilityProcess` class wraps Electron's native `utilityProcess.fork()` API
   - Each extension host is spawned as an independent process with its own Node.js runtime
   - The extension host entry point is specified in the configuration and loaded in the spawned process

2. **Process Lifecycle Management** (`src/vs/platform/extensions/electron-main/extensionHostStarter.ts:70-100`):
   - `ExtensionHostStarter.createExtensionHost()` creates a new `WindowUtilityProcess`
   - Each extension host is assigned a unique ID and tracked in a map
   - Exit handlers are registered immediately upon process creation (line 77)

3. **OS-Level Isolation**:
   - At the OS level, the extension host and main window are **parent and child processes**
   - The main window (renderer process) runs in the primary Electron BrowserWindow
   - The extension host runs in a completely separate process with independent memory, file descriptors, and system resources
   - If the extension host process crashes, the OS notifies the main process via exit events
   - There is **no shared memory** between the processes—they cannot directly access each other's memory

4. **Process Relationship**:
   - The extension host process is a **child of the main Electron process**
   - If the extension host crashes, only that child process terminates
   - The parent (main window) continues running because it has its own process lifecycle
   - The crash does not propagate to the parent—it's caught by the parent's event handlers

**Evidence:**
- `src/vs/platform/utilityProcess/electron-main/utilityProcess.ts:6-7`: Uses Electron's `utilityProcess` and `UtilityProcess` classes
- `src/vs/platform/extensions/electron-main/extensionHostStarter.ts:75`: Creates `WindowUtilityProcess` with log, windows, telemetry, and lifecycle services
- `src/vs/workbench/services/extensions/electron-sandbox/localProcessExtensionHost.ts:50-88`: `ExtensionHostProcess` wrapper provides the interface to the spawned process

---

## Q2: Communication Between Processes

VS Code uses **RPC (Remote Procedure Call) Protocol over IPC sockets** for communication between the main window and extension host. This communication mechanism is completely independent of process lifecycle.

**Key Implementation Details:**

1. **Message Passing Protocol** (`src/vs/workbench/services/extensions/common/rpcProtocol.ts:1-150`):
   - The `RPCProtocol` class implements a request-response protocol over `IMessagePassingProtocol`
   - Messages are serialized to JSON with buffer references, sent across the IPC channel
   - Each RPC call includes a message ID and expects an acknowledgment
   - Protocol handles both incoming and outgoing messages

2. **IPC Channel Creation** (`src/vs/base/parts/ipc/common/ipc.js` and `src/vs/base/parts/ipc/node/ipc.net.ts`):
   - Communication happens over **named pipes (Windows) or Unix domain sockets (macOS/Linux)**
   - The `IMessagePassingProtocol` interface abstracts the underlying transport
   - Messages are read/written via `ProtocolReader` and `ProtocolWriter` classes
   - Socket connection is established as part of extension host startup

3. **Connection Lifecycle** (`src/vs/workbench/services/extensions/electron-sandbox/localProcessExtensionHost.ts:42-48`):
   - The extension host receives a message port during initialization
   - The port is used to establish the WebSocket-based communication channel
   - Both processes maintain this connection for RPC messages

4. **Crash Detection via IPC Disconnection** (`src/vs/platform/utilityProcess/electron-main/utilityProcess.ts:316-325`):
   - Exit Event Handler (line 317): `process.on('exit', code => { ... })`
     - Fires when the extension host process exits
     - Calls `this._onExit.fire()` to notify listeners
   - V8 Error Handler (line 328): `process.on('error', (type, location, report) => { ... })`
     - Fires when a V8 crash is detected in the extension host
   - Child Process Gone Handler (line 368): `app.on('child-process-gone', (event, details) => { ... })`
     - Electron notifies when a utility process terminates unexpectedly

5. **What Happens When Connection Breaks**:
   - The RPC protocol tracks pending replies in `_pendingRPCReplies` (`src/vs/workbench/services/extensions/common/rpcProtocol.ts:135`)
   - If the socket closes, the protocol receives an `onClose` event (`src/vs/base/parts/ipc/node/ipc.net.ts:963`)
   - Pending RPC calls timeout after `UNRESPONSIVE_TIME = 3 seconds` (line 121)
   - The extension host manager detects disconnection and fires `onDidExit` event
   - The main window's extension service receives this event and handles recovery

6. **ResponsiveState Tracking** (`src/vs/workbench/services/extensions/common/rpcProtocol.ts:102-105, 121-125`):
   - `ResponsiveState` enum: `Responsive = 0`, `Unresponsive = 1`
   - The protocol tracks unacknowledged message count (`_unacknowledgedCount`)
   - If no acknowledgment within 3 seconds, protocol fires `onDidChangeResponsiveState` event
   - Main window can show "Extension Host Unresponsive" warning to user

**Evidence:**
- `src/vs/workbench/services/extensions/common/rpcProtocol.ts:117-127`: RPCProtocol implements IRPCProtocol with message passing
- `src/vs/platform/utilityProcess/electron-main/utilityProcess.ts:301-325`: Socket and message event listeners
- `src/vs/workbench/services/extensions/electron-sandbox/localProcessExtensionHost.ts:100-200`: Message port initialization

---

## Q3: Crash Detection and Recovery

VS Code has a sophisticated crash detection and recovery system that prevents crashes from affecting the main window.

**Key Implementation Details:**

1. **Crash Detection Mechanisms** (`src/vs/platform/utilityProcess/electron-main/utilityProcess.ts:287-395`):

   a. **Exit Event Handler** (lines 316-325):
   ```
   process.on('exit', code => {
       this._onExit.fire({ pid: this.processPid!, code, signal: 'unknown' });
       this.onDidExitOrCrashOrKill();
   })
   ```
   - Fires when extension host process exits normally or unexpectedly
   - Notifies all listeners of the exit

   b. **V8 Crash Handler** (lines 327-365):
   ```
   process.on('error', (type, location, report) => { ... })
   ```
   - Detects V8 sandbox fatal errors
   - Extracts addon information from crash reports
   - Sends telemetry for diagnostics

   c. **Child Process Gone Handler** (lines 367-390):
   ```
   app.on('child-process-gone', (event, details) => { ... })
   ```
   - Electron notifies when utility process terminates unexpectedly
   - Provides exit code and reason string

2. **Crash Tracking** (`src/vs/workbench/services/extensions/common/abstractExtensionService.ts:1465-1492`):
   - `ExtensionHostCrashTracker` class tracks recent crashes
   - Time Window: `_TIME_LIMIT = 5 minutes` (line 1471)
   - Crash Limit: `_CRASH_LIMIT = 3` crashes (line 1472)
   - `registerCrash()` method records each crash timestamp
   - `shouldAutomaticallyRestart()` returns true if fewer than 3 crashes in 5 minutes

3. **Automatic vs. Manual Restart** (`src/vs/workbench/services/extensions/common/abstractExtensionService.ts:880-898`):
   ```
   if (this._remoteCrashTracker.shouldAutomaticallyRestart()) {
       // Automatic restart - up to 3 crashes allowed
       this._logService.info(`Automatically restarting the remote extension host.`);
       this._notificationService.status(nls.localize('extensionService.autoRestart',
           "The remote extension host terminated unexpectedly. Restarting..."),
           { hideAfter: 5000 });
       this._startExtensionHostsIfNecessary(false, ...);
   } else {
       // Manual restart - 3+ crashes within 5 minutes
       this._notificationService.prompt(Severity.Error,
           nls.localize('extensionService.crash',
           "Remote Extension host terminated unexpectedly 3 times within the last 5 minutes."),
           [{ label: nls.localize('restart', "Restart Remote Extension Host"),
              run: () => { this._startExtensionHostsIfNecessary(...); } }]);
   }
   ```

4. **Crash Logging** (`src/vs/workbench/services/extensions/common/abstractExtensionService.ts:904-918`):
   - Identifies which extensions were activated when crash occurred
   - Logs the extension list for debugging
   - Uses extension status tracking to correlate crashes with extensions

5. **Preventing Infinite Restart Loops** (`src/vs/platform/extensions/electron-main/extensionHostStarter.ts:85-98`):
   ```
   // See https://github.com/microsoft/vscode/issues/194477
   // If process sends exit event but doesn't really exit, kill it forcefully after 1s
   setTimeout(() => {
       try {
           process.kill(pid, 0); // will throw if process doesn't exist
           this._logService.error(`Extension host with pid ${pid} still exists, forcefully killing it...`);
           process.kill(pid);
       } catch (er) {
           // ignore, process is already gone
       }
   }, 1000);
   ```
   - Detects zombie processes (sends exit signal but doesn't actually exit)
   - Force kills after 1 second timeout
   - Prevents hung processes from consuming resources

6. **Lifecycle Management** (`src/vs/platform/extensions/electron-main/extensionHostStarter.ts:34-38`):
   - On app shutdown, waits gracefully for extension host shutdown with 6-second timeout
   - Prevents main app from closing before extension host cleanup is complete

**Evidence:**
- `src/vs/platform/extensions/electron-main/extensionHostStarter.ts:66-68`: `onDynamicExit()` returns exit event
- `src/vs/workbench/services/extensions/common/abstractExtensionService.ts:1483-1491`: `ExtensionHostCrashTracker` implementation
- `src/vs/platform/extensions/electron-main/extensionHostStarter.ts:77-83`: Exit handler registration and cleanup

---

## Q4: Isolation Mechanisms

Multiple architectural features ensure the main window remains independent of the extension host lifecycle and can recover gracefully from extension failures.

**Key Implementation Details:**

1. **No Shared Memory or State**:
   - Extension host and main window are **completely separate processes**
   - Memory is not shared between them
   - All state transfers occur through serialized RPC messages
   - Even if extension host crashes with segmentation fault, it cannot corrupt main window's memory

2. **Exception Isolation** (`src/vs/workbench/services/extensions/common/rpcProtocol.ts`):
   - Exceptions in the extension host are caught within that process
   - They do not propagate to the main window
   - The extension host may crash, but the main window's event loop continues
   - Each RPC call has explicit error handling on both sides

3. **Responsive State Monitoring** (`src/vs/workbench/services/extensions/common/extensionHostManager.ts:254-256`):
   ```
   this._rpcProtocol = new RPCProtocol(protocol, logger);
   this._register(this._rpcProtocol.onDidChangeResponsiveState(
       (responsiveState: ResponsiveState) =>
           this._onDidChangeResponsiveState.fire(responsiveState)));
   ```
   - Main window can detect if extension host is unresponsive
   - Unresponsive state is tracked and reported to UI
   - User is notified about extension host status
   - Main window remains functional while extension host recovers

4. **Graceful Disconnection** (`src/vs/workbench/services/extensions/common/abstractExtensionService.ts:1243-1248`):
   ```
   public override dispose() {
       for (let i = this._extensionHostManagers.length - 1; i >= 0; i--) {
           const manager = this._extensionHostManagers[i];
           manager.extensionHost.disconnect();
           manager.dispose();
       }
   }
   ```
   - Main window can explicitly disconnect from extension host
   - Allows clean shutdown without waiting for unresponsive extension host
   - Prevents app from hanging on exit

5. **OS-Specific Handling**:
   - **Windows**: Uses named pipes for IPC, child process termination is handled by Windows process manager
   - **macOS/Linux**: Uses Unix domain sockets for IPC, process signals are handled by kernel
   - Both platforms ensure child process exit does not block parent process
   - Electron's `child-process-gone` event provides reliable crash notifications on all platforms

6. **Main Window Continues Operating**:
   - If extension host crashes:
     - Main window's event loop is unaffected
     - User can still edit files, open tabs, navigate UI
     - IPC socket is closed, triggering reconnection logic
     - New extension host is spawned (if under crash limit)
   - No locks or shared resources prevent main window from operating
   - UI remains responsive because extension host runs in separate process

7. **Buffer Between Processes** (`src/vs/base/parts/ipc/common/ipc.net.js:956-966`):
   - `BufferedEmitter` queues incoming messages
   - Even if one side is slow or temporarily unresponsive, messages are buffered
   - Allows graceful degradation rather than immediate failure
   - Prevents cascading failures from one process affecting the other

8. **Feature Availability During Extension Host Absence**:
   - Editor functionality (syntax highlighting from cached data, basic editing)
   - File operations (basic file management)
   - Workspace operations
   - Core UI navigation
   - Any features that don't require active extension host

**Evidence:**
- `src/vs/platform/utilityProcess/electron-main/utilityProcess.ts:1-20`: Separate process isolation via Electron API
- `src/vs/workbench/services/extensions/common/rpcProtocol.ts:117-160`: RPC isolation layer
- `src/vs/workbench/services/extensions/common/extensionHostManager.ts:245-300`: Separate RPC protocol instance per extension host
- `src/vs/base/parts/ipc/node/ipc.net.ts:956-1000`: Socket-based IPC isolation

---

## Evidence

### Core Files and Key Classes

**Process Management:**
- `src/vs/platform/utilityProcess/electron-main/utilityProcess.ts:100-110` - `WindowUtilityProcess` class definition
- `src/vs/platform/extensions/electron-main/extensionHostStarter.ts:17-100` - `ExtensionHostStarter` creates and manages extension host processes
- `src/vs/workbench/services/extensions/electron-sandbox/localProcessExtensionHost.ts:50-100` - `ExtensionHostProcess` wrapper

**Communication and RPC:**
- `src/vs/workbench/services/extensions/common/rpcProtocol.ts:117-160` - `RPCProtocol` class implementation
- `src/vs/base/parts/ipc/node/ipc.net.ts` - Socket-based IPC implementation
- `src/vs/workbench/services/extensions/common/extensionHostManager.ts:245-256` - RPC protocol instantiation and responsiveness tracking

**Crash Detection and Recovery:**
- `src/vs/workbench/services/extensions/common/abstractExtensionService.ts:1469-1492` - `ExtensionHostCrashTracker` class
- `src/vs/workbench/services/extensions/common/abstractExtensionService.ts:880-918` - Crash handling and restart logic
- `src/vs/platform/utilityProcess/electron-main/utilityProcess.ts:316-390` - Exit, error, and crash event handlers
- `src/vs/platform/extensions/electron-main/extensionHostStarter.ts:66-100` - Exit event registration and zombie process cleanup

**Native Extension Service:**
- `src/vs/workbench/services/extensions/electron-sandbox/nativeExtensionService.ts:62-150` - Main extension service for native environments

### Interfaces and Contracts

- `src/vs/workbench/services/extensions/common/extensionHostManagers.ts` - `IExtensionHostManager` interface
- `src/vs/workbench/services/extensions/common/extensions.ts:114-130` - `IExtensionHost` interface with `onExit` event
- `src/vs/base/parts/ipc/common/ipc.ts` - `IMessagePassingProtocol` interface
- `src/vs/workbench/services/extensions/common/rpcProtocol.ts:102-125` - `ResponsiveState` and RPC protocol interfaces

