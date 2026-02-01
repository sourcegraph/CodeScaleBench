```typescript
/**
 * Vite configuration for the StellarStage Carnival front-end.
 *
 * The configuration reflects the requirements of an interactive,
 * Web-Socket/GraphQL driven React-Three dApp that must co-exist
 * with WebCrypto / Ethereum provider libraries running in the
 * browser.  It therefore:
 *
 *  • Injects blockchain + IPFS environment variables at build-time.
 *  • Polyfills Node globals for browser-only bundles.
 *  • Enables HTTPS in dev when local certs are available so MetaMask
 *    will inject the provider without complaining.
 *  • Splits vendor chunks intelligently to keep bundle sizes small.
 *  • Registers a PWA service worker to allow offline replay-mode.
 */

import { defineConfig, loadEnv, UserConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tsconfigPaths from 'vite-tsconfig-paths';
import { VitePWA } from 'vite-plugin-pwa';
import viteCompression from 'vite-plugin-compression';
import svgrPlugin from 'vite-plugin-svgr';
import { NodeGlobalsPolyfillPlugin } from '@esbuild-plugins/node-globals-polyfill';
import { NodeModulesPolyfillPlugin } from '@esbuild-plugins/node-modules-polyfill';

import fs from 'fs';
import path from 'path';

/* -------------------------------------------------------------------------- */
/*                               Helper Methods                               */
/* -------------------------------------------------------------------------- */

/**
 * Attempt to load a local SSL certificate so that the dev-server can
 * run on HTTPS.  Certain browser wallets (e.g. MetaMask) will refuse
 * to inject `window.ethereum` on insecure origins.
 */
function loadDevHttpsConfig(): UserConfig['server']['https'] {
  try {
    const keyPath  = path.resolve(process.cwd(), 'certs/localhost+2-key.pem');
    const certPath = path.resolve(process.cwd(), 'certs/localhost+2.pem');
    if (fs.existsSync(keyPath) && fs.existsSync(certPath)) {
      return {
        key : fs.readFileSync(keyPath),
        cert: fs.readFileSync(certPath),
      };
    }

    // eslint-disable-next-line no-console
    console.warn(
      '[vite] HTTPS requested but certificate files were not found. Falling back to HTTP.',
    );
    return false;
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error('[vite] Failed to load SSL certificates:', err);
    return false;
  }
}

/** Read the root `package.json` to forward the version into the client. */
function getAppVersion(): string {
  try {
    const pkgJsonPath = path.resolve(__dirname, '../../package.json');
    const pkg = JSON.parse(fs.readFileSync(pkgJsonPath, 'utf-8')) as {
      version?: string;
    };

    return pkg.version ?? '0.0.0-dev';
  } catch {
    return '0.0.0-dev';
  }
}

/* -------------------------------------------------------------------------- */
/*                              Vite Definition                               */
/* -------------------------------------------------------------------------- */

export default defineConfig(({ mode }) => {
  // Load only variables prefixed with `VITE_`
  const viteEnv = loadEnv(mode, process.cwd(), 'VITE_');

  const isProduction = mode === 'production';
  const appVersion   = getAppVersion();

  return {
    // Expose env-vars and build-time constants
    define: {
      __APP_ENV__:           JSON.stringify(mode),
      __APP_VERSION__:       JSON.stringify(appVersion),
      __SMART_CHAIN_ID__:    JSON.stringify(viteEnv.VITE_CHAIN_ID),
      __IPFS_GATEWAY_URL__:  JSON.stringify(viteEnv.VITE_IPFS_GATEWAY),
    },

    plugins: [
      react(),
      tsconfigPaths(),
      svgrPlugin(),
      viteCompression({
        algorithm: 'gzip',
        threshold: 10 * 1024, // Only assets larger than 10kb
        ext: '.gz',
      }),
      VitePWA({
        registerType: 'autoUpdate',
        includeAssets: [
          'favicon.svg',
          'robots.txt',
          'apple-touch-icon.png',
        ],
        manifest: {
          name:        'StellarStage Carnival',
          short_name:  'SSC',
          description: 'Interactive NFT Showrunner',
          theme_color: '#000000',
          background_color: '#000000',
          display: 'standalone',
          icons: [
            {
              src: '/pwa-192x192.png',
              sizes: '192x192',
              type: 'image/png',
            },
            {
              src: '/pwa-512x512.png',
              sizes: '512x512',
              type: 'image/png',
            },
            {
              src: '/pwa-512x512.png',
              sizes: '512x512',
              type: 'image/png',
              purpose: 'any maskable',
            },
          ],
        },
      }),
    ],

    resolve: {
      alias: {
        // Monorepo root layers – match Clean Architecture boundaries
        '@core'         : path.resolve(__dirname, '../../domain'),
        '@application'  : path.resolve(__dirname, '../../application'),
        '@infrastructure': path.resolve(__dirname, '../../infrastructure'),
        '@ui'           : path.resolve(__dirname, 'src'),
      },
    },

    /* ------------------------------------------------------------------ */
    /*                         Dev-server Settings                         */
    /* ------------------------------------------------------------------ */
    server: {
      host  : viteEnv.VITE_DEV_HOST || '0.0.0.0',
      port  : Number(viteEnv.VITE_DEV_PORT) || 5173,
      https : viteEnv.VITE_DEV_HTTPS === 'true' ? loadDevHttpsConfig() : false,
      open  : !isProduction,
      // Proxy API calls to the GraphQL orchestrator if running locally
      proxy : {
        '/graphql': {
          target      : viteEnv.VITE_DEV_GRAPHQL_PROXY ?? 'http://localhost:4000',
          changeOrigin: true,
        },
        '/socket.io': {
          target      : viteEnv.VITE_DEV_SOCKET_PROXY ?? 'ws://localhost:4001',
          ws          : true,
          changeOrigin: true,
        },
      },
    },

    /* ------------------------------------------------------------------ */
    /*                         Build optimisation                          */
    /* ------------------------------------------------------------------ */
    build: {
      target: 'esnext',
      outDir: 'dist',
      sourcemap: !isProduction,
      rollupOptions: {
        output: {
          /**
           * Separate large libraries (react, three) so that subsequent
           * deployments can better leverage browser HTTP-cache.
           */
          manualChunks(id) {
            if (id.includes('node_modules')) {
              if (id.includes('three'))       { return 'vendor_three';  }
              if (id.includes('react'))       { return 'vendor_react';  }
              if (id.includes('graphql'))     { return 'vendor_gql';    }
              if (id.includes('ethers'))      { return 'vendor_ethers'; }
              return 'vendor_misc';
            }
          },
        },
      },
    },

    /* ------------------------------------------------------------------ */
    /*                       Dependency optimisation                       */
    /* ------------------------------------------------------------------ */
    optimizeDeps: {
      esbuildOptions: {
        plugins: [
          // Polyfill `process` and `buffer` for browser libraries
          NodeGlobalsPolyfillPlugin({
            process: true,
            buffer : true,
          }),
          // Polyfill Node built-ins (crypto, stream, etc)
          NodeModulesPolyfillPlugin(),
        ],
      },
      include: [
        'buffer',
        'process',
        'events',
        'stream',
        'crypto',
      ],
    },
  };
});
```