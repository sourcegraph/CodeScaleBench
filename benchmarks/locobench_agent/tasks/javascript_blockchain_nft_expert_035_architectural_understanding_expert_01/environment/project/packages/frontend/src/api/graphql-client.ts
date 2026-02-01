```typescript
/* eslint-disable import/no-extraneous-dependencies */
/*  StellarStage Carnival
 *  GraphQL Client — frontend infrastructure adapter
 *
 *  This file exposes a fully-configured Apollo GraphQL client that is aware of:
 *    • Access-token management (JWT) with silent refresh & concurrency control
 *    • HTTP queries / mutations and WebSocket subscriptions (split transport)
 *    • Centralised GraphQL + Network error handling with typed error surfaces
 *
 *  The client adheres to Clean-Architecture boundaries: the domain & use-case
 *  layers talk to “ports” (interfaces).  This module is an infrastructure
 *  “adapter” that implements such a port for the React presentation layer.
 *
 *  Author:  StellarStage Carnivals FE guild
 *  ----------------------------------------------------------------------------
 */

import {
  ApolloClient,
  InMemoryCache,
  HttpLink,
  ApolloLink,
  NormalizedCacheObject,
  from,
  Observable,
} from '@apollo/client';
import { onError } from '@apollo/client/link/error';
import { getMainDefinition } from '@apollo/client/utilities';
import { GraphQLWsLink } from '@apollo/client/link/subscriptions';
import { createClient as createWSClient, ClientOptions as WSClientOptions } from 'graphql-ws';
import jwtDecode from 'jwt-decode';

/* -------------------------------------------------------------------------- */
/*                              Environment helpers                           */
/* -------------------------------------------------------------------------- */

const env = {
  GRAPHQL_HTTP_URL: import.meta.env.VITE_GRAPHQL_HTTP_URL as string,
  GRAPHQL_WS_URL: import.meta.env.VITE_GRAPHQL_WS_URL as string,
  REFRESH_URL: import.meta.env.VITE_AUTH_REFRESH_URL as string, // REST endpoint
  TOKEN_STORAGE_KEY: 'stellarstage:accessToken',
} as const;

/* -------------------------------------------------------------------------- */
/*                          Access-token persistence                          */
/* -------------------------------------------------------------------------- */

interface JwtPayload {
  /** Unix timestamp (seconds)  */
  exp: number;
  /** e.g. wallet address or user id */
  sub: string;
  /** Additional scopes */
  [key: string]: unknown;
}

let inFlightRefresh: Promise<string | null> | null = null;

const storage = window.localStorage;

/**
 * Reads the current JWT from storage.
 */
export function getAccessToken(): string | null {
  return storage.getItem(env.TOKEN_STORAGE_KEY);
}

/**
 * Saves/clears the JWT in storage.
 */
export function setAccessToken(token: string | null): void {
  if (token) {
    storage.setItem(env.TOKEN_STORAGE_KEY, token);
  } else {
    storage.removeItem(env.TOKEN_STORAGE_KEY);
  }
}

/**
 * Checks if a JWT is expired (with 30s of leeway).
 */
function isTokenExpired(token?: string | null): boolean {
  if (!token) return true;

  try {
    const { exp } = jwtDecode<JwtPayload>(token);
    const now = Date.now() / 1000;
    // 30 seconds of clock skew tolerance
    return exp < now + 30;
  } catch {
    // Malformed token -> treat as expired
    return true;
  }
}

/**
 * Requests a new pair of tokens using the refresh token cookie.
 * The backend is expected to set HttpOnly `refresh_token` cookie;
 * The access token is returned in JSON.
 */
async function fetchNewAccessToken(): Promise<string | null> {
  const controller = new AbortController();

  try {
    const res = await fetch(env.REFRESH_URL, {
      method: 'POST',
      credentials: 'include',
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!res.ok) {
      console.error('[auth] Failed to refresh token', res.status);
      return null;
    }

    const { accessToken } = (await res.json()) as { accessToken: string };
    setAccessToken(accessToken);
    return accessToken;
  } catch (err) {
    if ((err as Error).name !== 'AbortError') {
      console.error('[auth] Token refresh network error', err);
    }
    return null;
  }
}

/**
 * Ensures that only one refresh request is made at a time.
 */
function requestAccessToken(): Promise<string | null> {
  if (!inFlightRefresh) {
    inFlightRefresh = fetchNewAccessToken().finally(() => {
      inFlightRefresh = null;
    });
  }
  return inFlightRefresh;
}

/* -------------------------------------------------------------------------- */
/*                              Apollo Link chain                             */
/* -------------------------------------------------------------------------- */

/**
 * 1. tokenRefreshLink:
 *    – If the token is (close to) expired, block the request chain, refresh the
 *      token first, then continue.
 */
const tokenRefreshLink = new ApolloLink((operation, forward) => {
  return new Observable((observer) => {
    (async () => {
      const token = getAccessToken();

      if (isTokenExpired(token)) {
        const newToken = await requestAccessToken();
        if (newToken === null) {
          // Unable to refresh — propagate an error for upper layers to handle
          observer.error(new Error('UNAUTHENTICATED'));
          return;
        }
      }

      // Continue with (possibly refreshed) token
      forward(operation).subscribe({
        next: (value) => observer.next(value),
        error: (err) => observer.error(err),
        complete: () => observer.complete(),
      });
    })().catch(observer.error);
  });
});

/**
 * 2. authLink:
 *    – Append Authorization header to every HTTP / WS operation.
 */
const authLink = new ApolloLink((operation, forward) => {
  const token = getAccessToken();

  operation.setContext(({ headers = {} }) => ({
    headers: {
      ...headers,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  }));

  return forward(operation);
});

/**
 * 3. errorLink:
 *    – Surface network & GraphQL errors in a unified format.
 */
const errorLink = onError(({ graphQLErrors, networkError, operation }) => {
  if (graphQLErrors?.length) {
    graphQLErrors.forEach((e) => {
      console.error(
        `[GraphQL error @${operation.operationName}]`,
        e.message,
        e.locations,
        e.path,
      );
      // Example: capture in Sentry
      // Sentry.captureException(e);
    });
  }
  if (networkError) {
    console.error('[Network error]', networkError);
    // Optionally notify user through toasts
  }
});

/**
 * 4. httpLink:
 *    – Standard HTTP transport for queries/mutations.
 */
const httpLink = new HttpLink({
  uri: env.GRAPHQL_HTTP_URL,
  credentials: 'include',
});

/**
 * 5. wsLink:
 *    – graphql-ws transport for subscriptions.
 */
const wsClientOptions: WSClientOptions = {
  url: env.GRAPHQL_WS_URL,
  connectionParams: () => {
    const token = getAccessToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  },
  lazy: true, // Connect only when first subscription is made
  keepAlive: 15_000,
};

const wsLink = new GraphQLWsLink(createWSClient(wsClientOptions));

/**
 * splitLink:
 * – Routes subscription operations to WebSocket, others to HTTP.
 */
const splitLink = ApolloLink.split(
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

/* -------------------------------------------------------------------------- */
/*                              InMemory cache                                */
/* -------------------------------------------------------------------------- */

const cache = new InMemoryCache({
  typePolicies: {
    Query: {
      fields: {
        // Example of relay-style pagination policy for `shows` list
        shows: {
          keyArgs: false,
          merge(existing = [], incoming: any[]) {
            return [...existing, ...incoming];
          },
        },
      },
    },
  },
});

/* -------------------------------------------------------------------------- */
/*                             ApolloClient factory                           */
/* -------------------------------------------------------------------------- */

let apolloClient: ApolloClient<NormalizedCacheObject> | null = null;

/**
 * Creates (or returns) the singleton ApolloClient instance.
 *
 * NOTE: The client must be created lazily to allow unit-tests to stub globals
 * such as window.localStorage before importing this module.
 */
export function getApolloClient(): ApolloClient<NormalizedCacheObject> {
  if (apolloClient) return apolloClient;

  apolloClient = new ApolloClient({
    link: from([tokenRefreshLink, authLink, errorLink, splitLink]),
    cache,
    connectToDevTools: import.meta.env.DEV,
    defaultOptions: {
      watchQuery: {
        errorPolicy: 'all',
      },
      query: {
        errorPolicy: 'all',
      },
      mutate: {
        errorPolicy: 'all',
      },
    },
  });

  return apolloClient;
}

/* -------------------------------------------------------------------------- */
/*                                Helper hooks                                */
/* -------------------------------------------------------------------------- */

export function logout(): void {
  // Clear token + Apollo cache; let calling UI redirect user.
  setAccessToken(null);
  if (apolloClient) void apolloClient.clearStore();
}

/**
 * Utility to force a refresh of the in-memory token and re-open WS connection.
 * Call after login / token refresh mutations when access token changes.
 */
export function rehydrateAuth(newToken: string): void {
  setAccessToken(newToken);
  if (apolloClient) {
    // Restart websocket connection to pass new auth header
    (wsLink as any)?.client?.dispose?.();
    // Refresh queries
    void apolloClient.refetchQueries({ include: 'active' });
  }
}

/* -------------------------------------------------------------------------- */
/*                                Example SDK                                 */
/* -------------------------------------------------------------------------- */
/*
  NOTE: In production we usually generate a typed SDK with GraphQL Code
        Generator.  Below is a handcrafted example to illustrate how domain
        use-cases call the adapter while keeping the domain layer pure.
*/

/**
 * showById query
 */
export async function fetchShowById(id: string) {
  const client = getApolloClient();

  const QUERY = /* GraphQL */ `
    query ShowById($id: ID!) {
      show(id: $id) {
        id
        title
        startsAt
        acts {
          id
          title
          performer {
            id
            displayName
          }
        }
      }
    }
  `;

  type Response = {
    show: {
      id: string;
      title: string;
      startsAt: string;
      acts: {
        id: string;
        title: string;
        performer: { id: string; displayName: string };
      }[];
    } | null;
  };

  const { data, errors } = await client.query<Response>({
    query: gql(QUERY),
    variables: { id },
  });

  if (errors?.length) {
    throw errors[0];
  }

  return data.show;
}

/* -------------------------------------------------------------------------- */
/*                              Module re-exports                             */
/* -------------------------------------------------------------------------- */

export type { JwtPayload };
```