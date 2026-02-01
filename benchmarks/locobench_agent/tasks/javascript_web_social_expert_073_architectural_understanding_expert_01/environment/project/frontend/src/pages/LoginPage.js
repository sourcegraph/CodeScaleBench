```javascript
/**
 * PulseLearn Campus Hub - Login Page
 *
 * This component provides:
 *  • Traditional e-mail/password authentication
 *  • Google OAuth2 social sign-in
 *  • Institution-wide SSO sign-in
 *  • “Remember me” persisted sessions
 *  • SSL self-check guard (frontend only, sanity-check)
 *
 * It relies on:
 *  • AuthContext  – runtime authentication state
 *  • authService  – API wrapper around the /auth backend endpoints
 *  • react-hook-form + yup – declarative form handling & validation
 *  • Material-UI – visual components
 *
 * NOTE:
 *  – Any navigation intent coming from a protected route is preserved in location.state.from.
 *  – In case the page lives under “/admin/*”, copy changes the headline while
 *    still using the same business logic.
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  Avatar,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  FormControlLabel,
  Grid,
  Link,
  Paper,
  TextField,
  Typography,
  Alert
} from '@mui/material';
import LockOutlinedIcon from '@mui/icons-material/LockOutlined';
import { useNavigate, useLocation } from 'react-router-dom';
import { useForm, Controller } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as yup from 'yup';

// --- Local application modules ------------------------------------------------
import { useAuth } from '../contexts/AuthContext';
import authService from '../services/authService';
import trackEvent from '../utils/analytics';
import getSSLCertificateStatus from '../utils/sslHelper';

// Optional icons for social login buttons
import GoogleIcon from '../components/icons/GoogleIcon';
import SsoIcon from '../components/icons/SsoIcon';

// -----------------------------------------------------------------------------
// Validation schema (powered by yup)
// -----------------------------------------------------------------------------
const schema = yup.object({
  email: yup
    .string()
    .trim()
    .email('Invalid e-mail address')
    .required('E-mail is required'),
  password: yup
    .string()
    .min(6, 'Password must be at least 6 characters')
    .required('Password is required'),
  remember: yup.boolean()
});

/**
 * LoginPage – React functional component
 */
function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, currentUser } = useAuth();

  // ---------------------------------------------------------------------------
  // react-hook-form setup
  // ---------------------------------------------------------------------------
  const {
    control,
    handleSubmit,
    setError,
    formState: { isSubmitting }
  } = useForm({
    mode: 'onTouched',
    defaultValues: {
      email: '',
      password: '',
      remember: true
    },
    resolver: yupResolver(schema)
  });

  // ---------------------------------------------------------------------------
  // Local UI state
  // ---------------------------------------------------------------------------
  const [serverError, setServerError] = useState(null);
  const [sslReady, setSslReady]   = useState(true);

  // Redirect immediately if user is already authenticated
  useEffect(() => {
    if (currentUser) {
      navigate(location.state?.from || '/dashboard', { replace: true });
    }
  }, [currentUser, navigate, location.state]);

  // Perform a lightweight SSL sanity-check on first render
  useEffect(() => {
    let mounted = true;

    (async () => {
      try {
        const ok = await getSSLCertificateStatus();
        mounted && setSslReady(ok);
      } catch (e) {
        console.warn('SSL check failed', e);
      }
    })();

    return () => {
      mounted = false;
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------
  const onSubmit = useCallback(
    /**
     * Called when the e-mail/password form is submitted and passes validation.
     * @param {{ email: string, password: string, remember: boolean }} data
     */
    async (data) => {
      setServerError(null);

      try {
        const user = await authService.login(
          data.email,
          data.password,
          data.remember
        );

        await login(user);               // Cache token & user in context
        trackEvent('auth_login_success', { method: 'password' });

        navigate(location.state?.from || '/dashboard');
      } catch (err) {
        console.error('Login failed', err);
        trackEvent('auth_login_failure', {
          method: 'password',
          status: err?.response?.status
        });

        if (err?.response?.status === 401) {
          // Invalid credentials → field-level error
          setError('password', {
            type: 'manual',
            message: 'Invalid e-mail or password'
          });
        } else {
          // Generic / network error
          setServerError(
            'Unable to reach authentication service. Please try again later.'
          );
        }
      }
    },
    [login, navigate, location.state, setError]
  );

  const handleGoogleLogin = async () => {
    setServerError(null);
    try {
      const user = await authService.googleLogin(); // OAuth pop-up / redirect
      await login(user);
      trackEvent('auth_login_success', { method: 'google' });
      navigate('/dashboard');
    } catch (err) {
      console.error('Google login failed', err);
      setServerError('Google authentication failed.');
      trackEvent('auth_login_failure', { method: 'google', reason: err.message });
    }
  };

  const handleSsoLogin = async () => {
    setServerError(null);
    try {
      const user = await authService.ssoLogin(); // May open new window
      await login(user);
      trackEvent('auth_login_success', { method: 'sso' });
      navigate('/dashboard');
    } catch (err) {
      console.error('SSO login failed', err);
      setServerError('SSO authentication failed.');
      trackEvent('auth_login_failure', { method: 'sso', reason: err.message });
    }
  };

  // ---------------------------------------------------------------------------
  // SSL blocked UI
  // ---------------------------------------------------------------------------
  if (!sslReady) {
    return (
      <Box
        display="flex"
        alignItems="center"
        justifyContent="center"
        minHeight="100vh"
      >
        <Alert severity="error">
          Secure connection could not be established. Please refresh the page or
          contact support.
        </Alert>
      </Box>
    );
  }

  const fromAdmin = location.pathname.startsWith('/admin');

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <Grid container component="main" sx={{ height: '100vh' }}>
      {/* Hero / Illustration side */}
      <Grid
        item
        xs={false}
        sm={4}
        md={7}
        sx={{
          backgroundImage: 'url(/assets/login-bg.jpg)',
          backgroundRepeat: 'no-repeat',
          backgroundSize: 'cover',
          backgroundPosition: 'center'
        }}
      />

      {/* Form side */}
      <Grid item xs={12} sm={8} md={5} component={Paper} square elevation={6}>
        <Box
          sx={{
            my: 8,
            mx: 4,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center'
          }}
        >
          <Avatar sx={{ m: 1, bgcolor: 'secondary.main' }}>
            <LockOutlinedIcon />
          </Avatar>

          <Typography component="h1" variant="h5">
            {fromAdmin ? 'Admin sign in' : 'Sign in'}
          </Typography>

          {/* Global page-level error */}
          {serverError && (
            <Alert severity="error" sx={{ width: '100%', mt: 2 }}>
              {serverError}
            </Alert>
          )}

          {/* Password authentication form */}
          <Box
            component="form"
            noValidate
            onSubmit={handleSubmit(onSubmit)}
            sx={{ mt: 1, width: '100%' }}
          >
            {/* E-mail field --------------------------------------------------- */}
            <Controller
              name="email"
              control={control}
              render={({ field, fieldState }) => (
                <TextField
                  {...field}
                  fullWidth
                  label="E-mail address"
                  autoComplete="email"
                  margin="normal"
                  error={Boolean(fieldState.error)}
                  helperText={fieldState.error?.message}
                  autoFocus
                />
              )}
            />

            {/* Password field ------------------------------------------------- */}
            <Controller
              name="password"
              control={control}
              render={({ field, fieldState }) => (
                <TextField
                  {...field}
                  fullWidth
                  label="Password"
                  type="password"
                  margin="normal"
                  autoComplete="current-password"
                  error={Boolean(fieldState.error)}
                  helperText={fieldState.error?.message}
                />
              )}
            />

            {/* Remember me ---------------------------------------------------- */}
            <Controller
              name="remember"
              control={control}
              render={({ field }) => (
                <FormControlLabel
                  control={<Checkbox color="primary" {...field} checked={field.value} />}
                  label="Remember me"
                />
              )}
            />

            {/* Submit button --------------------------------------------------- */}
            <Button
              type="submit"
              fullWidth
              variant="contained"
              color="primary"
              disabled={isSubmitting}
              sx={{ mt: 3, mb: 2 }}
              startIcon={isSubmitting ? <CircularProgress size={20} /> : null}
            >
              {isSubmitting ? 'Signing in…' : 'Sign in'}
            </Button>

            {/* Links ----------------------------------------------------------- */}
            <Grid container>
              <Grid item xs>
                <Link href="/forgot-password" variant="body2">
                  Forgot password?
                </Link>
              </Grid>
              {!fromAdmin && (
                <Grid item>
                  <Link href="/register" variant="body2">
                    {"Don't have an account? Sign up"}
                  </Link>
                </Grid>
              )}
            </Grid>
          </Box>

          {/* Divider ---------------------------------------------------------- */}
          <Box
            sx={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              mt: 4,
              mb: 2
            }}
          >
            <Box sx={{ flexGrow: 1, height: 1, backgroundColor: 'divider' }} />
            <Typography variant="caption" sx={{ mx: 1 }}>
              OR
            </Typography>
            <Box sx={{ flexGrow: 1, height: 1, backgroundColor: 'divider' }} />
          </Box>

          {/* Social authentication buttons ----------------------------------- */}
          <Grid container spacing={2}>
            <Grid item xs={12} sm={6}>
              <Button
                variant="outlined"
                fullWidth
                startIcon={<GoogleIcon />}
                onClick={handleGoogleLogin}
              >
                Google
              </Button>
            </Grid>

            <Grid item xs={12} sm={6}>
              <Button
                variant="outlined"
                fullWidth
                startIcon={<SsoIcon />}
                onClick={handleSsoLogin}
              >
                Campus SSO
              </Button>
            </Grid>
          </Grid>
        </Box>
      </Grid>
    </Grid>
  );
}

export default React.memo(LoginPage);
```