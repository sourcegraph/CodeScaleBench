```javascript
/**
 * App.js
 * Main React entry-point for PulseLearn Campus Hub frontend.
 *
 * Responsibilities:
 * 1. Bootstrap global providers (Redux, React-Query, Auth, WebSocket, MUI, etc.).
 * 2. Enforce SSL in production (security requirement).
 * 3. Configure routes (public, protected, admin-only) using react-router v6.
 * 4. Provide global UI helpers (error boundary, snackbars, idle-timeout handling).
 *
 * NOTE: Most referenced modules/components live in sibling folders; they are
 *       intentionally imported rather than inlined to keep this file focused.
 */

import React, { useEffect, useMemo, Suspense } from 'react';
import PropTypes from 'prop-types';
import {
  BrowserRouter as Router,
  Routes,
  Route,
  Navigate,
  useLocation,
} from 'react-router-dom';

import { Provider as ReduxProvider } from 'react-redux';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { ThemeProvider, createTheme } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import { SnackbarProvider } from 'notistack';

import store from './store'; // Redux store
import { useAuth, AuthProvider } from './context/AuthContext';
import SocketProvider from './context/SocketContext';
import EventProvider from './context/EventContext';
import IdleTimerProvider from './components/session/IdleTimerProvider';

import ErrorBoundary from './components/common/ErrorBoundary';
import LoadingScreen from './components/common/LoadingScreen';
import GlobalModalContainer from './components/common/GlobalModalContainer';

/* -------------------------------------------------------------------------- */
/*  Code-Split Pages (lazy loaded)                                            */
/* -------------------------------------------------------------------------- */

const Home         = React.lazy(() => import('./pages/Home'));
const Login        = React.lazy(() => import('./pages/auth/Login'));
const Register     = React.lazy(() => import('./pages/auth/Register'));
const Dashboard    = React.lazy(() => import('./pages/dashboard/Dashboard'));
const Course       = React.lazy(() => import('./pages/course/Course'));
const AdminPanel   = React.lazy(() => import('./pages/admin/AdminPanel'));
const NotFound     = React.lazy(() => import('./pages/NotFound'));

/* -------------------------------------------------------------------------- */
/*  ProtectedRoute — wrapper to guard private / admin routes                  */
/* -------------------------------------------------------------------------- */

function ProtectedRoute({ children, requireAdmin = false }) {
  const { user, isAdmin } = useAuth();
  const location = useLocation();

  // Redirect unauthenticated users to login page.
  if (!user) {
    return <Navigate to="/auth/login" replace state={{ from: location }} />;
  }

  // Redirect non-admins trying to reach admin-only routes.
  if (requireAdmin && !isAdmin) {
    return <Navigate to="/dashboard" replace />;
  }

  return children;
}

ProtectedRoute.propTypes = {
  children: PropTypes.node.isRequired,
  requireAdmin: PropTypes.bool,
};

/* -------------------------------------------------------------------------- */
/*  Main App Component                                                        */
/* -------------------------------------------------------------------------- */

function App() {
  /* ----------------------- Runtime initialisation ------------------------ */

  const queryClient = useMemo(() => new QueryClient(), []);

  const theme = useMemo(
    () =>
      createTheme({
        palette: {
          mode: 'light',
          primary: { main: '#1e88e5' },
          secondary: { main: '#ffb300' },
        },
        typography: {
          fontFamily: "'Inter', sans-serif",
        },
      }),
    []
  );

  /* ----------------------- Enforce HTTPS in production ------------------- */

  useEffect(() => {
    if (
      process.env.NODE_ENV === 'production' &&
      process.env.REACT_APP_FORCE_SSL === 'true' &&
      window.location.protocol !== 'https:'
    ) {
      // Preserve path & query string while upgrading to SSL
      window.location.href = `https://${window.location.host}${window.location.pathname}${window.location.search}`;
    }
  }, []);

  /* ----------------------- Render tree ----------------------------------- */

  return (
    <ReduxProvider store={store}>
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <ThemeProvider theme={theme}>
            <CssBaseline />

            <AuthProvider>
              <SocketProvider>
                <EventProvider>
                  <IdleTimerProvider timeoutMinutes={30}>
                    <SnackbarProvider
                      maxSnack={4}
                      anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
                    >
                      <Suspense fallback={<LoadingScreen />}>
                        <Router>
                          <GlobalModalContainer />
                          <AppRoutes />
                        </Router>
                      </Suspense>
                    </SnackbarProvider>
                  </IdleTimerProvider>
                </EventProvider>
              </SocketProvider>
            </AuthProvider>
          </ThemeProvider>
        </QueryClientProvider>
      </ErrorBoundary>
    </ReduxProvider>
  );
}

/* -------------------------------------------------------------------------- */
/*  Declarative route map                                                     */
/* -------------------------------------------------------------------------- */

function AppRoutes() {
  const { user, initializing, isAdmin } = useAuth();

  // Wait for auth provider to restore session (e.g., from LocalStorage)
  if (initializing) {
    return <LoadingScreen />;
  }

  return (
    <Routes>
      {/* ------------------ Public routes ------------------ */}
      <Route path="/" element={<Home />} />
      <Route
        path="/auth/login"
        element={!user ? <Login /> : <Navigate to="/dashboard" replace />}
      />
      <Route
        path="/auth/register"
        element={!user ? <Register /> : <Navigate to="/dashboard" replace />}
      />

      {/* ------------------ Protected routes --------------- */}
      <Route
        path="/dashboard/*"
        element={
          <ProtectedRoute>
            <Dashboard />
          </ProtectedRoute>
        }
      />

      <Route
        path="/courses/:courseId/*"
        element={
          <ProtectedRoute>
            <Course />
          </ProtectedRoute>
        }
      />

      {/* ------------------ Admin routes ------------------- */}
      <Route
        path="/admin/*"
        element={
          <ProtectedRoute requireAdmin>
            {isAdmin ? <AdminPanel /> : <Navigate to="/dashboard" replace />}
          </ProtectedRoute>
        }
      />

      {/* ------------------ Fallback ----------------------- */}
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

export default App;
```