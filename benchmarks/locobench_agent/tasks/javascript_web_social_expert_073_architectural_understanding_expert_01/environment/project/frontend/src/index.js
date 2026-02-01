```javascript
/**
 * PulseLearn Campus Hub – Front-end Entry Point
 * ------------------------------------------------
 * This file bootstraps the React application with every global provider that
 * the platform requires (Redux, React-Query, Theming, Routing, Auth, Event Bus, …).
 * 
 * NOTE:  All referenced modules (store, theme, App, etc.) live inside their
 *        respective directories and follow the same production-grade standards.
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import { Provider as ReduxProvider } from 'react-redux';
import { BrowserRouter } from 'react-router-dom';
import { ThemeProvider } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import { QueryClient, QueryClientProvider } from 'react-query';

import App from './App';
import store from './state/store';
import theme from './theme';

import EventBusProvider from './services/event-bus/EventBusProvider';
import AuthProvider from './services/auth/AuthProvider';

import ErrorBoundary from './components/common/ErrorBoundary';
import reportWebVitals from './reportWebVitals';
import { setupAxiosInterceptors } from './utils/axiosConfig';

// Initialise all global side-effects *before* rendering any UI.
setupAxiosInterceptors(store);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus : false,
      retry                : 1,
      suspense             : false,
    },
    mutations: {
      retry: 0,
    },
  },
});

// Grab the root element from the DOM.
const container = document.getElementById('root');
if (!container) {
  // eslint-disable-next-line no-console
  console.error(
    '[PulseLearn] <div id="root" /> is missing from index.html – aborting bootstrap.',
  );
  throw new Error('Critical: Unable to find root element');
}

const root = createRoot(container);

/**
 * Main render tree
 * ----------------
 *  <StrictMode>
 *    └─ ErrorBoundary  (catches JS errors from any descendant)
 *         └─ ReduxProvider (global state)
 *              └─ QueryClientProvider (data-fetching cache)
 *                   └─ EventBusProvider (WebSocket/SSE real-time events)
 *                        └─ AuthProvider (JWT session management)
 *                             └─ ThemeProvider (MUI theme & design-system)
 *                                  └─ BrowserRouter (client-side routing)
 *                                       └─ App (root component)
 */
root.render(
  <React.StrictMode>
    <ErrorBoundary>
      <ReduxProvider store={store}>
        <QueryClientProvider client={queryClient}>
          <EventBusProvider url={process.env.REACT_APP_EVENT_BUS_URL}>
            <AuthProvider>
              <ThemeProvider theme={theme}>
                <CssBaseline />
                <BrowserRouter>
                  <App />
                </BrowserRouter>
              </ThemeProvider>
            </AuthProvider>
          </EventBusProvider>
        </QueryClientProvider>
      </ReduxProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);

// Register service worker for offline support & faster reloads in production.
if ('serviceWorker' in navigator && process.env.NODE_ENV === 'production') {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/service-worker.js')
      .then((registration) => {
        // eslint-disable-next-line no-console
        console.info('[PulseLearn] ServiceWorker registered: ', registration);
      })
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.error('[PulseLearn] ServiceWorker registration failed: ', err);
      });
  });
}

// Collect Web Vitals & send to analytics/observability backend.
reportWebVitals((metric) => {
  // You can hook this into any APM (Datadog, NewRelic, OpenTelemetry, …)
  // Example: metricsService.send(metric);
  // eslint-disable-next-line no-console
  console.debug('[PulseLearn][WebVitals]', metric);
});
```