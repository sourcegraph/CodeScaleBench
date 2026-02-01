```javascript
/**
 * PulseLearn Campus Hub
 * ----------------------------------------
 * useWebSocket.js
 *
 * A production-grade React hook that wraps the native WebSocket API and adds:
 *  • Automatic (exponential-back-off) reconnect
 *  • Heart-beat / ping-pong mechanism
 *  • Message queue for messages sent while the socket is not yet open
 *  • Optional authentication token and query-param support
 *  • Typed callbacks (onOpen, onClose, onMessage, onError)
 *
 * Usage example:
 * const {
 *   connected,
 *   lastMessage,
 *   send,
 *   disconnect
 * } = useWebSocket('/events', {
 *     token: auth.jwt,
 *     onMessage: evt => console.log(JSON.parse(evt.data))
 * });
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { v4 as uuidv4 } from 'uuid';

// -- Constants ----------------------------------------------------------------

const DEFAULT_HEARTBEAT_INTERVAL = 30_000;            // 30s
const DEFAULT_RECONNECT_INTERVAL = 2_000;             // 2s
const MAX_RECONNECT_INTERVAL       = 30_000;          // 30s
const READY_STATES                 = ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED'];

/**
 * Build a WebSocket URL from an endpoint.
 * Accepts absolute URLs or relative endpoints that will be resolved
 * against window.location, automatically switching the scheme (http → ws).
 */
function buildSocketUrl(endpoint, queryParams = {}, token) {
  let url;

  try {
    // Absolute URL provided by caller
    url = new URL(endpoint);
  } catch (_) {
    // Relative or path-only endpoint
    const base = new URL(window.location.origin);
    const scheme = base.protocol === 'https:' ? 'wss:' : 'ws:';
    url = new URL(endpoint, base);
    url.protocol = scheme;
  }

  const params = new URLSearchParams(queryParams);
  if (token) params.set('auth', token);
  url.search = params.toString();

  return url.toString();
}

// -- Hook ---------------------------------------------------------------------

/**
 * useWebSocket
 *
 * @param {string} endpoint                       - Endpoint or absolute URL.
 * @param {object} [options]
 * @param {string|string[]} [options.protocols]   - Subprotocol(s).
 * @param {boolean} [options.autoConnect=true]    - Connect immediately.
 * @param {object} [options.queryParams]          - Extra query string params.
 * @param {string} [options.token]                - Auth token appended as ?auth=
 * @param {number} [options.heartbeatInterval]    - ms between pings.
 * @param {string|object} [options.heartbeatMsg]  - Payload of the heartbeat.
 * @param {number} [options.reconnectAttempts]    - Max reconnect tries (∞ default).
 * @param {number} [options.reconnectInterval]    - Initial back-off delay (ms).
 * @param {Function} [options.onOpen]             - WebSocket#onopen handler.
 * @param {Function} [options.onClose]            - WebSocket#onclose handler.
 * @param {Function} [options.onError]            - WebSocket#onerror handler.
 * @param {Function} [options.onMessage]          - WebSocket#onmessage handler.
 * @param {Function} [options.filter]             - Filter incoming messages.
 */
export default function useWebSocket(
  endpoint,
  {
    protocols,
    autoConnect           = true,
    queryParams           = {},
    token                 = undefined,
    heartbeatInterval     = DEFAULT_HEARTBEAT_INTERVAL,
    heartbeatMsg          = '--heartbeat--',
    reconnectAttempts     = Infinity,
    reconnectInterval     = DEFAULT_RECONNECT_INTERVAL,
    onOpen                = () => {},
    onClose               = () => {},
    onError               = () => {},
    onMessage             = () => {},
    filter                = () => true
  } = {}
) {
  const socketRef     = useRef(null);
  const queueRef      = useRef([]);           // Outbound message queue
  const heartbeatRef  = useRef(null);
  const reconnectRef  = useRef({ count: 0, delay: reconnectInterval });

  const [readyState, setReadyState]     = useState(WebSocket.CONNECTING);
  const [lastMessage, setLastMessage]   = useState(null);

  /* -------------------------------------------------------------------------
   * Internal helpers
   * ---------------------------------------------------------------------- */

  const clearHeartbeat = () => {
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
  };

  const scheduleHeartbeat = () => {
    clearHeartbeat();
    heartbeatRef.current = setInterval(() => {
      if (socketRef.current?.readyState === WebSocket.OPEN) {
        // send heartbeat safely
        try {
          socketRef.current.send(
            typeof heartbeatMsg === 'string'
              ? heartbeatMsg
              : JSON.stringify(heartbeatMsg)
          );
        } catch (_) {
          /* ignore send errors (socket will close on its own) */
        }
      }
    }, heartbeatInterval);
  };

  /* -------------------------------------------------------------------------
   * Connection / Reconnection logic
   * ---------------------------------------------------------------------- */

  const connect = useCallback(() => {
    if (!endpoint) throw new Error('useWebSocket: endpoint is required');

    const url = buildSocketUrl(endpoint, queryParams, token);
    const ws  = new WebSocket(url, protocols);
    socketRef.current = ws;
    setReadyState(ws.readyState);

    // -- WebSocket event bindings ------------------------------------------

    ws.onopen = evt => {
      setReadyState(ws.readyState);
      reconnectRef.current = { count: 0, delay: reconnectInterval };
      scheduleHeartbeat();

      // flush queue
      queueRef.current.forEach(msg => ws.send(msg));
      queueRef.current = [];

      onOpen(evt);
    };

    ws.onmessage = evt => {
      if (typeof filter === 'function' && !filter(evt)) return;

      setLastMessage(evt);
      onMessage(evt);
    };

    ws.onerror = err => {
      onError(err);
    };

    ws.onclose = evt => {
      setReadyState(ws.readyState);
      clearHeartbeat();
      onClose(evt);

      const { count }  = reconnectRef.current;
      if (count < reconnectAttempts) {
        // Exponential back-off with full-jitter strategy
        const delay = Math.min(
          MAX_RECONNECT_INTERVAL,
          reconnectRef.current.delay * 2 ** count
        );
        const jitter = delay * Math.random();
        const wait   = Math.min(MAX_RECONNECT_INTERVAL, delay + jitter);

        reconnectRef.current = { count: count + 1, delay };

        // Reconnect after a randomised delay
        setTimeout(() => {
          connect();
        }, wait);
      }
    };
  }, [
    endpoint,
    protocols,
    queryParams,
    token,
    reconnectInterval,
    reconnectAttempts,
    onOpen,
    onClose,
    onError,
    onMessage,
    filter,
    heartbeatInterval,
    heartbeatMsg
  ]);

  const disconnect = useCallback(code => {
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      socketRef.current.close(code ?? 1000, 'Manual disconnect');
    }
  }, []);

  const send = useCallback(message => {
    const payload =
      typeof message === 'string' ? message : JSON.stringify(message);

    const ws = socketRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(payload);
    } else {
      // Queue until socket is ready
      queueRef.current.push(payload);
    }
  }, []);

  /* -------------------------------------------------------------------------
   * Life-cycle bindings
   * ---------------------------------------------------------------------- */

  useEffect(() => {
    if (autoConnect) connect();
    return () => {
      // component unmount
      clearHeartbeat();
      socketRef.current?.close(1000, 'Component unmounted');
    };
  }, [autoConnect, connect]);

  /* -----------------------------------------------------------------------
   * Public API
   * -------------------------------------------------------------------- */

  return {
    socket:        socketRef.current,
    readyState,                               // 0-3, per native API
    readyStateText: READY_STATES[readyState], // human-friendly
    connected:     readyState === WebSocket.OPEN,
    reconnecting:  readyState === WebSocket.CONNECTING && reconnectRef.current.count > 0,
    lastMessage,                              // Last MessageEvent
    send,
    connect,
    disconnect
  };
}
```