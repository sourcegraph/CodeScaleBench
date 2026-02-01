```typescript
/**
 * End-to-end startup smoke-test for PaletteFlow Studio’s Electron shell.
 *
 * This spec boots a real Electron instance in a controlled environment and
 * performs a series of behavioural assertions that represent “go/no-go” gates
 * for every production release:
 *
 * 1. The main window opens within an acceptable time-frame.
 * 2. Core services (auto-updates, crash-reporting, settings, plugin runtime)
 *    are initialised and exposed on the preload context.
 * 3. A sandboxed 3rd-party plugin can be discovered, loaded and evaluated.
 *
 * The test leverages Playwright’s _electron harness which provides typed
 * handles for ElectronApplication / BrowserWindow → Page objects.
 *
 * NOTE: The app is expected to be built beforehand (`pnpm build:electron`)
 *       and the compiled binary referenced via the PLAYWRIGHT_ELECTRON_BINARY
 *       env var. CI pipelines populate this variable automatically; developers
 *       get a sensible default that points to the local dist folder.
 */
import { test, expect } from '@playwright/test';
import { _electron as electron, ElectronApplication, Page } from 'playwright';
import * as path from 'path';
import * as fs from 'fs/promises';
import { fileURLToPath } from 'url';

// ---------- Helpers ---------------------------------------------------------

const E2E_TIMEOUT = 60_000;         // upper bound to launch the app
const WINDOW_LOAD_TIMEOUT = 15_000; // renderer must paint within this window
const FIXTURE_PLUGIN_ID = 'pf.e2e.hello-world';

/**
 * Convenience: wait for a predicate evaluated in the renderer process.
 */
async function waitForRendererCondition<T>(
  page: Page,
  predicate: () => T | Promise<T>,
  description: string,
  timeout: number = 5_000,
  pollInterval: number = 200
): Promise<T> {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const result = await page.evaluate(predicate);
    if (result) return result;
    await new Promise(res => setTimeout(res, pollInterval));
  }
  throw new Error(`Timed out waiting for: ${description}`);
}

/**
 * Creates a temporary hello-world plugin and returns its root directory.
 */
async function createFixturePlugin(tmpDir: string): Promise<string> {
  const pluginDir = path.join(tmpDir, FIXTURE_PLUGIN_ID);
  await fs.mkdir(pluginDir, { recursive: true });

  const manifest = {
    id: FIXTURE_PLUGIN_ID,
    name: 'E2E Hello World',
    version: '1.0.0',
    main: './index.js',
    engines: {
      paletteflow: '^1.0.0'
    }
  };

  const indexJs = `
    module.exports = function activate(api) {
      // Register a trivial "Hello-World" node type for sanity-checking.
      api.registerNodeType({
        id: '${FIXTURE_PLUGIN_ID}.node',
        title: 'Hello World',
        render() { return /* html */\`<div data-test-id="hello-node">Hello!</div>\`; }
      });
    };
  `;

  await Promise.all([
    fs.writeFile(path.join(pluginDir, 'package.json'), JSON.stringify(manifest, null, 2)),
    fs.writeFile(path.join(pluginDir, 'index.js'), indexJs)
  ]);

  return pluginDir;
}

// ---------- Tests -----------------------------------------------------------

test.describe('App startup smoke suite', () => {
  let electronApp: ElectronApplication;
  let mainPage: Page;
  let tmpPluginDir: string;

  test.beforeAll(async ({}, testInfo) => {
    // 1. Compose a throw-away plugin folder under Playwright’s test-scoped temp dir.
    tmpPluginDir = await createFixturePlugin(testInfo.outputDir);

    // 2. Boot the Electron app.
    electronApp = await electron.launch({
      args: ['.'], // root of app, Playwright will spawn via the packaged binary
      cwd: path.resolve(__dirname, '../../..'),
      timeout: E2E_TIMEOUT,
      env: {
        // Hint the app to an isolated plugin path. It should *only* see our test plugin.
        PALETTEFLOW_PLUGIN_PATH: tmpPluginDir,
        // Prevent auto-update network calls hitting production services.
        PALETTEFLOW_UPDATES_DISABLED: 'true',
        // Disable telemetry so CI isn’t polluted.
        PALETTEFLOW_CRASH_REPORTING: 'test',
        // Preserve existing env.
        ...process.env
      }
    });

    // 3. Obtain the renderer handle (first BrowserWindow).
    mainPage = await electronApp.firstWindow();
  });

  test.afterAll(async () => {
    await electronApp?.close();
  });

  /**
   * Core “app boots” expectation.
   */
  test('main window renders the canvas shell', async () => {
    await expect(mainPage).toHaveTitle(/PaletteFlow Studio/i, { timeout: WINDOW_LOAD_TIMEOUT });

    // Canvas shell creates a global flag once mobx-state-tree completed hydration.
    await waitForRendererCondition(
      mainPage,
      () => (window as any).PF_BOOTSTRAP_COMPLETE === true,
      'PF_BOOTSTRAP_COMPLETE flag to be true',
      10_000
    );

    // Dock UI should exist.
    const inspectorSelector = '[data-test-id="dock-inspector"]';
    await expect(mainPage.locator(inspectorSelector)).toBeVisible();
  });

  /**
   * Guard against silent failures in the services that are traditionally
   * “headless” (auto-updates / crash-reporting).
   */
  test('background services initialise correctly', async () => {
    const services = await mainPage.evaluate(() => {
      const g = (window as any).PF_SERVICES;
      if (!g) return null;
      return {
        updater: !!g.autoUpdater,
        crash: !!g.crashReporter,
        settings: !!g.settingsService
      };
    });

    expect(services).not.toBeNull();
    expect(services!.updater).toBe(true);
    expect(services!.crash).toBe(true);
    expect(services!.settings).toBe(true);
  });

  /**
   * Validate that 3rd-party plugin discovery / activation pipeline is alive.
   */
  test('loads and activates fixture plugin', async () => {
    // Ask the renderer for plugin registry entries.
    const pluginRegistered = await waitForRendererCondition(
      mainPage,
      () => {
        const runtime = (window as any).PF_PLUGIN_RUNTIME;
        return runtime?.has('${FIXTURE_PLUGIN_ID}');
      },
      `plugin ${FIXTURE_PLUGIN_ID} to be registered`
    );

    expect(pluginRegistered).toBe(true);

    // Verify that the node-type we registered can be instantiated by dispatching
    // a create-node command through the renderer’s command palette.
    const nodeId = await mainPage.evaluate(async () => {
      const palette = (window as any).PF_COMMAND_PALETTE;
      const node = await palette.execute('nodes.create', {
        type: '${FIXTURE_PLUGIN_ID}.node',
        position: { x: 100, y: 100 }
      });
      return node?.id;
    });

    expect(nodeId).toMatch(/^node_/);

    // Node should render on canvas and expose its test data-id.
    await expect(mainPage.locator('[data-test-id="hello-node"]')).toBeVisible();
  });
});
```