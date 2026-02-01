```typescript
/**************************************************************************************************
 * StellarStage Carnival – Front-End Bootstrap
 * -------------------------------------------------------------
 * Entry point for the React‒Three application. Wires up the UI, data-layer clients (GraphQL,
 * WebSocket event bus, Ethereum provider), global contexts and error boundaries.
 *
 *   Clean Architecture Notice:
 *   ‑ Only infrastructure-level composition should live here. No business rules.
 *************************************************************************************************/

import React, { StrictMode, Suspense } from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { ThemeProvider, CssBaseline } from '@mui/material';
import { ApolloClient, ApolloProvider, InMemoryCache, split, HttpLink } from '@apollo/client';
import { GraphQLWsLink } from '@apollo/client/link/subscriptions';
import { createClient as createWSClient } from 'graphql-ws';
import { getMainDefinition } from '@apollo/client/utilities';
import { ethers } from 'ethers';
import { Buffer } from 'buffer';
import reportWebVitals from './reportWebVitals';

import App from './App';
import theme from './theme';
import { EventBusProvider } from './shared/eventBus';
import { BlockchainProvider } from './shared/blockchain';
import ErrorBoundary from './shared/ErrorBoundary';

/* -------------------------------------------------------------------------------------------------
 * Polyfills
 * Buffer is required by some crypto libraries used when the app is bundled for the browser.
 * ------------------------------------------------------------------------------------------------*/
window.Buffer = Buffer;

/* -------------------------------------------------------------------------------------------------
 * Environment
 * These are injected at build-time via Vite / Webpack DefinePlugin (REACT_APP_* convention).
 * ------------------------------------------------------------------------------------------------*/
const {
  VITE_GRAPHQL_HTTP,
  VITE_GRAPHQL_WS,
  VITE_ETHEREUM_RPC,
  VITE_INFURA_ID,
  VITE_SENTRY_DSN,
} = import.meta.env;

/* -------------------------------------------------------------------------------------------------
 * GraphQL (Apollo) Client
 * WebSocket link is used for live subscription feeds (e.g., real-time stage actions).
 * The split ensures that queries/mutations go over HTTP and subscriptions over WS.
 * ------------------------------------------------------------------------------------------------*/
const httpLink = new HttpLink({
  uri: VITE_GRAPHQL_HTTP,
  credentials: 'include',
});

const wsLink = new GraphQLWsLink(
  createWSClient({
    url: VITE_GRAPHQL_WS,
    retryAttempts: 3,
    shouldRetry: () => true,
    connectionParams: async () => {
      // Provide bearer token if the user is authenticated.
      const token = localStorage.getItem('ssc-auth-token');
      return token ? { headers: { Authorization: `Bearer ${token}` } } : {};
    },
  }),
);

const splitLink = split(
  ({ query }) => {
    const definition = getMainDefinition(query);
    return (
      definition.kind === 'OperationDefinition' &&
      definition.operation === 'subscription'
    );
  },
  wsLink,
  httpLink,
);

const apolloClient = new ApolloClient({
  link: splitLink,
  cache: new InMemoryCache({
    typePolicies: {
      Query: {
        fields: {
          // Merge incoming NFT traits instead of replacing to prevent UI flicker.
          traits: {
            merge(existing = [], incoming) {
              return [...existing, ...incoming];
            },
          },
        },
      },
    },
  }),
  defaultOptions: {
    watchQuery: { fetchPolicy: 'cache-and-network' },
  },
});

/* -------------------------------------------------------------------------------------------------
 * Ethereum Provider
 * Fallback to public (read-only) RPC if wallet is not connected.
 * ------------------------------------------------------------------------------------------------*/
const defaultProvider = new ethers.providers.InfuraProvider('homestead', VITE_INFURA_ID);

const connectToWallet = async (): Promise<ethers.providers.Web3Provider | ethers.providers.Provider> => {
  if (window.ethereum) {
    try {
      const web3Provider = new ethers.providers.Web3Provider(window.ethereum, 'any');
      // Prompt wallet connection.
      await web3Provider.send('eth_requestAccounts', []);
      return web3Provider;
    } catch (err) {
      // User rejected request or other problem, continue with read-only provider.
      console.warn('[Wallet] Connection failed, falling back to read-only provider:', err);
      return defaultProvider;
    }
  }
  return defaultProvider;
};

/* -------------------------------------------------------------------------------------------------
 * Bootstrap
 * React 18 concurrent root.
 * Suspense is used for lazy-loaded routes/components.
 * ------------------------------------------------------------------------------------------------*/
(async () => {
  const ethereumProvider = await connectToWallet();

  const container = document.getElementById('root');
  if (!container) throw new Error('[Bootstrap] #root container missing in index.html');

  const root = ReactDOM.createRoot(container);

  root.render(
    <StrictMode>
      <ErrorBoundary>
        <ThemeProvider theme={theme}>
          <CssBaseline />
          <ApolloProvider client={apolloClient}>
            <EventBusProvider>
              <BlockchainProvider provider={ethereumProvider}>
                <BrowserRouter basename="/">
                  <Suspense fallback={null}>
                    <App />
                  </Suspense>
                </BrowserRouter>
              </BlockchainProvider>
            </EventBusProvider>
          </ApolloProvider>
        </ThemeProvider>
      </ErrorBoundary>
    </StrictMode>,
  );

  // Performance reporting (optional, can be piped to analytics).
  reportWebVitals(console.debug);

  // Sentry or other error monitoring platform.
  if (VITE_SENTRY_DSN) {
    const { init } = await import('@sentry/react');
    init({
      dsn: VITE_SENTRY_DSN,
      tracesSampleRate: 0.2,
    });
  }
})();

/**************************************************************************************************
 * Module Hot Replacement (development only)
 **************************************************************************************************/
if (import.meta.hot) {
  import.meta.hot.accept();
}
```