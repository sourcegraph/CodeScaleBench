```typescript
/**
 * End-to-end tests that cover the most common user-flows around
 * node creation, editing, linking and persistence inside
 * PaletteFlow Studio.  These tests run the packaged Electron
 * application in a real OS window by leveraging Playwright’s
 * Electron launcher.
 *
 * To execute:
 *   $ pnpm e2e                                # see package.json
 *
 * Environment variables:
 *   E2E_APP_PATH   Absolute path to the built electron entry file.
 *                  When omitted, `npm start` (dev) is used instead.
 */

import { test, expect } from '@playwright/test';
import type { Page, ElectronApplication } from '@playwright/test';
import { _electron as electron } from 'playwright';
import path from 'node:path';
import fs from 'node:fs/promises';

////////////////////////////////////////////////////////////////////////////////
// Helpers
////////////////////////////////////////////////////////////////////////////////

/**
 * Grabs the internal (domain-layer) JSON representation of the current
 * workspace via a test-only IPC channel exposed by the main process.
 */
async function getSerializedWorkspace(app: ElectronApplication) {
  return await app.evaluate(async ({ ipcMain }) => {
    return await ipcMain.handle('TEST.BACKDOOR.GET_WORKSPACE_STATE');
  });
}

/**
 * Waits for the canvas to contain exactly `count` nodes.  Assumes that
 * every rendered node carries the `data-testid="canvas-node"` attribute.
 */
async function waitForNodeCount(page: Page, count: number) {
  await expect(page.locator('[data-testid="canvas-node"]')).toHaveCount(count, {
    timeout: 5_000,
  });
}

/**
 * Returns an absolute path to the packaged electron entry.
 */
function resolveAppPath(): string {
  const fromEnv = process.env.E2E_APP_PATH;
  if (fromEnv && fromEnv.length > 0) return fromEnv;

  // Fallback to the dev entry used by `npm start`
  return path.join(__dirname, '..', '..', 'dist', 'main.js');
}

/**
 * Generates a temporary workspace file that the app will open in a
 * clean state before each test.
 */
async function createTempWorkspace(): Promise<string> {
  const tmpPath = path.join(
    process.cwd(),
    '.tmp',
    `pfw-${Date.now()}-${Math.random().toString(16).slice(2)}.pflow`
  );
  await fs.mkdir(path.dirname(tmpPath), { recursive: true });
  await fs.writeFile(
    tmpPath,
    JSON.stringify({
      id: 'tmp-ws',
      version: 1,
      nodes: [],
      links: [],
    })
  );
  return tmpPath;
}

////////////////////////////////////////////////////////////////////////////////
// Test suite
////////////////////////////////////////////////////////////////////////////////

test.describe('Node interaction happy-paths', () => {
  let app: ElectronApplication;
  let page: Page;
  let workspaceFile: string;

  test.beforeAll(async () => {
    workspaceFile = await createTempWorkspace();

    app = await electron.launch({
      args: [resolveAppPath(), '--workspace', workspaceFile, '--disable-gpu'],
      env: {
        /* forward minimal env so crash reporter won’t spam Sentry */
        NODE_ENV: 'test',
        E2E: 'true',
      },
    });

    // The first renderer window
    page = await app.firstWindow();

    // Ensure the workspace fully loads before running tests
    await page.waitForSelector('[data-testid="canvas"]', { timeout: 10_000 });
  });

  test.afterAll(async () => {
    await app.close();
    // Clean up tmp workspace
    await fs.rm(workspaceFile, { force: true });
  });

  ////////////////////////////////////////////////////////////////////////////
  // 1. Create & persist markdown node
  ////////////////////////////////////////////////////////////////////////////

  test('creates a markdown node via ⌘+Shift+M and persists it', async () => {
    // Ensure canvas starts empty
    await waitForNodeCount(page, 0);

    // macOS style accelerator (works cross-platform in tests)
    await page.keyboard.press('Meta+Shift+M');

    // Modal quick-create palette appears
    await page.waitForSelector('[data-testid="quick-create-modal"]');
    await page.fill('[data-testid="node-title-input"]', 'Daily Log');
    await page.press('[data-testid="node-title-input"]', 'Enter');

    // A single node should now be visible
    await waitForNodeCount(page, 1);

    const node = page.locator('[data-testid="canvas-node"]').first();
    await expect(node).toContainText('Daily Log');

    // Close application to force disk write
    await app.evaluate(async ({ app }) => {
      await app.quit();
    });

    // Re-launch with the same workspace, ensure node persists
    app = await electron.launch({
      args: [resolveAppPath(), '--workspace', workspaceFile],
      env: { NODE_ENV: 'test', E2E: 'true' },
    });
    page = await app.firstWindow();
    await waitForNodeCount(page, 1);
    await expect(page.locator('[data-testid="canvas-node"]').first()).toContainText('Daily Log');
  });

  ////////////////////////////////////////////////////////////////////////////
  // 2. Link two nodes together through drag gesture
  ////////////////////////////////////////////////////////////////////////////

  test('links two nodes via drag-connector and updates domain state', async () => {
    // Pre-condition: we have 1 node from previous test
    // Create second node
    await page.click('[data-testid="toolbar-new-node"]');
    await page.fill('[data-testid="node-title-input"]', 'Tasks');
    await page.keyboard.press('Enter');
    await waitForNodeCount(page, 2);

    const firstNode = page.locator('[data-testid="canvas-node"] >> text=Daily Log');
    const secondNode = page.locator('[data-testid="canvas-node"] >> text=Tasks');

    // Grab the output handle of node-1 and drop on node-2’s input
    const firstAnchor = firstNode.locator('[data-testid="node-anchor-out"]');
    const secondAnchor = secondNode.locator('[data-testid="node-anchor-in"]');

    const firstBox = await firstAnchor.boundingBox();
    const secondBox = await secondAnchor.boundingBox();
    if (!firstBox || !secondBox) throw new Error('Anchor missing bounding box');

    await page.mouse.move(firstBox.x + firstBox.width / 2, firstBox.y + firstBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(secondBox.x + secondBox.width / 2, secondBox.y + secondBox.height / 2, { steps: 10 });
    await page.mouse.up();

    // A link element should now exist
    await page.waitForSelector('[data-testid="canvas-link"]');

    // Validate domain state via backdoor IPC
    const ws = await getSerializedWorkspace(app);
    expect(ws.links.length).toBeGreaterThan(0);
    const link = ws.links.find(
      (l: any) => l.from.title === 'Daily Log' && l.to.title === 'Tasks'
    );
    expect(link).toBeTruthy();
  });

  ////////////////////////////////////////////////////////////////////////////
  // 3. Undo / Redo stack for node movement
  ////////////////////////////////////////////////////////////////////////////

  test('moves a node, undo and redo restores position correctly', async () => {
    const node = page.locator('[data-testid="canvas-node"] >> text=Daily Log');
    const originalBox = await node.boundingBox();
    if (!originalBox) throw new Error('Node bounding box not found');

    // Drag node by 200px to the right
    await page.mouse.move(originalBox.x + 20, originalBox.y + 20);
    await page.mouse.down();
    await page.mouse.move(originalBox.x + 220, originalBox.y + 20, { steps: 15 });
    await page.mouse.up();

    const movedBox = await node.boundingBox();
    expect(movedBox?.x).toBeGreaterThan(originalBox.x + 150); // moved right

    // Undo (⌘+Z)
    await page.keyboard.press('Meta+Z');
    const undoneBox = await node.boundingBox();
    expect(Math.abs((undoneBox?.x ?? 0) - originalBox.x)).toBeLessThan(5);

    // Redo (⇧+⌘+Z)
    await page.keyboard.press('Meta+Shift+Z');
    const redoneBox = await node.boundingBox();
    expect(redoneBox?.x).toBeGreaterThan(originalBox.x + 150);
  });
});
```