```javascript
/**
 * PulseLearn Campus Hub – ActivityStream Component
 * ------------------------------------------------
 * A real-time, infinite-scrolling activity feed that renders domain events such as
 * `LectureUploaded`, `QuizCompleted`, `BadgeAwarded`, etc.  The component hydrates
 * itself by requesting the first page of activities from the REST API, then keeps
 * the list up-to-date by subscribing to a websocket endpoint that pushes new events
 * as they occur.  Built with accessibility, performance, and resiliency in mind.
 */

import React, {
  memo,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import PropTypes from 'prop-types';
import axios from 'axios';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { toast } from 'react-toastify';
import { v4 as uuid } from 'uuid';

import useAuthToken from '../../hooks/useAuthToken'; // ← project-level custom hook
import Loader from '../shared/Loader';
import ErrorMessage from '../shared/ErrorMessage';
import ActivityIcon from './ActivityIcon';

import './ActivityStream.css';

dayjs.extend(relativeTime);

/* -------------------------------------------------------------------------- */
/* Helpers                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Throttles a function so it is executed at most once every `limit` ms.
 */
const throttle = (fn, limit = 200) => {
  let inThrottle;
  return (...args) => {
    if (!inThrottle) {
      // eslint-disable-next-line prefer-spread
      fn.apply(null, args);
      inThrottle = true;
      setTimeout(() => (inThrottle = false), limit);
    }
  };
};

/**
 * Formats a timestamp into a relative string (e.g., "3 minutes ago").
 */
const formatRelativeTime = (timestamp) => dayjs(timestamp).fromNow();

/**
 * Maps event types to human-readable strings.
 * Extend this map to support new event types.
 */
const EVENT_DESCRIPTIONS = {
  LectureUploaded: (e) => `${e.actor.name} uploaded "${e.payload.title}"`,
  QuizCompleted: (e) => `${e.actor.name} completed a quiz (${e.payload.score}%)`,
  BadgeAwarded: (e) => `${e.actor.name} earned the "${e.payload.badgeName}" badge`,
  PeerReviewGiven: (e) =>
    `${e.actor.name} reviewed ${e.payload.revieweeName}'s submission`,
  SessionExpired: (e) => `${e.actor.name}'s session expired`,
  // fallback
  default: (e) => `${e.actor.name} performed an action`,
};

const getEventDescription = (e) =>
  (EVENT_DESCRIPTIONS[e.type] || EVENT_DESCRIPTIONS.default)(e);

/* -------------------------------------------------------------------------- */
/* Component                                                                  */
/* -------------------------------------------------------------------------- */

const PAGE_SIZE = 25;
const API_BASE = '/api/v1';
const WS_BASE = process.env.REACT_APP_WS_ENDPOINT || 'wss://api.pulselearn.io/ws';

function ActivityStream({ userId }) {
  const token = useAuthToken();
  const feedRef = useRef(null);

  const [activities, setActivities] = useState([]);
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [loadingInitial, setLoadingInitial] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);

  /* --------------------------------- Fetch -------------------------------- */

  /**
   * Fetches a page of historical activity events.
   */
  const fetchPage = useCallback(
    async (pageNumber) => {
      try {
        const response = await axios.get(`${API_BASE}/activity-stream`, {
          params: {
            page: pageNumber,
            size: PAGE_SIZE,
            userId,
          },
          headers: { Authorization: `Bearer ${token}` },
          timeout: 10_000,
        });

        const { items, last } = response.data;

        setActivities((prev) =>
          // De-duplicate by id so websocket items don't double-insert
          [
            ...prev,
            ...items.filter((it) => !prev.some((p) => p.id === it.id)),
          ].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp)),
        );
        setHasMore(!last);
        setPage(pageNumber);
      } catch (err) {
        setError(
          err.response?.data?.message ||
            err.message ||
            'Failed to load activity stream.',
        );
        toast.error('Unable to load activity stream. Please try again later.');
      } finally {
        setLoadingInitial(false);
        setLoadingMore(false);
      }
    },
    [token, userId],
  );

  /* ---------------------------- Infinite Scroll --------------------------- */

  const handleScroll = useCallback(
    throttle(() => {
      if (!hasMore || loadingMore || !feedRef.current) return;

      const { scrollTop, scrollHeight, clientHeight } = feedRef.current;

      // If scrolled within 100px from bottom, load more
      if (scrollHeight - scrollTop - clientHeight < 100) {
        setLoadingMore(true);
        fetchPage(page + 1);
      }
    }, 250),
    [hasMore, loadingMore, page, fetchPage],
  );

  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.addEventListener('scroll', handleScroll);
      return () =>
        feedRef.current?.removeEventListener('scroll', handleScroll);
    }
    return undefined;
  }, [handleScroll]);

  /* ----------------------------- Websocket Sync --------------------------- */

  useEffect(() => {
    // Lazy-instantiate only when token present
    if (!token) return undefined;

    const wsUrl = `${WS_BASE}/activity?token=${token}`;
    const socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      // eslint-disable-next-line no-console
      console.debug('[ActivityStream] WebSocket connected:', wsUrl);
    };

    socket.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data);
        if (parsed?.event) {
          setActivities((prev) => {
            const alreadyExists = prev.some((a) => a.id === parsed.event.id);
            if (alreadyExists) return prev; // ignore duplicates
            return [parsed.event, ...prev];
          });
        }
      } catch (e) {
        // eslint-disable-next-line no-console
        console.warn('Failed to parse websocket message', e);
      }
    };

    socket.onerror = (e) => {
      // eslint-disable-next-line no-console
      console.error('[ActivityStream] WebSocket error', e);
      toast.error('Real-time connection lost.');
    };

    socket.onclose = (e) => {
      // eslint-disable-next-line no-console
      console.warn('[ActivityStream] WebSocket closed', e.reason);
    };

    return () => socket.close(1000, 'Component unmounted');
  }, [token]);

  /* -------------------------------- Mount --------------------------------- */

  useEffect(() => {
    fetchPage(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  /* -------------------------------- Render -------------------------------- */

  const renderItem = (activity) => (
    <li className="activity-item" key={activity.id || uuid()}>
      <ActivityIcon type={activity.type} />
      <div className="activity-body">
        <p className="activity-desc">{getEventDescription(activity)}</p>
        <time
          dateTime={activity.timestamp}
          title={dayjs(activity.timestamp).format('YYYY-MM-DD HH:mm')}
          className="activity-time"
        >
          {formatRelativeTime(activity.timestamp)}
        </time>
      </div>
    </li>
  );

  if (error) {
    return <ErrorMessage message={error} />;
  }

  return (
    <section
      aria-label="Activity Stream"
      className="activity-stream-container"
      ref={feedRef}
    >
      {loadingInitial && <Loader />}
      <ul className="activity-list">
        {activities.map((a) => renderItem(a))}
      </ul>

      {loadingMore && (
        <div className="activity-loader--more">
          <Loader size="sm" />
        </div>
      )}
      {!hasMore && !loadingInitial && (
        <p className="activity-end-of-feed">You’re all caught up 🎉</p>
      )}
    </section>
  );
}

ActivityStream.propTypes = {
  /**
   * If provided, filters the activity stream by user id (show only activities
   * related to that user). Otherwise, shows global campus-wide feed.
   */
  userId: PropTypes.string,
};

ActivityStream.defaultProps = {
  userId: null,
};

export default memo(ActivityStream);
```

