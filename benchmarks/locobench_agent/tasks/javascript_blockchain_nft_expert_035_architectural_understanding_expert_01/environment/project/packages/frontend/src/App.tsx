```tsx
/**
 * StellarStage Carnival
 * Front-end Root Component
 *
 * Clean-architecture Note:
 *  –  This file only wires framework level concerns (routing, DI containers, providers)
 *     and NEVER imports domain entities or business rules directly.
 */

import React, { Suspense, useMemo } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

import { ThemeProvider, CssBaseline } from '@mui/material';
import { SnackbarProvider } from 'notistack';

import {
  ApolloClient,
  ApolloProvider,
  InMemoryCache,
  createHttpLink,
  ApolloLink,
  from,
  split,
} from '@apollo/client';
import { GraphQLWsLink } from '@apollo/client/link/subscriptions';
import { getMainDefinition } from '@apollo/client/utilities';
import { createClient as createWsClient } from 'graphql-ws';

import { EventBusProvider } from '@/infrastructure/eventBus/react';
import { WalletProvider } from '@/infrastructure/wallet/react';
import darkTheme from '@/ui/theme/dark';

import FullScreenLoader from '@/ui/components/feedback/FullScreenLoader';
import ErrorFallback from '@/ui/components/feedback/ErrorFallback';
import ErrorBoundary from '@/ui/components/util/ErrorBoundary';
import useGlobalEventHandlers from '@/ui/hooks/useGlobalEventHandlers';

// ---------- Lazy-loaded route modules ----------
const HomePage = React.lazy(() => import('@/ui/pages/HomePage'));
const ShowRunnerPage = React.lazy(() => import('@/ui/pages/ShowRunnerPage'));
const PassStakingPage = React.lazy(() => import('@/ui/pages/PassStakingPage'));
const NotFoundPage = React.lazy(() => import('@/ui/pages/NotFoundPage'));

// ---------- Environment Utilities ----------
const getEnv = (key: string, fallback?: string): string => {
  const value = import.meta.env[key] ?? process.env[key];
  if (!value && fallback === undefined) {
    // eslint-disable-next-line no-console
    console.warn(`Environment variable ${key} is not defined`);
  }
  return value ?? fallback ?? '';
};

// ---------- Apollo / GraphQL Client Factory ----------
const buildApolloClient = (): ApolloClient<unknown> => {
  const httpLink = createHttpLink({
    uri: getEnv('VITE_GRAPHQL_HTTP_URL', 'https://api.stellarstage.io/graphql'),
    credentials: 'include',
  });

  /* Auth header link connects to the current wallet, if any  */
  const authLink = new ApolloLink((operation, forward) => {
    const token = localStorage.getItem('auth_token'); // JWT issued by backend after wallet signature
    if (token) {
      operation.setContext(({ headers = {} }) => ({
        headers: { ...headers, authorization: `Bearer ${token}` },
      }));
    }
    return forward(operation);
  });

  /* Centralized error handler – surfaces GraphQL & network errors to UI */
  const errorLink = new ApolloLink((operation, forward) =>
    forward(operation).map((response) => {
      if (response.errors?.length) {
        // we throw so the calling component can boundary-catch if needed
        throw response.errors;
      }
      return response;
    }),
  );

  /* Realtime subscription link over WebSockets */
  const wsClient = createWsClient({
    url: getEnv(
      'VITE_GRAPHQL_WS_URL',
      'wss://api.stellarstage.io/graphql',
    ),
    connectionParams: () => {
      const token = localStorage.getItem('auth_token');
      return token ? { Authorization: `Bearer ${token}` } : {};
    },
  });

  const wsLink = new GraphQLWsLink(wsClient);

  /* Split based on operation type (query/mutation vs subscription) */
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

  return new ApolloClient({
    link: from([errorLink, authLink, splitLink]),
    cache: new InMemoryCache({
      typePolicies: {
        Query: {
          fields: {
            /* ensures relay-style pagination works out of the box */
            paginatedShows: {
              keyArgs: false,
              merge(existing = { items: [] }, incoming) {
                return {
                  ...incoming,
                  items: [...existing.items, ...incoming.items],
                };
              },
            },
          },
        },
      },
    }),
    connectToDevTools: getEnv('NODE_ENV') !== 'production',
  });
};

// ---------- Root App Component ----------
const App: React.FC = () => {
  const apolloClient = useMemo(() => buildApolloClient(), []);

  /* Global event handlers register listeners (keyboard, visibilitychange, etc.) */
  useGlobalEventHandlers();

  return (
    <ErrorBoundary fallback={<ErrorFallback />}>
      <ThemeProvider theme={darkTheme}>
        <CssBaseline />
        <ApolloProvider client={apolloClient}>
          <WalletProvider>
            <EventBusProvider>
              <SnackbarProvider
                maxSnack={4}
                anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
              >
                <BrowserRouter>
                  <Suspense fallback={<FullScreenLoader />}>
                    <Routes>
                      <Route path="/" element={<HomePage />} />
                      <Route path="/show/:showId" element={<ShowRunnerPage />} />
                      <Route path="/stake" element={<PassStakingPage />} />
                      <Route path="/404" element={<NotFoundPage />} />
                      <Route path="*" element={<Navigate to="/404" replace />} />
                    </Routes>
                  </Suspense>
                </BrowserRouter>
              </SnackbarProvider>
            </EventBusProvider>
          </WalletProvider>
        </ApolloProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
};

export default App;
```
