```typescript
/**
 * PaletteFlow Studio – Playwright end-to-end test configuration
 * --------------------------------------------------------------
 * This file centralises all E2E settings for local development
 * and CI lanes (GitHub Actions, Azure Pipelines, etc.).  Because
 * PaletteFlow is an Electron desktop app that also exposes a Web
 * renderer (for internal docs), two dedicated Playwright projects
 * are declared:
 *
 *   1. electron-app  – Boots the packaged Electron binary and
 *                      exercises real user flows such as opening
 *                      workspaces, spawning new windows, and
 *                      interacting with plugin UIs.
 *   2. web-preview   – Targets the headless Web preview build
 *                      (used by the docs site and plugin sandbox)
 *                      and runs classic browser tests in parallel.
 *
 * Playwright’s powerful project matrix lets us keep the two
 * concerns separate while sharing reporters, fixtures and helpers.
 */

import { devices, defineConfig, PlaywrightTestConfig } from '@playwright/test';
import path from 'path';
import fs from 'fs';

/* ------------------------------------------------------------------ */
/* ENVIRONMENT HELPERS                                                 */
/* ------------------------------------------------------------------ */

/**
 * Returns `true` when running in a Continuous-Integration agent.
 */
const isCI = (): boolean => process.env.CI === 'true' || process.env.CI === '1';

/**
 * Fetches an environment variable with an optional fallback.
 */
const env = (key: string, fallback?: string): string =>
  process.env[key] ?? (fallback ?? '');

/**
 * Resolve the absolute path to the compiled Electron main process
 * entry.  This assumes that the build pipeline outputs binaries to
 * `dist/desktop/`.
 */
const resolveElectronBinary = (): string => {
  const platform = process.platform;
  const distRoot = path.resolve(__dirname, '..', 'dist', 'desktop');

  if (platform === 'darwin') {
    // macOS – packaged as .app bundle
    return path.join(
      distRoot,
      'mac',
      'PaletteFlow Studio.app',
      'Contents',
      'MacOS',
      'PaletteFlow Studio',
    );
  }

  if (platform === 'win32') {
    // Windows – .exe
    return path.join(distRoot, 'win-unpacked', 'PaletteFlow Studio.exe');
  }

  // Linux – AppImage or unpacked
  return path.join(distRoot, 'linux-unpacked', 'paletteflow-studio');
};

/**
 * Ensure that the Electron binary exists before we pass it to
 * Playwright; otherwise fail fast with a clear error.
 */
const assertElectronBinary = (): string => {
  const bin = env('PALFLOW_E2E_ELECTRON_PATH', resolveElectronBinary());

  if (!fs.existsSync(bin)) {
    // eslint-disable-next-line no-console
    console.error(
      `\n[Playwright] Cannot locate Electron binary at:\n  ${bin}\n\n` +
        'Make sure you ran the desktop build step before executing E2E tests.\n',
    );
    process.exit(1);
  }

  return bin;
};

/* ------------------------------------------------------------------ */
/* SHARED USE OPTIONS                                                  */
/* ------------------------------------------------------------------ */

const sharedUse: PlaywrightTestConfig['use'] = {
  headless: isCI() || env('PALFLOW_E2E_HEADLESS', 'true') === 'true',
  screenshot: 'only-on-failure',
  video: isCI() ? 'retain-on-failure' : 'off',
  trace: 'on-first-retry',
  viewport: { width: 1440, height: 900 },
  ignoreHTTPSErrors: true,
  launchOptions: {
    slowMo: env('PALFLOW_E2E_SLOWMO', '0') ? +env('PALFLOW_E2E_SLOWMO') : 0,
  },
};

/* ------------------------------------------------------------------ */
/* PLAYWRIGHT CONFIGURATION                                            */
/* ------------------------------------------------------------------ */

export default defineConfig({
  testDir: path.resolve(__dirname, 'tests'),
  outputDir: path.resolve(__dirname, 'results'),

  /* General timeouts */
  timeout: 90 * 1000,
  expect: {
    timeout: 5_000,
  },

  /* Fail the build on unhandled console errors emitted by the app */
  forbidOnly: isCI(),
  fullyParallel: true,
  retries: isCI() ? 2 : 0,
  workers: isCI() ? 4 : undefined,

  /* Global lifecycle hooks */
  globalSetup: path.resolve(__dirname, 'utils', 'globalSetup.ts'),
  globalTeardown: path.resolve(__dirname, 'utils', 'globalTeardown.ts'),

  /* Test reporters */
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
    ...(isCI() ? [['github']] : []),
  ],

  /* Shared settings for each project below                   */
  use: sharedUse,

  /* Define project matrix                                     */
  projects: [
    /* ------------------------------------------------------ */
    /* Desktop – Electron                                      */
    /* ------------------------------------------------------ */
    {
      name: 'electron-app',
      testMatch: /\.electron\.spec\.(ts|js)/,
      use: {
        ...sharedUse,
        /* Custom fixture inherits the binary location via env */
        launchOptions: {
          ...sharedUse.launchOptions,
          executablePath: assertElectronBinary(),
          args: [
            '--no-sandbox',
            '--disable-gpu',
            env('PALFLOW_E2E_DEVTOOLS', 'false') === 'true' ? '--auto-open-devtools-for-tabs' : '',
          ].filter(Boolean),
        },
      },
    },

    /* ------------------------------------------------------ */
    /* Web preview – Chromium / WebKit / Firefox              */
    /* ------------------------------------------------------ */
    {
      name: 'web-preview-chromium',
      testMatch: /\.web\.spec\.(ts|js)/,
      use: {
        ...sharedUse,
        browserName: 'chromium',
        baseURL: env('PALFLOW_PREVIEW_URL', 'http://localhost:5173'),
      },
    },
    {
      name: 'web-preview-firefox',
      testMatch: /\.web\.spec\.(ts|js)/,
      use: {
        ...sharedUse,
        browserName: 'firefox',
        baseURL: env('PALFLOW_PREVIEW_URL', 'http://localhost:5173'),
      },
    },
    {
      name: 'web-preview-webkit',
      testMatch: /\.web\.spec\.(ts|js)/,
      use: {
        ...sharedUse,
        browserName: 'webkit',
        baseURL: env('PALFLOW_PREVIEW_URL', 'http://localhost:5173'),
      },
    },

    /* ------------------------------------------------------ */
    /* Integration for mobile viewport regression             */
    /* ------------------------------------------------------ */
    {
      name: 'mobile-chrome',
      testMatch: /\.web\.spec\.(ts|js)/,
      use: {
        ...sharedUse,
        browserName: 'chromium',
        ...devices['Pixel 5'],
        baseURL: env('PALFLOW_PREVIEW_URL', 'http://localhost:5173'),
      },
    },
  ],

  /* Configure screenshot diff thresholds for visual testing */
  expect: {
    toMatchSnapshot: {
      threshold: 0.15, // 15 % mismatch tolerated on CI
    },
    timeout: 10_000,
  },
});
```