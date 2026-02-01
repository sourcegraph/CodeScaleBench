```typescript
/**
 * PaletteFlow Studio – CrashReportService
 *
 * Collects runtime errors, renderer crashes, and unhandled rejections,
 * enriches them with runtime metadata, and ships them to PaletteFlow’s
 * telemetry back-end.  When the device is offline or the user has opted-out,
 * reports are queued on disk and retried on the next application start-up.
 *
 * This file lives in the Electron main-process and therefore captures both
 * main/renderer failures.  It does NOT depend on any renderer code.
 */

import { app, crashReporter, BrowserWindow, WebContents } from 'electron';
import { v4 as uuidv4 } from 'uuid';
import * as os from 'os';
import * as path from 'path';
import * as fs from 'fs/promises';
import { EventEmitter } from 'events';
import https from 'https';

/* -------------------------------------------------------------------------- */
/*                               Type definitions                             */
/* -------------------------------------------------------------------------- */

interface CrashReportingSettings {
  enabled: boolean;
  endpoint: string; // e.g. "https://telemetry.paletteflow.com/crash"
  /** Maximum size (bytes) for on-disk queue. Older reports are removed. */
  maxQueueSize?: number;
}

interface ISettingsRepository {
  getCrashReportingSettings(): Promise<CrashReportingSettings>;
}

type ErrorLike = Error | { message: string; name?: string; stack?: string };

interface CrashReportPayload {
  /** Unique id for this crash event. */
  id: string;
  /** Session UUID generated on application bootstrap. */
  sessionId: string;
  timestamp: string; // ISO
  appVersion: string;
  platform: NodeJS.Platform;
  arch: string;
  release: string;
  electronVersion: string;
  nodeVersion: string;

  error: {
    message: string;
    name: string;
    stack?: string;
  };

  context: Record<string, unknown>;
  plugins: string[];
  workspacesOpen: number;
  memory: NodeJS.MemoryUsage;
}

/* -------------------------------------------------------------------------- */
/*                             CrashReportService                             */
/* -------------------------------------------------------------------------- */

export class CrashReportService extends EventEmitter {
  private readonly settingsRepo: ISettingsRepository;
  private readonly queueDir: string;
  private settings: CrashReportingSettings | null = null;
  private sessionId: string = uuidv4();
  private disposed = false;
  private flushing = false;

  constructor(opts: { settingsRepo: ISettingsRepository; queueDir?: string }) {
    super();
    this.settingsRepo = opts.settingsRepo;
    this.queueDir =
      opts.queueDir ??
      path.join(app.getPath('userData'), 'crash-reports-queue');
  }

  /* ---------------------------------------------------------------------- */
  /*                                Public API                              */
  /* ---------------------------------------------------------------------- */

  async initialize(): Promise<void> {
    this.settings = await this.settingsRepo.getCrashReportingSettings();

    // Ensure queue directory exists.
    await fs
      .mkdir(this.queueDir, { recursive: true })
      .catch(() => /** ignore */ {});

    if (this.settings.enabled) {
      // Start Electron's native crashReporter (captures minidumps).
      crashReporter.start({
        companyName: 'PaletteFlow',
        productName: 'PaletteFlow Studio',
        submitURL: this.settings.endpoint, // fallback; we also send JSON manually
        uploadToServer: false, // we'll handle uploads ourselves
        compress: true,
      });
    }

    this.registerProcessHooks();
    await this.flushQueue(); // attempt to send queued reports on start
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;

    process.off('uncaughtException', this.handleMainProcessCrash);
    process.off('unhandledRejection', this.handleUnhandledRejection);
    app.off('browser-window-created', this.handleWindowCreated);

    // Remove listeners from existing windows
    for (const bw of BrowserWindow.getAllWindows()) {
      this.detachWindow(bw);
    }
  }

  /* ---------------------------------------------------------------------- */
  /*                              Event Hooks                               */
  /* ---------------------------------------------------------------------- */

  private registerProcessHooks() {
    process.on('uncaughtException', this.handleMainProcessCrash);
    process.on('unhandledRejection', this.handleUnhandledRejection);

    // renderer crash reporting
    app.on('browser-window-created', this.handleWindowCreated);
    for (const bw of BrowserWindow.getAllWindows()) {
      this.attachWindow(bw);
    }
  }

  private readonly handleWindowCreated = (
    _event: Electron.Event,
    window: BrowserWindow,
  ) => {
    this.attachWindow(window);
  };

  private readonly handleMainProcessCrash = (error: ErrorLike) => {
    // We do NOT rethrow; Electron will decide whether to exit.
    void this.captureError(error, { scope: 'main' });
  };

  private readonly handleUnhandledRejection = (
    reason: unknown,
    _promise: Promise<unknown>,
  ) => {
    const error: ErrorLike =
      reason instanceof Error ? reason : { message: String(reason) };
    void this.captureError(error, { scope: 'main', type: 'unhandledRejection' });
  };

  /* ------------------------------ Renderer ------------------------------ */

  private readonly attachWindow = (bw: BrowserWindow) => {
    const wc = bw.webContents;
    wc.on('render-process-gone', (_, details) => {
      const err: ErrorLike = {
        name: 'RendererProcessGone',
        message: `Renderer process gone – reason: ${details.reason}`,
      };
      void this.captureError(err, { scope: 'renderer', details });
    });

    wc.on(
      'preload-error',
      (_event, _preloadPath: string, error: ErrorLike) => {
        void this.captureError(error, { scope: 'preload' });
      },
    );

    bw.on('closed', () => this.detachWindow(bw));
  };

  private readonly detachWindow = (bw: BrowserWindow) => {
    const wc = bw.webContents;
    wc.removeAllListeners('render-process-gone');
    wc.removeAllListeners('preload-error');
  };

  /* ---------------------------------------------------------------------- */
  /*                             Core capturing                             */
  /* ---------------------------------------------------------------------- */

  /**
   * Captures and (attempts to) send a crash report.  If sending fails, the
   * payload is persisted to disk for retry on next boot.
   */
  async captureError(
    errorLike: ErrorLike,
    context: Record<string, unknown> = {},
  ): Promise<void> {
    const settings = this.settings ?? (await this.settingsRepo.getCrashReportingSettings());

    const payload = await this.buildPayload(errorLike, context);
    this.emit('captured', payload);

    if (!settings.enabled) {
      await this.enqueuePayload(payload); // keep for user if they enable later
      return;
    }

    try {
      await this.postPayload(settings.endpoint, payload);
    } catch (err) {
      await this.enqueuePayload(payload);
      console.warn('[CrashReportService] Failed to send crash report: ', err);
    }
  }

  private async buildPayload(
    errorLike: ErrorLike,
    context: Record<string, unknown>,
  ): Promise<CrashReportPayload> {
    const plugins = this.getLoadedPluginIds();
    const workspacesOpen = this.getOpenWorkspaceCount();

    return {
      id: uuidv4(),
      sessionId: this.sessionId,
      timestamp: new Date().toISOString(),
      appVersion: app.getVersion(),
      platform: process.platform,
      arch: process.arch,
      release: os.release(),
      electronVersion: process.versions.electron,
      nodeVersion: process.versions.node,

      error: {
        message: errorLike.message ?? 'Unknown error',
        name: errorLike.name ?? 'Error',
        stack: errorLike.stack,
      },

      context,
      plugins,
      workspacesOpen,
      memory: process.memoryUsage(),
    };
  }

  /* ---------------------------------------------------------------------- */
  /*                               Networking                                */
  /* ---------------------------------------------------------------------- */

  private async postPayload(
    endpoint: string,
    payload: CrashReportPayload,
  ): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const data = JSON.stringify(payload);
      const url = new URL(endpoint);

      const req = https.request(
        {
          hostname: url.hostname,
          port: url.port || 443,
          path: url.pathname,
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Content-Length': Buffer.byteLength(data),
            'User-Agent': `PaletteFlowStudio/${app.getVersion()}`,
          },
          timeout: 10_000,
        },
        (res) => {
          if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) {
            resolve();
          } else {
            reject(
              new Error(
                `Unexpected response ${res.statusCode} when uploading crash report`,
              ),
            );
          }
        },
      );

      req.on('error', reject);
      req.on('timeout', () => {
        req.destroy(new Error('Timeout uploading crash report'));
      });

      req.write(data);
      req.end();
    });
  }

  /* ---------------------------------------------------------------------- */
  /*                            On-disk queueing                             */
  /* ---------------------------------------------------------------------- */

  private async enqueuePayload(payload: CrashReportPayload): Promise<void> {
    try {
      const filePath = path.join(this.queueDir, `${payload.id}.json`);
      await fs.writeFile(filePath, JSON.stringify(payload), 'utf8');
      await this.trimQueue();
    } catch (err) {
      console.error('[CrashReportService] Unable to persist crash report', err);
    }
  }

  /**
   * Attempts to flush the backlog queue.
   */
  private async flushQueue(): Promise<void> {
    if (this.flushing) return;
    this.flushing = true;

    try {
      const files = await fs.readdir(this.queueDir);
      for (const file of files) {
        if (!file.endsWith('.json')) continue;

        const filePath = path.join(this.queueDir, file);
        const raw = await fs.readFile(filePath, 'utf8');
        let payload: CrashReportPayload | null = null;

        try {
          payload = JSON.parse(raw);
        } catch {
          // malformed – delete
          await fs.unlink(filePath);
          continue;
        }

        if (!this.settings?.enabled) continue; // keep file for later

        try {
          await this.postPayload(this.settings.endpoint, payload);
          await fs.unlink(filePath); // remove only on success
        } catch (err) {
          console.warn('[CrashReportService] Retry failed for queued report', err);
          // stop processing further to avoid spamming server if offline
          break;
        }
      }
    } catch (err) {
      console.error('[CrashReportService] Could not flush crash queue', err);
    } finally {
      this.flushing = false;
    }
  }

  /**
   * Keeps queue folder size under the configured maximum.
   */
  private async trimQueue(): Promise<void> {
    const maxBytes = this.settings?.maxQueueSize ?? 5 * 1024 * 1024; // 5MB default
    let files = await fs.readdir(this.queueDir);
    files = files.filter((f) => f.endsWith('.json'));

    // Gather file stats
    const entries = await Promise.all(
      files.map(async (f) => {
        const filePath = path.join(this.queueDir, f);
        const stat = await fs.stat(filePath);
        return { filePath, size: stat.size, birthtime: stat.birthtimeMs };
      }),
    );

    let total = entries.reduce((acc, e) => acc + e.size, 0);
    if (total <= maxBytes) return;

    // Sort oldest first
    entries.sort((a, b) => a.birthtime - b.birthtime);

    for (const entry of entries) {
      await fs.unlink(entry.filePath).catch(() => {});
      total -= entry.size;
      if (total <= maxBytes) break;
    }
  }

  /* ---------------------------------------------------------------------- */
  /*                               Utilities                                */
  /* ---------------------------------------------------------------------- */

  private getLoadedPluginIds(): string[] {
    // In real implementation, query the plugin subsystem.
    // Here we return stub data to remain domain-agnostic.
    try {
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const pluginManager = require('../plugins/PluginManager').instance;
      return pluginManager.getLoadedPlugins().map((p: any) => p.id);
    } catch {
      return [];
    }
  }

  private getOpenWorkspaceCount(): number {
    try {
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const workspaceService = require('./WorkspaceService').instance;
      return workspaceService.getOpenWorkspaces().length;
    } catch {
      return 0;
    }
  }
}

/* -------------------------------------------------------------------------- */
/*                        Bootstrap singleton (main-proc)                     */
/* -------------------------------------------------------------------------- */

// It is typical to bootstrap the service as soon as the app is ready.
// Exporting a singleton makes it convenient for other services/tests.

let instance: CrashReportService | null = null;

export async function initCrashReporting(
  settingsRepo: ISettingsRepository,
): Promise<CrashReportService> {
  if (instance) return instance;
  instance = new CrashReportService({ settingsRepo });
  if (app.isReady()) {
    await instance.initialize();
  } else {
    app.on('ready', () => instance?.initialize());
  }
  return instance;
}
```