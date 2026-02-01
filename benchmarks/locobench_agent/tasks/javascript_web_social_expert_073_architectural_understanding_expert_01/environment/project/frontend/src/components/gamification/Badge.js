```javascript
/**
 * PulseLearn Campus Hub – Badge component
 *
 * Displays a gamification badge with real-time progress updates pushed through the
 * platform’s event bus.  A badge can be “locked”, “in-progress”, or “earned”.
 *
 * Key features:
 *  • Retrieves badge meta-data from REST API (`/api/v1/badges/:id`)
 *  • Subscribes to `BadgeProgressed` / `BadgeAwarded` events via socket.io
 *  • Shows progress ring until badge is earned
 *  • Accessible tooltip w/ name, description, and progress
 *
 * NOTE: Socket connection is intentionally kept lightweight (singleton) to avoid
 *       opening multiple WebSocket connections when many Badge instances mount.
 */

import React, { useEffect, useState, useCallback, memo } from 'react';
import PropTypes from 'prop-types';
import clsx from 'clsx';
import {
  Avatar,
  CircularProgress,
  Tooltip,
  makeStyles,
} from '@material-ui/core';
import EmojiEventsIcon from '@material-ui/icons/EmojiEvents';
import LockIcon from '@material-ui/icons/Lock';
import io from 'socket.io-client';

// ---------------------------
//  Config & util
// ---------------------------
/**
 * Singleton socket.io client – avoids redundant connections across components.
 * In production this URL would be provided by config/env vars.
 */
let SOCKET;
const getSocket = () => {
  if (!SOCKET) {
    SOCKET = io(process.env.REACT_APP_EVENT_BUS_URL || '/', {
      path: '/events',
      transports: ['websocket'],
    });
  }
  return SOCKET;
};

// Badge progress helper
const clamp = (num, min, max) => Math.min(Math.max(num, min), max);

// ---------------------------
//  Styles
// ---------------------------
const useStyles = makeStyles((theme) => ({
  root: {
    position: 'relative',
    display: 'inline-flex',
  },
  progressRing: {
    position: 'absolute',
    top: 0,
    left: 0,
    zIndex: 1,
  },
  avatar: {
    width: ({ size }) => size,
    height: ({ size }) => size,
    backgroundColor: theme.palette.grey[100],
    color: theme.palette.text.secondary,
    fontSize: ({ size }) => size * 0.55,
    border: ({ earned }) =>
      earned ? `2px solid ${theme.palette.warning.main}` : 'none',
  },
  locked: {
    backgroundColor: theme.palette.action.disabledBackground,
  },
}));

// ---------------------------
//  Hook: useBadgeProgress
// ---------------------------
/**
 * Fetches badge meta-data & listens for live progress updates.
 *
 * @param {string} badgeId   – Badge identifier
 * @param {string} userId    – Current logged-in user
 * @returns {{
 *   badge:   object|null,
 *   progress:number,        // 0-100
 *   earned:  boolean,
 *   loading: boolean,
 *   error:   Error|null
 * }}
 */
const useBadgeProgress = (badgeId, userId) => {
  const [badge, setBadge]       = useState(null);
  const [progress, setProgress] = useState(0);
  const [earned, setEarned]     = useState(false);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);

  // Fetch initial badge state
  useEffect(() => {
    if (!badgeId) return;

    const controller = new AbortController();
    const fetchBadge = async () => {
      try {
        setLoading(true);
        const res = await fetch(`/api/v1/badges/${badgeId}`, {
          signal: controller.signal,
          headers: { 'X-User-Id': userId },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        setBadge(data.metadata);
        setProgress(clamp(data.progress || 0, 0, 100));
        setEarned(Boolean(data.earned));
      } catch (err) {
        if (err.name !== 'AbortError') setError(err);
      } finally {
        setLoading(false);
      }
    };

    fetchBadge();
    return () => controller.abort();
  }, [badgeId, userId]);

  // Real-time updates
  useEffect(() => {
    const socket = getSocket();
    const handleProgress = ({ badgeId: id, progress: prg, earned: erd, userId: uid }) => {
      if (id !== badgeId || uid !== userId) return;
      setProgress(clamp(prg, 0, 100));
      setEarned(Boolean(erd));
    };

    socket.on('BadgeProgressed', handleProgress);
    socket.on('BadgeAwarded', handleProgress);

    return () => {
      socket.off('BadgeProgressed', handleProgress);
      socket.off('BadgeAwarded', handleProgress);
    };
  }, [badgeId, userId]);

  return { badge, progress, earned, loading, error };
};

// ---------------------------
//  Component: Badge
// ---------------------------
const Badge = ({
  badgeId,
  size = 64,
  userId,
  hideLabel = false,
  className,
  style,
}) => {
  const { badge, progress, earned, loading, error } = useBadgeProgress(
    badgeId,
    userId,
  );
  const classes = useStyles({ size, earned });
  const percent  = progress || 0;

  // Fallbacks
  const iconSrc = badge?.iconUrl ?? null;
  const name    = badge?.name    ?? 'Loading...';
  const desc    = badge?.description ?? '';

  const renderAvatarContent = useCallback(() => {
    if (loading || error) return <CircularProgress size={size * 0.5} />;
    if (!earned && percent < 100) return <LockIcon fontSize="inherit" />;
    if (iconSrc) return <img src={iconSrc} alt={name} width="100%" />;
    return <EmojiEventsIcon fontSize="inherit" />;
  }, [loading, error, earned, percent, iconSrc, size, name]);

  return (
    <Tooltip
      title={
        <div style={{ padding: 4 }}>
          <strong>{name}</strong>
          {!hideLabel && <div>{desc}</div>}
          {!earned && !loading && (
            <small>
              Progress: {percent.toFixed(0)}%
              {error && ` – Error: ${error.message}`}
            </small>
          )}
        </div>
      }
      arrow
      placement="top"
    >
      <div className={clsx(classes.root, className)} style={style}>
        {!earned && !loading && (
          <CircularProgress
            variant="determinate"
            value={percent}
            size={size + 8} // Slightly larger than avatar
            className={classes.progressRing}
            thickness={4}
          />
        )}

        <Avatar
          className={clsx(
            classes.avatar,
            {
              [classes.locked]: !earned && percent === 0,
            },
          )}
        >
          {renderAvatarContent()}
        </Avatar>
      </div>
    </Tooltip>
  );
};

Badge.propTypes = {
  /** Badge identifier (required) */
  badgeId: PropTypes.string.isRequired,
  /** Avatar size in px */
  size: PropTypes.number,
  /** Current logged-in user id (required for event filtering) */
  userId: PropTypes.string.isRequired,
  /** Hide description text in tooltip */
  hideLabel: PropTypes.bool,
  className: PropTypes.string,
  style: PropTypes.object,
};

export default memo(Badge);
```