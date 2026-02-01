```markdown
# PulseLearn Campus Hub — Frontend

Real-time, event-driven campus life in your browser.  
This React + Vite micro-frontend consumes the PulseLearn event stream and REST API to deliver an interactive, **zero-latency** learning experience.

---

## Table of Contents
1. [Quick Start](#quick-start)
2. [Architecture Overview](#architecture-overview)
3. [Project Structure](#project-structure)
4. [Core Concepts & Code Samples](#core-concepts--code-samples)
   - [1. Secure API Client (Service Layer)](#1-secure-api-client-service-layer)
   - [2. WebSocket Event Bus](#2-websocket-event-bus)
   - [3. Authentication Hook](#3-authentication-hook)
   - [4. Error Boundary](#4-error-boundary)
5. [NPM Scripts](#npm-scripts)
6. [Environment Variables](#environment-variables)
7. [Coding Standards](#coding-standards)
8. [Contributing](#contributing)
9. [License](#license)

---

## Quick Start

```bash
# 1. Install dependencies
pnpm install

# 2. Copy & configure environment
cp .env.example .env.local

# 3. Run in development mode
pnpm dev

# 4. Build for production
pnpm build

# 5. Preview production build
pnpm preview
```

---

## Architecture Overview

| Layer                  | Technology                            | Responsibility                                                     |
|------------------------|---------------------------------------|--------------------------------------------------------------------|
| Presentation           | React 18, React-Router 6              | UI components, routing                                             |
| State Management       | Zustand + Immer                       | Local and per-feature stores                                       |
| Service Layer          | Axios                                 | Domain-level API calls, unified error handling                     |
| Event Backbone         | Socket.IO                             | Real-time domain events (e.g., `BadgeAwarded`, `LectureUploaded`)  |
| Auth & Session         | OpenID Connect PKCE                   | Social login + refresh-token rotation                              |
| Styling                | Tailwind CSS                          | Utility-first CSS framework                                        |
| Testing                | Vitest, @testing-library/react        | Unit and component integration tests                               |
| Static Typing          | TypeScript                            | End-to-end type safety                                             |

---

## Project Structure

```
frontend/
├── public/                # Static assets
├── src/
│   ├── api/               # Service layer & API adapters
│   ├── components/        # Reusable UI widgets
│   ├── hooks/             # Custom React hooks
│   ├── pages/             # Route-level components (React Router)
│   ├── stores/            # Zustand state slices
│   ├── styles/            # Tailwind config & global CSS
│   ├── utils/             # Shared helpers & domain utilities
│   └── main.tsx           # Application entrypoint
├── vitest.config.ts       # Unit-test configuration
└── tsconfig.json          # TypeScript compiler options
```

---

## Core Concepts & Code Samples

### 1. Secure API Client (Service Layer)

`src/api/httpClient.ts`

```ts
/**
 * A thin Axios wrapper that transparently
 *  • injects the JWT access-token
 *  • handles token refresh on 401
 *  • logs errors to Sentry
 */

import axios, { AxiosError } from 'axios';
import { getSession, refreshSession } from '@/stores/session';
import * as Sentry from '@sentry/browser';

export const httpClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 10_000,
});

httpClient.interceptors.request.use(config => {
  const { accessToken } = getSession.getState();
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

httpClient.interceptors.response.use(
  response => response,
  async (error: AxiosError) => {
    if (error.response?.status === 401) {
      // Attempt silent token refresh
      try {
        await refreshSession();
        // Repeat the original request with the new token
        return httpClient.request(error.config as any);
      } catch {
        // Bubble up if refresh fails
        window.location.href = '/login';
      }
    }
    Sentry.captureException(error);
    return Promise.reject(error);
  },
);
```

---

### 2. WebSocket Event Bus

`src/api/eventBus.ts`

```ts
import { io, Socket } from 'socket.io-client';

export interface DomainEventPayload {
  type: string;
  timestamp: number;
  data: Record<string, unknown>;
}

let socket: Socket | null = null;

export function connectEventBus() {
  if (socket) return socket; // Singleton

  socket = io(import.meta.env.VITE_EVENT_GATEWAY_URL, {
    transports: ['websocket'],
    auth: cb => cb({ token: sessionStorage.getItem('accessToken') }),
  });

  socket.on('connect_error', err => {
    console.error('🔥 WebSocket Error:', err.message);
  });

  return socket;
}

// Example subscription
export function onEvent<T = DomainEventPayload>(
  eventName: string,
  handler: (payload: T) => void,
) {
  const ws = connectEventBus();
  ws.on(eventName, handler);
  return () => ws.off(eventName, handler); // Unsubscribe
}
```

---

### 3. Authentication Hook

`src/hooks/useAuth.ts`

```ts
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSessionStore } from '@/stores/session';

/**
 * Redirect unauthenticated users to `/login`.
 * Returns the current user object when authenticated.
 */
export const useAuth = () => {
  const navigate = useNavigate();
  const { user, isAuthenticated, checkSession } = useSessionStore();

  useEffect(() => {
    if (isAuthenticated === false) navigate('/login');
    else if (isAuthenticated === null) checkSession(); // Lazy validation
  }, [isAuthenticated]);

  return { user };
};
```

---

### 4. Error Boundary

`src/components/ErrorBoundary.tsx`

```tsx
import React, { Component, ReactNode } from 'react';
import * as Sentry from '@sentry/react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  readonly state: State = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    Sentry.captureException(error, { extra: errorInfo });
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center h-screen text-center">
          <h1 className="text-3xl font-bold">Something went wrong.</h1>
          <p className="mt-2 text-gray-500">
            Our team has been notified. Try refreshing the page.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}
```

---

## NPM Scripts

| Script            | Description                                          |
|-------------------|------------------------------------------------------|
| `pnpm dev`        | Development server with hot-module reload            |
| `pnpm build`      | Production-grade, optimized build (Vite)             |
| `pnpm preview`    | Serve the production build locally                   |
| `pnpm test`       | Run unit & component tests via Vitest                |
| `pnpm lint`       | ESLint with Prettier custom rules                    |
| `pnpm typecheck`  | Run the TypeScript compiler in `--noEmit` mode       |

---

## Environment Variables

Create a `.env.local` file (git-ignored).  
Full reference in `./.env.example`.

| Variable                    | Purpose                                |
|-----------------------------|----------------------------------------|
| `VITE_API_BASE_URL`         | REST API root (e.g., `https://api.`)   |
| `VITE_EVENT_GATEWAY_URL`    | Socket.IO gateway endpoint             |
| `VITE_OIDC_ISSUER`          | OpenID Connect Issuer URL             |
| `VITE_OIDC_CLIENT_ID`       | OAuth 2.0 client ID                    |
| `VITE_OIDC_REDIRECT_URI`    | Where identity server redirects to     |
| `VITE_SENTRY_DSN`           | Sentry project DSN                     |

---

## Coding Standards

* 100 % TypeScript (no implicit `any`)
* Absolute imports (`@/components/Button`)
* ESLint + Prettier enforced by pre-commit hooks (Husky)
* Conventional Commits for commit messages
* Test-Driven where feasible (Vitest, RTL)
* Accessible-by-default components (WCAG 2.1 AA)

---

## Contributing

1. Fork -> Feature branch -> PR
2. `pnpm test && pnpm lint && pnpm typecheck` must pass
3. At least one approving review required

---

## License

`MIT © 2023–Present PulseLearn, Inc. All rights reserved.`
```