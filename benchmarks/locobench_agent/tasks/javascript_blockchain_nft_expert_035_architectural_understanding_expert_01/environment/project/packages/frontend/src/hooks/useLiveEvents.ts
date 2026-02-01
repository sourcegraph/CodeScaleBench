```typescript
/*  StellarStage Carnival — useLiveEvents Hook
    ------------------------------------------
    Provides a unified stream of real-time show events sourced from:
      • GraphQL subscriptions (primary, ordered, guaranteed delivery)
      • WebSocket fallback (low-latency, fire-and-forget)
    
    Consumers receive an array of LiveEvents as well as a convenience
    callback (onEvent) that fires for every UNIQUE event.

    The hook internally deduplicates events across heterogeneous sources,
    supports auto-reconnect, and guarantees stable reference identity for
    the returned array (React rendering optimisation).

    Author: StellarStage Front-End Guild
*/

import { useEffect, useRef, useState, useCallback } from 'react';
import { useSubscription, ApolloError } from '@apollo/client';
import { io, Socket } from 'socket.io-client';
import gql from 'graphql-tag';
import { v4 as uuidv4 } from 'uuid';

/* -----------------------------------------------------------------------
 * Types
 * -------------------------------------------------------------------- */

export type LiveEventType =
  | 'SHOW_START'
  | 'SHOW_END'
  | 'ACT_CHANGE'
  | 'LOOT_DROP'
  | 'VOTE_OPEN'
  | 'VOTE_RESULT'
  | 'MISC';

export interface LiveEvent<TPayload = Record<string, unknown>> {
  id: string;
  type: LiveEventType;
  timestamp: number; // epoch ms
  payload: TPayload;
}

/* -----------------------------------------------------------------------
 * GraphQL: Live event subscription
 * -------------------------------------------------------------------- */

const LIVE_EVENT_SUBSCRIPTION = gql`
  subscription LiveEvent($showId: ID!) {
    liveEvent(showId: $showId) {
      id
      type
      timestamp
      payload
    }
  }
`;

/* -----------------------------------------------------------------------
 * Hook signature
 * -------------------------------------------------------------------- */

export interface UseLiveEventsParams {
  showId: string;
  /**
   * Optional side-effect for every NEW event (deduped).
   */
  onEvent?: (event: LiveEvent) => void;
  /**
   * If false, the hook will not establish any connection.
   * Useful when the component is hidden / out of focus.
   */
  enabled?: boolean;
  /**
   * Milliseconds for which event IDs should be remembered to avoid
   * duplicates. 0 disables deduplication window trimming.
   */
  dedupInterval?: number;
}

export interface UseLiveEventsReturn {
  events: LiveEvent[];
  loading: boolean;
  error: Error | null;
}

/* -----------------------------------------------------------------------
 * Implementation
 * -------------------------------------------------------------------- */

export const useLiveEvents = ({
  showId,
  onEvent,
  enabled = true,
  dedupInterval = 10 * 60 * 1000, // default 10 min sliding window
}: UseLiveEventsParams): UseLiveEventsReturn => {
  /* ---------------------- State & refs ------------------------------- */
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [socketError, setSocketError] = useState<Error | null>(null);
  const seenIdsRef = useRef<Map<string, number>>(new Map());
  const socketRef = useRef<Socket | null>(null);

  /* ---------------------- GraphQL Layer ------------------------------ */
  const {
    data: gqlData,
    error: gqlError,
    loading: gqlLoading,
  } = useSubscription<{ liveEvent: LiveEvent }>(LIVE_EVENT_SUBSCRIPTION, {
    variables: { showId },
    skip: !enabled,
  });

  /* ---------------------- Deduplication ------------------------------ */
  const rememberEvent = useCallback(
    (evt: LiveEvent): boolean => {
      const now = Date.now();
      const { id } = evt;

      // Trim old entries to avoid unbounded memory growth.
      if (dedupInterval > 0) {
        seenIdsRef.current.forEach((ts, key) => {
          if (now - ts > dedupInterval) {
            seenIdsRef.current.delete(key);
          }
        });
      }

      if (seenIdsRef.current.has(id)) return false;
      seenIdsRef.current.set(id, now);
      return true;
    },
    [dedupInterval],
  );

  /* ---------------------- Merge helper ------------------------------- */
  const pushEvent = useCallback(
    (evt: LiveEvent) => {
      if (!rememberEvent(evt)) return;

      setEvents((prev) => {
        // Keep events sorted by timestamp ascending.
        const merged = [...prev, evt].sort((a, b) => a.timestamp - b.timestamp);
        return merged;
      });

      // Fire side-effect.
      onEvent?.(evt);
    },
    [rememberEvent, onEvent],
  );

  /* ---------------------- GraphQL -> state --------------------------- */
  useEffect(() => {
    if (gqlData?.liveEvent) {
      pushEvent(gqlData.liveEvent);
    }
  }, [gqlData, pushEvent]);

  /* ---------------------- WebSocket Layer ---------------------------- */
  useEffect(() => {
    if (!enabled) return;

    // Lazily initialise socket.
    const socket: Socket = io(
      process.env.NEXT_PUBLIC_LIVE_SOCKET_URL ?? '',
      {
        transports: ['websocket'],
        auth: { showId },
        reconnectionAttempts: 5,
        autoConnect: true,
      },
    );

    socketRef.current = socket;

    const handleSocketEvent = (raw: unknown) => {
      try {
        const evt: LiveEvent = normalizeSocketPayload(raw);
        pushEvent(evt);
      } catch (e) {
        // eslint-disable-next-line no-console
        console.warn('Failed to parse socket event', e);
      }
    };

    const handleError = (err: Error) => {
      setSocketError(err);
    };

    socket.on('connect_error', handleError);
    socket.on('live-event', handleSocketEvent);

    return () => {
      socket.off('connect_error', handleError);
      socket.off('live-event', handleSocketEvent);
      socket.disconnect();
      socketRef.current = null;
    };
  }, [showId, enabled, pushEvent]);

  /* ---------------------- Public return ------------------------------ */
  const error: Error | null =
    gqlError ?? socketError ?? null;

  return {
    events,
    loading: gqlLoading && events.length === 0,
    error,
  };
};

/* -----------------------------------------------------------------------
 * Helpers
 * -------------------------------------------------------------------- */

/**
 * Normalises raw data from WebSocket into LiveEvent shape.
 * Performs light validation and assigns fallback defaults.
 */
function normalizeSocketPayload(raw: any): LiveEvent {
  if (!raw || typeof raw !== 'object') {
    throw new Error('Malformed socket payload');
  }

  const id: string = typeof raw.id === 'string' ? raw.id : uuidv4();
  const type: LiveEventType =
    isValidEventType(raw.type) ? raw.type : 'MISC';
  const timestamp: number =
    typeof raw.timestamp === 'number' ? raw.timestamp : Date.now();
  const payload: Record<string, unknown> =
    raw.payload && typeof raw.payload === 'object' ? raw.payload : {};

  return { id, type, timestamp, payload };
}

function isValidEventType(value: any): value is LiveEventType {
  return (
    typeof value === 'string' &&
    [
      'SHOW_START',
      'SHOW_END',
      'ACT_CHANGE',
      'LOOT_DROP',
      'VOTE_OPEN',
      'VOTE_RESULT',
      'MISC',
    ].includes(value)
  );
}
```