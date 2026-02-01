```typescript
import { app, BrowserWindow, dialog, ipcMain } from 'electron';
import { autoUpdater, UpdateCheckResult } from 'electron-updater';
import log from 'electron-log';
import debounce from 'lodash.debounce';
import { EventEmitter } from 'events';

/**
 * AutoUpdateService
 * -----------------
 * Centralised wrapper around `electron-updater` that:
 *   • Periodically checks for application updates
 *   • Streams update lifecycle events to all renderer processes via IPC
 *   • Obeys user-defined preferences (auto-download / auto-install on quit)
 *   • Provides hardened error handling & logging
 *
 * The service is designed as a singleton.  Import the instance rather than
 * instantiating your own copy to avoid duplicate event hooks.
 */
export class AutoUpdateService extends EventEmitter {
  /* --------------------------------------------------------------------- *
   * IPC Channels
   * --------------------------------------------------------------------- */
  private static readonly IPC_STATUS_PUSH = 'autoUpdate:status';       // <renderer-only> stream of status events
  private static readonly IPC_CHECK_NOW   = 'autoUpdate:checkNow';     // <renderer> ask main to trigger a check
  private static readonly IPC_INSTALL_NOW = 'autoUpdate:installNow';   // <renderer> ask main to quit & install
  private static readonly IPC_GET_STATE   = 'autoUpdate:getState';     // <renderer> returns current state struct

  /* --------------------------------------------------------------------- *
   * Internal state
   * --------------------------------------------------------------------- */
  private _updateDownloaded = false;
  private _latestVersion?: string;
  private _currentCheck?: Promise<UpdateCheckResult | null>; // ensures only one concurrent check
  private readonly _devMode = !app.isPackaged;

  constructor() {
    super();
    this.configureLogging();
    this.registerIpc();
  }

  /**
   * Must be called after Electron’s “ready” event.
   * Starts background timers & hooks into `autoUpdater`.
   */
  public init(): void {
    this.configureAutoUpdater();

    // Immediate check on first launch
    this.debouncedCheck(/*userInitiated*/ false);

    // Periodic checks every 4h
    const FOUR_HOURS = 1000 * 60 * 60 * 4;
    setInterval(() => this.debouncedCheck(false), FOUR_HOURS);
  }

  /** Public API exposed to renderers via IPC (and tests). */
  public async checkForUpdates(userInitiated = false): Promise<UpdateCheckResult | null> {
    if (this._currentCheck) return this._currentCheck; // de-bounce calls

    this.emitAndBroadcast('checking-for-update');
    this._currentCheck = autoUpdater.checkForUpdates()
      .catch(err => {
        log.error('[AutoUpdate] checkForUpdates failed', err);
        if (userInitiated) this.showErrorDialog(err);
        this.emitAndBroadcast('error', err?.message ?? String(err));
        return null;
      })
      .finally(() => { this._currentCheck = undefined; });

    return this._currentCheck;
  }

  /** Called by renderer (“Install Now”) or automatically on quit, depending on prefs. */
  public quitAndInstall(): void {
    if (!this._updateDownloaded) {
      log.warn('[AutoUpdate] quitAndInstall invoked but no update downloaded');
      return;
    }
    setImmediate(() => autoUpdater.quitAndInstall());
  }

  /* ===================================================================== *
   * Internal helpers
   * ===================================================================== */

  private configureLogging(): void {
    log.transports.file.level = 'info';
    autoUpdater.logger = log; // route electron-updater logs into electron-log
  }

  private configureAutoUpdater(): void {
    if (process.env.PF_CUSTOM_UPDATE_FEED) {
      autoUpdater.setFeedURL({
        provider: 'generic',
        url: process.env.PF_CUSTOM_UPDATE_FEED
      });
      log.info('[AutoUpdate] Using custom feed:', process.env.PF_CUSTOM_UPDATE_FEED);
    }

    autoUpdater.autoDownload = false; // we decide when to download
    autoUpdater.fullChangelog = false;

    /* ---------- native events ---------- */
    autoUpdater.on('checking-for-update', () => this.emitAndBroadcast('checking-for-update'));

    autoUpdater.on('update-available', info => {
      this._latestVersion = info.version;
      this.emitAndBroadcast('update-available', info);
      if (this.shouldAutoDownload()) {
        autoUpdater.downloadUpdate().catch(err => {
          log.error('[AutoUpdate] download failed', err);
          this.emitAndBroadcast('error', err?.message ?? String(err));
        });
      }
    });

    autoUpdater.on('update-not-available', info => {
      this.emitAndBroadcast('update-not-available', info);
    });

    autoUpdater.on('download-progress', progress => {
      this.emitAndBroadcast('download-progress', progress);
    });

    autoUpdater.on('update-downloaded', info => {
      this._updateDownloaded = true;
      this.emitAndBroadcast('update-downloaded', info);

      if (this.shouldAutoInstallOnQuit()) {
        log.info('[AutoUpdate] Will install on quit');
      } else {
        this.promptUpdateReady(info.version);
      }
    });

    autoUpdater.on('error', err => {
      log.error('[AutoUpdate] fatal error', err);
      this.emitAndBroadcast('error', err?.message ?? String(err));
      if (this._devMode) dialog.showErrorBox('Auto Update Error', err?.message ?? String(err));
    });
  }

  private emitAndBroadcast(event: string, payload?: unknown): void {
    this.emit(event, payload);
    BrowserWindow.getAllWindows().forEach(win => {
      if (!win.isDestroyed()) {
        win.webContents.send(AutoUpdateService.IPC_STATUS_PUSH, { event, payload });
      }
    });
  }

  private debouncedCheck = debounce(
    (userInitiated: boolean) => void this.checkForUpdates(userInitiated),
    5_000,
    { leading: true, trailing: false }
  );

  /* --------------------------------------------------------------------- *
   * IPC plumbing
   * --------------------------------------------------------------------- */
  private registerIpc(): void {
    ipcMain.handle(AutoUpdateService.IPC_CHECK_NOW, async () => {
      await this.debouncedCheck(true);
      return { checking: !!this._currentCheck };
    });

    ipcMain.handle(AutoUpdateService.IPC_INSTALL_NOW, () => {
      this.quitAndInstall();
    });

    ipcMain.handle(AutoUpdateService.IPC_GET_STATE, () => ({
      updateDownloaded: this._updateDownloaded,
      latestVersion   : this._latestVersion
    }));
  }

  /* --------------------------------------------------------------------- *
   * UX helpers
   * --------------------------------------------------------------------- */
  private async promptUpdateReady(version: string): Promise<void> {
    const { response } = await dialog.showMessageBox({
      type      : 'info',
      buttons   : ['Restart & Install', 'Later'],
      defaultId : 0,
      cancelId  : 1,
      noLink    : true,
      title     : `PaletteFlow Studio ${version} is ready!`,
      message   : `Version ${version} has been downloaded. Restart now to apply the update.`
    });

    if (response === 0) this.quitAndInstall();
  }

  private showErrorDialog(error: unknown): void {
    dialog.showErrorBox(
      'Update Failed',
      error instanceof Error ? error.message : String(error)
    );
  }

  /* --------------------------------------------------------------------- *
   * Preferences (to be wired into SettingsService later)
   * --------------------------------------------------------------------- */
  private shouldAutoDownload(): boolean {
    // TODO: fetch from SettingsService
    return true;
  }

  private shouldAutoInstallOnQuit(): boolean {
    // TODO: fetch from SettingsService
    return false;
  }
}

/* ========================================================================= *
 * Singleton export
 * ========================================================================= */
export const autoUpdateService = new AutoUpdateService();
```