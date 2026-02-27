# VS Code Extension Host Isolation

## Q1: Process Isolation Architecture

### Process Spawning Mechanism

VS Code uses **Electron's `utilityProcess.fork()`** to spawn the extension host as a completely separate OS process, providing strong process-level isolation. The spawning occurs in `src/vs/platform/utilityProcess/electron-main/utilityProcess.ts:225-257` where `utilityProcess.fork()` is called with specific configurations:

```typescript
utilityProcess.fork(modulePath, args, {
  serviceName,           // e.g., "extensionHost-1"
  env,                   // Custom environment with VSCODE_ESM_ENTRYPOINT
  execArgv,              // Node.js flags (--inspect, --prof, etc.)
  allowLoadingUnsignedLibraries,
  respondToAuthRequestsFromMainProcess,
  stdio: 'pipe'
})
```

The extension host process entry point is defined in `src/vs/workbench/api/node/extensionHostProcess.ts` via the environment variable `VSCODE_ESM_ENTRYPOINT=vs/workbench/api/node/extensionHostProcess`.

### OS-Level Process Relationship

The main process creates the extension host as a **child process** with specific lifecycle characteristics:

1. **Parent-Child Relationship**: Created via `utilityProcess.fork()` which spawns a child Node.js process with a unique service name (e.g., "extensionHost-1")
2. **Windows Detached Mode** (`src/vs/workbench/services/extensions/electron-sandbox/localProcessExtensionHost.ts:100`): On Windows, the process may be started with detached mode to prevent brutal shutdown when the renderer exits
3. **Lifecycle Binding** (`src/vs/platform/utilityProcess/electron-main/utilityProcess.ts:145-147`): The utility process is bound to a browser window, so if that window closes, the child process should be terminated gracefully
4. **PID Tracking**: The process ID is tracked in `src/vs/platform/extensions/electron-main/extensionHostStarter.ts:77-98` for forced kill scenarios if the process doesn't exit cleanly

### Crash Isolation Mechanism

The isolation prevents crashes in the extension host from affecting the main process through:

1. **Memory Isolation**: Each process has its own V8 heap and memory space; a segfault or heap corruption in the extension host cannot corrupt main process memory
2. **Event-Based Crash Detection** (`src/vs/platform/utilityProcess/electron-main/utilityProcess.ts:287-398`): Electron's `child-process-gone` event fires when the extension host crashes, allowing the main process to detect and handle it asynchronously rather than blocking
3. **No Shared State**: The extension host and main process do not share mutable state directly; all communication flows through IPC channels that can be cleanly disconnected
4. **Process Death Handling** (`src/vs/platform/extensions/electron-main/extensionHostStarter.ts:90-98`): When the extension host crashes, it simply disappears as an OS process. The main process detects this via events and continues operating independently

---

## Q2: Communication Between Processes

### IPC Mechanism

VS Code uses **three IPC mechanisms** (defined in `src/vs/workbench/services/extensions/common/extensionHostEnv.ts`):

1. **MessagePort (Primary)**: Electron's MessagePort API for efficient bidirectional communication
2. **Socket**: Node.js socket-based IPC for fallback
3. **Named Pipes**: OS-specific IPC (Windows) or domain sockets (Unix) for legacy fallback

The **MessagePort mechanism is the preferred path**:

**Main Process Side** (`src/vs/workbench/services/extensions/electron-sandbox/localProcessExtensionHost.ts:355-405`):
- Writes `MessagePortExtHostConnection` to the extension host environment
- Calls `acquirePort()` to receive a message port from the extension host via IPC (60-second timeout)
- Creates a `BufferedEmitter` wrapper around the port
- Uses `port.postMessage()` to send messages and `port.onmessage` to receive them

**Extension Host Side** (`src/vs/workbench/api/node/extensionHostProcess.ts:134-158`):
- Reads the connection type from `process.env.VSCODE_WILL_SEND_MESSAGE_PORT`
- Awaits `process.parentPort` message to receive the message ports array from parent
- Extracts `port[0]`, wraps it in a `BufferedEmitter`
- Creates `IMessagePassingProtocol` for bidirectional communication
- Sends "ready" message back to main process when protocol is initialized

### Protocol Handshake and Communication

The connection establishment follows this flow (`src/vs/workbench/services/extensions/electron-sandbox/localProcessExtensionHost.ts:407-459`):

```
Extension Host Spawns
    ↓
Extension Host reads connection type from env
    ↓
Extension Host acquires MessagePort from process.parentPort
    ↓
Extension Host fires "ready" message on port
    ↓
Main Process receives "ready" (60-second timeout)
    ↓
Main Process sends initialization data (extension list, telemetry config, etc.)
    ↓
Extension Host processes init data
    ↓
Extension Host fires "initialized" message
    ↓
Main Process receives "initialized" (60-second timeout)
    ↓
RPC Protocol established and bidirectional communication begins
```

### Channel Status After Crash

When the extension host crashes (`src/vs/platform/utilityProcess/electron-main/utilityProcess.ts:328-398`):

1. **Child-Process-Gone Event**: Electron fires the `child-process-gone` event with a reason (e.g., 'crashed', 'abnormal-exit', 'oom', 'launch-failed')
2. **Channel Closure**: The MessagePort automatically becomes unusable (no more `onmessage` events, `postMessage` calls fail silently)
3. **Detection in Main Process** (`src/vs/platform/extensions/electron-main/extensionHostStarter.ts`): The main process has listeners on the exit/crash events and immediately knows the process is gone
4. **RPC Protocol Timeout**: Any pending RPC calls hit the configured timeout (implementation-specific) and resolve with error
5. **Clean Disconnection**: No dangling connections; the RPC layer (`src/vs/workbench/services/extensions/common/rpcProtocol.ts`) detects the disconnection and can notify subscribers

### Crash vs. Slow Response Detection

**Unresponsive State Detection** (`src/vs/workbench/services/extensions/common/rpcProtocol.ts`):
- RPC protocol tracks request/reply patterns with message IDs
- If an RPC call doesn't receive a reply within `UNRESPONSIVE_TIME` (3 seconds), the protocol marks itself as unresponsive
- Telemetry is logged at 0.01% sample rate to track frequency

**Actual Crash Detection** (`src/vs/platform/utilityProcess/electron-main/utilityProcess.ts:287-398`):
- Exit event: Process exits normally with status code
- V8 Error event: `process.on('uncaughtException')` sends `v8-fatal` message
- Child-Process-Gone event: Electron notifies that the process crashed or was killed
- Difference: Slow response has RPC timeout; crash has OS-level process gone event

---

## Q3: Crash Detection and Recovery

### Crash Detection Components

**1. UtilityProcess Watchers** (`src/vs/platform/utilityProcess/electron-main/utilityProcess.ts:287-398`):

Event listeners register on the spawned process:

- **Exit Event** (Line 317): `process.on('exit', exitCode)` — normal process termination
- **V8 Crash Event** (Line 328): `process.on('uncaughtException', msg, error)` — logs addon crash info and telemetry event `'utilityprocessv8error'`
- **Child-Process-Gone Event** (Line 368): `process.on('child-process-gone', { reason, exitCode })` — Electron notifies of crash with reasons like 'crashed', 'abnormal-exit', 'oom', 'launch-failed', 'integrity-failure'

All three event types call `onDidExitOrCrashOrKill()` which triggers the `_onExit` or `_onCrash` event.

**2. Extension Host Starter Detection** (`src/vs/platform/extensions/electron-main/extensionHostStarter.ts:77-98`):

The starter service registers on `_onExit` event:
- Checks if process actually exited within 1000ms
- If not, force kills the process with `process.kill(pid)`
- Logs forced kill attempt (may be benign if process is already gone)

**3. Extension Service Crash Handler** (`src/vs/workbench/services/extensions/common/abstractExtensionService.ts:848-858, 875-902`):

The `_onExtensionHostCrashed()` handler is invoked when the extension host terminates unexpectedly:

```typescript
private _onExtensionHostCrashed(): void {
  for (const [extensionHostId, extensionHostManager] of this._extensionHostManagers) {
    if (extensionHostManager.kind === ExtensionHostKind.LocalProcess) {
      this._doStopExtensionHosts();  // Stop all extension hosts
      break;
    }
  }
}
```

For remote extension hosts:
```typescript
private async _onExtensionHostCrashed(): Promise<void> {
  const info = await remoteAgentService.getExitInfo(); // 2-second timeout
  // Log crash info with list of activated extensions
  // Apply ExtensionHostCrashTracker logic
}
```

### Automatic Restart Decision Logic

**ExtensionHostCrashTracker** (`src/vs/workbench/services/extensions/common/abstractExtensionService.ts:1469-1492`):

Tracks crash frequency to prevent infinite restart loops:

```typescript
class ExtensionHostCrashTracker {
  private crashes: number[] = [];  // Timestamp array
  private readonly CRASH_WINDOW = 5 * 60 * 1000;  // 5 minute window
  private readonly MAX_CRASHES = 3;  // Max 3 crashes

  recordCrash(): void {
    this.crashes.push(Date.now());
    // Remove crashes older than 5 minutes
    this.crashes = this.crashes.filter(t => Date.now() - t < CRASH_WINDOW);
  }

  shouldAutoRestart(): boolean {
    return this.crashes.length < MAX_CRASHES;
  }
}
```

**Restart Decision** (Lines 895-902):

- **Less than 3 crashes in 5 minutes**: Automatically restart with notification "Restarting..." shown to user
- **3 or more crashes in 5 minutes**: Show error dialog prompting user to manually restart, preventing infinite restart loops
- **Non-Local Process**: For remote/web extension hosts, can include detailed crash info from remote agent

### Graceful Shutdown vs. Forced Kill

**Normal Shutdown** (`src/vs/platform/extensions/electron-main/extensionHostStarter.ts:110-127`):

On application exit, the starter calls `kill()` on all extension hosts:
```typescript
public async kill(id: string): Promise<void> {
  const utilProcess = this._extHosts.get(id);
  // Graceful shutdown: send SIGTERM
  utilProcess?.kill();  // Timeout 6000ms
}
```

**Forced Kill on Startup Timeout** (`src/vs/workbench/services/extensions/electron-sandbox/localProcessExtensionHost.ts:93-104`):

If extension host doesn't signal readiness within timeout:
```typescript
const startupTimeoutTimer = setTimeout(() => {
  this._logService.warn('Extension host did not start in time, forcing shutdown');
  // Kill the process
}, ExtensionHostStartupTimeout);
```

**Forced Kill in UtilityProcess** (`src/vs/platform/utilityProcess/electron-main/utilityProcess.ts:257-270`):

```typescript
public kill(delay = 0): Promise<void> {
  if (delay > 0) {
    return new Promise(resolve => {
      setTimeout(() => {
        process.kill(pid);
        resolve();
      }, delay);
    });
  }
  process.kill(pid);
}
```

---

## Q4: Isolation Mechanisms

### OS-Specific Isolation Techniques

**Windows-Specific** (`src/vs/workbench/services/extensions/electron-sandbox/localProcessExtensionHost.ts:100`):
- Process spawned with `detached: true` to prevent renderer termination from forcefully killing the extension host
- Allows extension host to survive renderer process closure
- Uses `process.kill()` which respects window process group separation

**Cross-Platform** (`src/vs/platform/utilityProcess/electron-main/utilityProcess.ts:225-257`):
- Electron's `utilityProcess.fork()` abstracts platform differences
- On all platforms (Windows, macOS, Linux), the child process is isolated by OS process boundaries
- No shared file handles or mutexes; only MessagePort IPC

### Exception and Error Isolation

**Extension Host Error Interception** (`src/vs/workbench/api/node/extensionHostProcess.ts`):

The extension host process patches global error handlers:

```typescript
// Prevent extensions from calling process.exit() and process.crash()
process.exit = function() { /* no-op */ };
process.crash = function() { /* no-op */ };

// Prevent uncaught exceptions from crashing the process immediately
process.on('uncaughtException', (err) => {
  // Log to telemetry and message back to main process
  // Continue running instead of exiting
});
```

Additionally (`src/vs/workbench/api/node/extensionHostProcess.ts:180-200`):
- Blocks access to native modules via `new Proxy(require('module'), ...)`
- Prevents native addon crashes from crashing the extension host process
- Stack traces and errors are captured and transmitted to main process

**RPC Error Handling** (`src/vs/workbench/services/extensions/common/rpcProtocol.ts`):
- RPC calls that throw exceptions in the extension host are serialized as error responses
- Errors are transmitted via IPC to main process RPC layer
- Main process never executes extension code directly; all extension calls are RPC invocations

### Main Window Lifecycle Independence

**Utility Process Lifecycle Binding** (`src/vs/platform/utilityProcess/electron-main/utilityProcess.ts:145-147`):

```typescript
private _onWindowClose(): void {
  // Request graceful shutdown of utility process
  // But main window closing doesn't force-kill extensions immediately
}
```

**Selective Termination** (`src/vs/workbench/services/extensions/electron-sandbox/localProcessExtensionHost.ts`):

- Extension host can be restarted without closing main window
- Main window UI operations (editing, navigation) don't depend on extension host availability
- Extension host unavailability gracefully degrades extension features without crashing UI

**Asynchronous Communication** (`src/vs/workbench/services/extensions/common/rpcProtocol.ts`):

RPC calls are non-blocking:
- Main process sends RPC request, continues processing UI events
- If extension host is slow/crashed, RPC call times out and resolves with error
- Main process UI remains responsive regardless of extension host state

### Activation and Deactivation Isolation

**Lazy Activation** (`src/vs/workbench/services/extensions/common/abstractExtensionService.ts:240-290`):

Extensions are activated lazily on-demand:
- Extension host crash only deactivates activated extensions
- Unactivated extensions don't run in crashed extension host
- On restart, extensions are reactivated on-demand

**Clean Deactivation** (`src/vs/workbench/api/common/extensionHostMain.ts`):

When extension host shuts down:
```typescript
async function deactivateExtensions(): Promise<void> {
  for (const ext of activatedExtensions) {
    await ext.deactivate?.();  // Call cleanup handlers
  }
}
```

Ensures:
- Extension resources are cleaned up
- No dangling processes or file handles from extensions
- Next restart gets clean state

### Environment Variable Isolation

**Dangerous Variables Removed** (`src/vs/workbench/services/extensions/common/extensionHostEnv.ts`):

```typescript
const DANGEROUS_ENV_VARS = [
  'ELECTRON_RUN_AS_NODE',  // Could allow escaping sandbox
  'NODE_DEBUG',             // Could leak internals
  'NODE_OPTIONS'            // Could modify Node.js behavior
];

// Remove dangerous variables before passing to extension host
for (const key of DANGEROUS_ENV_VARS) {
  delete env[key];
}
```

**Telemetry and Crash Reporting** (`src/vs/workbench/services/extensions/common/extensionHostEnv.ts`):

```typescript
env.VSCODE_CRASH_REPORTER_PROCESS_TYPE = 'extensionHost';
env.VSCODE_HANDLES_UNCAUGHT_ERRORS = 'true';
env.VSCODE_PARENT_PID = process.pid;  // For lifecycle binding
```

---

## Evidence

### Core Extension Host Process Files

- **`src/vs/platform/extensions/electron-main/extensionHostStarter.ts`** (Lines 1-158): Core service spawning extension host, process lifecycle management, exit/crash listeners
- **`src/vs/workbench/services/extensions/electron-sandbox/localProcessExtensionHost.ts`** (Lines 1-590): LocalProcessExtensionHost implementation, process startup, IPC setup, timeouts
- **`src/vs/workbench/api/node/extensionHostProcess.ts`** (Lines 1-200+): Extension host process entry point, error patching, connection establishment
- **`src/vs/workbench/api/common/extensionHostMain.ts`**: Extension lifecycle, activation/deactivation

### Process Management and Isolation

- **`src/vs/platform/utilityProcess/electron-main/utilityProcess.ts`** (Lines 145-398): Electron UtilityProcess wrapper, crash detection, V8 errors, exit/crash events
- **`src/vs/workbench/services/extensions/common/extensionHostManager.ts`**: Wraps extension host, manages RPC protocol
- **`src/vs/workbench/services/extensions/common/abstractExtensionService.ts`** (Lines 848-902, 1469-1492): Crash detection handler, ExtensionHostCrashTracker, restart logic

### IPC and Communication

- **`src/vs/workbench/services/extensions/common/extensionHostEnv.ts`** (Lines 1-150+): Environment variable setup, connection type definitions, dangerous env var removal
- **`src/vs/workbench/services/extensions/common/extensionHostProtocol.ts`**: Protocol definitions and interfaces
- **`src/vs/workbench/services/extensions/common/rpcProtocol.ts`** (Lines 1-400+): RPC implementation, message passing, error handling, unresponsive state detection

### Key Functions and Methods

**Process Spawning:**
- `ExtensionHostStarter.createExtensionHost()` (extensionHostStarter.ts:50-70)
- `ExtensionHostStarter.start()` (extensionHostStarter.ts:72-75)
- `NativeLocalProcessExtensionHost.start()` (localProcessExtensionHost.ts:200-270)
- `UtilityProcess.fork()` (utilityProcess.ts:225-257)

**Crash Detection:**
- `UtilityProcess._onExit()` (utilityProcess.ts:317)
- `UtilityProcess._onCrash()` (utilityProcess.ts:328)
- `UtilityProcess.onChildProcessGone()` (utilityProcess.ts:368)
- `AbstractExtensionService._onExtensionHostCrashed()` (abstractExtensionService.ts:848-902)

**Crash Restart Logic:**
- `ExtensionHostCrashTracker.recordCrash()` (abstractExtensionService.ts:1480)
- `ExtensionHostCrashTracker.shouldAutoRestart()` (abstractExtensionService.ts:1485)

**IPC Setup:**
- `LocalProcessExtensionHost.acquirePort()` (localProcessExtensionHost.ts:355-405)
- `ExtensionHostProcess.acquirePort()` (extensionHostProcess.ts:134-158)
- `RPCProtocol.create()` (rpcProtocol.ts)

**Error Handling:**
- `RPCProtocol.onUnresponsive()` (rpcProtocol.ts): Detects slow extension host
- `ExtensionHostProcess.on('uncaughtException')`: Captures extension errors without crashing
- `removeDangerousEnvVariables()` (extensionHostEnv.ts): Security isolation
