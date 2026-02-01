```typescript
/**
 * End-to-end tests for basic Workspace CRUD operations in PaletteFlow Studio.
 *
 * These tests drive the real Electron bundle through Playwright in headless
 * mode.  The UI is exercised the same way a user would—with clicks and key
 * presses—so we can detect any regression in renderer logic, IPC glue, or
 * persisted workspace metadata.
 *
 * IMPORTANT
 * ---------
 * • All UI elements involved in these tests MUST expose a
 *   `data-test-id="<semantic-id>"` attribute in production code.
 *   That keeps the tests resilient to class-name / styling churn.
 * • The tests assume the app will create a temporary user-data directory
 *   when `NODE_ENV === "test"`.  Do NOT write to the real user profile.
 *
 * Tools/stack
 * -----------
 * • Playwright Test (https://playwright.dev/docs/api/class-test)
 * • Electron automation binding (`_electron` export)
 *
 * Author: PaletteFlow QA Engineering
 * -------------------------------------------------------------------------- */
import { test, expect, ElectronApplication, Page, _electron as electron } from '@playwright/test';
import path from 'node:path';
import fs from 'fs-extra';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/** Absolute path to the compiled Electron main entry (built by `pnpm build`). */
const ELECTRON_MAIN_PATH = path.resolve(__dirname, '../../../dist/main.js');

/** Reusable selectors mapped to their test-ID counterparts. */
const UI = {
  // Dashboard / start screen
  newWorkspaceBtn: '[data-test-id="new-workspace"]',
  workspaceNameInput: '[data-test-id="workspace-name-input"]',
  createWorkspaceConfirmBtn: '[data-test-id="create-workspace-confirm"]',
  workspaceCardByName: (name: string) => `[data-test-id="workspace-card-${name}"]`,
  deleteWorkspaceBtn: '[data-test-id="delete-workspace"]',
  duplicateWorkspaceBtn: '[data-test-id="duplicate-workspace"]',
  confirmDeleteBtn: '[data-test-id="confirm-delete"]',

  // Editor
  canvasStage: '[data-test-id="canvas"]',
  addNodeBtn: '[data-test-id="toolbar-add-node"]',
  nodeTitleInput: '[data-test-id="node-title-input"]',
  saveWorkspaceBtn: '[data-test-id="save-workspace"]',
  backToDashboardBtn: '[data-test-id="back-to-dashboard"]',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Launches an Electron instance of PaletteFlow Studio in test mode.
 */
async function launchApp(): Promise<{
  app: ElectronApplication;
  window: Page;
}> {
  const app = await electron.launch({
    args: [ELECTRON_MAIN_PATH],
    env: {
      NODE_ENV: 'test',
      // Ensure a fresh profile is used so tests don't leak state.
      PAL_FLOW_TEST_PROFILE_DIR: path.resolve(__dirname, '../../.tmp/profiles', `${Date.now()}`),
    },
  });

  const window = await app.firstWindow();
  // Enforce predictable window size so UI coordinates don't change between CI agents.
  await window.setViewportSize({ width: 1280, height: 800 });

  return { app, window };
}

/**
 * Polls for a workspace card to appear in the dashboard.
 */
async function waitForWorkspaceCard(window: Page, name: string): Promise<void> {
  await expect(window.locator(UI.workspaceCardByName(name))).toBeVisible({
    timeout: 5_000,
  });
}

/**
 * Generates a unique workspace name for test isolation.
 */
function uniqueWorkspaceName(prefix = 'e2e-ws'): string {
  return `${prefix}-${Date.now().toString(36)}`;
}

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

test.describe('Workspace CRUD 📁', () => {
  let electronApp: ElectronApplication;
  let win: Page;

  // Boot once for entire suite to speed things up.
  test.beforeAll(async () => {
    const { app, window } = await launchApp();
    electronApp = app;
    win = window;
  });

  // Close Electron when suite is done.
  test.afterAll(async () => {
    await electronApp.close();
    // Clean up temp filesystem profile if present
    const tmpDir = process.env['PAL_FLOW_TEST_PROFILE_DIR'];
    if (tmpDir && (await fs.pathExists(tmpDir))) {
      await fs.remove(tmpDir).catch(console.error);
    }
  });

  // Each test returns to dashboard to keep them independent.
  test.afterEach(async () => {
    // Try closing editor if it's still open; ignore errors when not present.
    try {
      if (await win.locator(UI.backToDashboardBtn).isVisible({ timeout: 500 })) {
        await win.click(UI.backToDashboardBtn);
      }
    } catch {
      /* no-op */
    }
  });

  // -------------------------------------------------------------------------
  // Test cases
  // -------------------------------------------------------------------------

  test('creates a new workspace and persists a node', async () => {
    const workspaceName = uniqueWorkspaceName();

    /* 1️⃣  Create a new workspace from start screen */
    await win.click(UI.newWorkspaceBtn);
    await win.fill(UI.workspaceNameInput, workspaceName);
    await win.click(UI.createWorkspaceConfirmBtn);

    /* Wait for editor canvas to show up */
    await expect(win.locator(UI.canvasStage)).toBeVisible();

    /* 2️⃣  Add a node so that we can later verify persistence */
    await win.click(UI.addNodeBtn);
    await win.fill(UI.nodeTitleInput, 'Hello Node');
    await win.press(UI.nodeTitleInput, 'Enter');

    /* 3️⃣  Save & return to dashboard */
    await win.click(UI.saveWorkspaceBtn);
    await win.click(UI.backToDashboardBtn);

    /* 4️⃣  Ensure workspace card exists */
    await waitForWorkspaceCard(win, workspaceName);

    /* 5️⃣  Re-open workspace and confirm node is still there */
    await win.click(UI.workspaceCardByName(workspaceName));
    await expect(win.locator(UI.canvasStage)).toBeVisible();

    const nodeCount = await win.locator('[data-test-id="canvas-node"]').count();
    expect(nodeCount).toBeGreaterThanOrEqual(1);

    // Back to dashboard for next test
    await win.click(UI.backToDashboardBtn);
  });

  test('duplicates an existing workspace ("branch")', async () => {
    const originalName = uniqueWorkspaceName('branch-src');
    const duplicateName = `${originalName}-copy`;

    /* Create original workspace (reuse helper) */
    await win.click(UI.newWorkspaceBtn);
    await win.fill(UI.workspaceNameInput, originalName);
    await win.click(UI.createWorkspaceConfirmBtn);

    await expect(win.locator(UI.canvasStage)).toBeVisible();
    await win.click(UI.saveWorkspaceBtn);
    await win.click(UI.backToDashboardBtn);

    await waitForWorkspaceCard(win, originalName);

    /* Duplicate */
    const card = win.locator(UI.workspaceCardByName(originalName));
    await card.hover(); // reveal ⋮ menu or inline buttons
    await win.click(`${UI.workspaceCardByName(originalName)} ${UI.duplicateWorkspaceBtn}`);

    // Confirm duplication dialog auto-suggests a name
    await win.locator(UI.workspaceNameInput).fill(duplicateName);
    await win.click(UI.createWorkspaceConfirmBtn);

    await expect(win.locator(UI.canvasStage)).toBeVisible();
    await win.click(UI.backToDashboardBtn);

    // Original & duplicate should both be present
    await waitForWorkspaceCard(win, originalName);
    await waitForWorkspaceCard(win, duplicateName);
  });

  test('deletes a workspace permanently when confirmed', async () => {
    const doomedName = uniqueWorkspaceName('todelete');

    /* Prep workspace */
    await win.click(UI.newWorkspaceBtn);
    await win.fill(UI.workspaceNameInput, doomedName);
    await win.click(UI.createWorkspaceConfirmBtn);
    await win.click(UI.backToDashboardBtn);

    await waitForWorkspaceCard(win, doomedName);

    /* Delete via context menu */
    const card = win.locator(UI.workspaceCardByName(doomedName));
    await card.hover();
    await win.click(`${UI.workspaceCardByName(doomedName)} ${UI.deleteWorkspaceBtn}`);

    // Expect confirmation modal
    await expect(win.locator(UI.confirmDeleteBtn)).toBeVisible();
    await win.click(UI.confirmDeleteBtn);

    // Workspace card should disappear
    await expect(win.locator(UI.workspaceCardByName(doomedName))).toBeHidden({
      timeout: 5_000,
    });
  });
});
```