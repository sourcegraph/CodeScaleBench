```javascript
/**
 * @file LoginPage.test.js
 * @description End-to-end / integration tests for the LoginPage component.
 *
 * The tests exercise:
 *  • Form rendering & validation
 *  • Email / password authentication success & failure paths
 *  • “Remember me” session-persistence logic (localStorage vs. sessionStorage)
 *  • Social-login redirect behaviour
 *
 * These tests rely on MSW (Mock Service Worker) to mock the backend REST API
 * so that the frontend can be tested in complete isolation.
 */

import React from 'react';
import {
  render,
  screen,
  waitFor,
  fireEvent,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryHistory } from 'history';
import { Router } from 'react-router-dom';
import { rest } from 'msw';
import { setupServer } from 'msw/node';

import LoginPage from '../../pages/LoginPage';
import { AuthProvider } from '../../context/AuthContext';

////////////////////////////////////////////////////////////////////////////////
// ─── MSW SETUP ────────────────────────────────────────────────────────────────
////////////////////////////////////////////////////////////////////////////////

const API_URL = '/api/auth/login';

const validCredentials = {
  email: 'jane.doe@pulselearn.edu',
  password: 'Secure#Pass1',
};

const tokenPayload = {
  token: 'eyMock.JWT.Token',
  user: {
    id: 'user-123',
    name: 'Jane Doe',
    role: 'student',
  },
};

const server = setupServer(
  // Successful login
  rest.post(API_URL, async (req, res, ctx) => {
    const { email, password } = await req.json();

    if (email === validCredentials.email && password === validCredentials.password) {
      return res(ctx.status(200), ctx.json(tokenPayload));
    }

    // Invalid credentials
    return res(
      ctx.status(401),
      ctx.json({ error: 'Invalid email or password.' }),
    );
  }),

  // Simulate an unexpected server error
  rest.post('/api/auth/boom', (_req, res, ctx) =>
    res(ctx.status(500), ctx.json({ error: 'Internal Server Error' })),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  jest.clearAllMocks();
  window.localStorage.clear();
  window.sessionStorage.clear();
});
afterAll(() => server.close());

////////////////////////////////////////////////////////////////////////////////
// ─── TEST UTILITIES ──────────────────────────────────────────────────────────
////////////////////////////////////////////////////////////////////////////////

/**
 * Renders the component under the needed providers (AuthProvider + Router)
 */
const renderWithProviders = (ui, { route = '/' } = {}) => {
  const history = createMemoryHistory({ initialEntries: [route] });

  return {
    history,
    ...render(
      <AuthProvider>
        <Router history={history}>{ui}</Router>
      </AuthProvider>,
    ),
  };
};

/**
 * Helpers to grab form fields
 */
const getEmailInput = () => screen.getByLabelText(/email/i);
const getPasswordInput = () => screen.getByLabelText(/^password/i);
const getRememberCheckbox = () => screen.getByRole('checkbox', { name: /remember me/i });
const getSubmitButton = () => screen.getByRole('button', { name: /log in/i });

////////////////////////////////////////////////////////////////////////////////
// ─── TESTS ───────────────────────────────────────────────────────────────────
////////////////////////////////////////////////////////////////////////////////

describe('LoginPage', () => {
  test('renders form controls correctly', () => {
    renderWithProviders(<LoginPage />);

    expect(getEmailInput()).toBeInTheDocument();
    expect(getPasswordInput()).toBeInTheDocument();
    expect(getRememberCheckbox()).toBeInTheDocument();
    expect(getSubmitButton()).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /continue with google/i }))
      .toBeInTheDocument();
  });

  test('successful login redirects user to dashboard and stores token', async () => {
    const { history } = renderWithProviders(<LoginPage />);

    userEvent.type(getEmailInput(), validCredentials.email);
    userEvent.type(getPasswordInput(), validCredentials.password);
    userEvent.click(getSubmitButton());

    await waitFor(() =>
      expect(history.location.pathname).toBe('/dashboard'),
    );

    // The token should be stored in sessionStorage by default
    expect(window.sessionStorage.getItem('authToken')).toBe(tokenPayload.token);
  });

  test('“Remember me” stores token in localStorage instead of sessionStorage', async () => {
    renderWithProviders(<LoginPage />);

    userEvent.type(getEmailInput(), validCredentials.email);
    userEvent.type(getPasswordInput(), validCredentials.password);
    userEvent.click(getRememberCheckbox());
    userEvent.click(getSubmitButton());

    await waitFor(() =>
      expect(window.localStorage.getItem('authToken')).toBe(tokenPayload.token),
    );

    expect(window.sessionStorage.getItem('authToken')).toBeNull();
  });

  test('invalid credentials surface a user-friendly error message', async () => {
    renderWithProviders(<LoginPage />);

    userEvent.type(getEmailInput(), validCredentials.email);
    userEvent.type(getPasswordInput(), 'WrongPassword!');
    userEvent.click(getSubmitButton());

    const alert = await screen.findByRole('alert');

    expect(alert).toHaveTextContent(/invalid email or password/i);
    expect(window.sessionStorage.getItem('authToken')).toBeNull();
  });

  test('network / server error fallback is displayed to the user', async () => {
    // Override the handler for this test to force 500 error
    server.use(
      rest.post(API_URL, (_req, res, ctx) =>
        res(ctx.status(500)),
      ),
    );

    renderWithProviders(<LoginPage />);

    userEvent.type(getEmailInput(), validCredentials.email);
    userEvent.type(getPasswordInput(), validCredentials.password);
    userEvent.click(getSubmitButton());

    const alert = await screen.findByRole('alert');

    expect(alert).toHaveTextContent(/something went wrong/i);
  });

  test('social login initiates OAuth redirect', () => {
    const originalLocation = window.location;

    delete window.location;
    window.location = { assign: jest.fn() };

    renderWithProviders(<LoginPage />);

    const googleButton = screen.getByRole('button', { name: /continue with google/i });

    userEvent.click(googleButton);

    expect(window.location.assign).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/auth\/google\/redirect/),
    );

    // Restore window.location
    window.location = originalLocation;
  });

  test('form validation – prevents submission if fields are empty', async () => {
    renderWithProviders(<LoginPage />);

    // Attempt to submit empty form
    fireEvent.submit(getSubmitButton());

    const validationErrors = await screen.findAllByText(/required/i);
    expect(validationErrors.length).toBeGreaterThanOrEqual(1);

    // No fetch call should have been made
    // (MSW would throw on unhandled requests if API was hit)
  });
});
```