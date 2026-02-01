```javascript
/**
 * PulseLearn Campus Hub
 * Component: LecturePlayer
 *
 * A production-ready, fully-featured lecture/video player that tracks
 * learner progress in real-time, reports domain events to the event bus,
 * persists checkpoints to the REST API, and provides an accessible custom
 * UI built on top of ReactPlayer + Material-UI.
 *
 * Author: PulseLearn FE Guild
 */

import React, {
  useCallback,
  useEffect,
  useRef,
  useState,
  Fragment,
} from 'react';
import PropTypes from 'prop-types';
import ReactPlayer from 'react-player';
import screenfull from 'screenfull';
import throttle from 'lodash.throttle';

// ────────────────────────────────────────────────────────────────────────────────
// UI
// ────────────────────────────────────────────────────────────────────────────────
import {
  Box,
  IconButton,
  LinearProgress,
  Tooltip,
  Typography,
  Stack,
} from '@mui/material';
import {
  PlayArrow,
  Pause,
  VolumeUp,
  VolumeOff,
  Fullscreen,
  FullscreenExit,
  ErrorOutline,
} from '@mui/icons-material';

// ────────────────────────────────────────────────────────────────────────────────
// Services
// ────────────────────────────────────────────────────────────────────────────────
import api from '../../services/api'; // Axios wrapper w/ auth interceptor
import eventBus from '../../services/eventBus'; // NATS/Kafka bridge abstraction

// ────────────────────────────────────────────────────────────────────────────────
// Constants
// ────────────────────────────────────────────────────────────────────────────────
const SAVE_INTERVAL_MS = 5_000; // Persist progress every 5 seconds
const SEEK_EPSILON = 1; // When comparing times, treat +/- 1 second as equal

// ────────────────────────────────────────────────────────────────────────────────
// Helpers
// ────────────────────────────────────────────────────────────────────────────────
/**
 * Round a floating-point time (in seconds) to one decimal for storage.
 */
const roundTime = (t) => Math.round(t * 10) / 10;

/**
 * Returns true if two floating-point times are "close enough".
 */
const isNearlyEqual = (a, b, epsilon = SEEK_EPSILON) => Math.abs(a - b) < epsilon;

/**
 * A hook that returns a function throttled to a given interval.
 */
const useThrottledCallback = (callback, delay) =>
  useCallback(throttle(callback, delay, { leading: false, trailing: true }), [
    callback,
    delay,
  ]);

// ────────────────────────────────────────────────────────────────────────────────
// LecturePlayer
// ────────────────────────────────────────────────────────────────────────────────
const LecturePlayer = ({
  courseId,
  lectureId,
  src,
  poster,
  captionSrc,
  startAt = 0,
  autoPlay = false,
}) => {
  // ──────────────────────────────────────────────────────────────────────────
  // Refs / State
  // ──────────────────────────────────────────────────────────────────────────
  const playerRef = useRef(null);
  const containerRef = useRef(null);

  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(autoPlay);
  const [volume, setVolume] = useState(0.8);
  const [muted, setMuted] = useState(false);
  const [progress, setProgress] = useState({
    playedSeconds: 0,
    loadedSeconds: 0,
    played: 0,
  });
  const [buffering, setBuffering] = useState(false);
  const [error, setError] = useState(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // ──────────────────────────────────────────────────────────────────────────
  // Domain Event Dispatchers
  // ──────────────────────────────────────────────────────────────────────────
  const emitEvent = useCallback(
    (type, payload = {}) => {
      eventBus.publish(type, {
        courseId,
        lectureId,
        timestamp: Date.now(),
        ...payload,
      });
    },
    [courseId, lectureId],
  );

  // ──────────────────────────────────────────────────────────────────────────
  // API Calls
  // ──────────────────────────────────────────────────────────────────────────
  const saveProgress = useCallback(
    async (seconds) => {
      try {
        await api.put(
          `/courses/${courseId}/lectures/${lectureId}/progress`,
          { seconds: roundTime(seconds) },
        );
      } catch (e) {
        /* Non-blocking: log and continue */
        // eslint-disable-next-line no-console
        console.error('Failed to save progress', e);
      }
    },
    [courseId, lectureId],
  );

  const throttledSaveProgress = useThrottledCallback(saveProgress, SAVE_INTERVAL_MS);

  // ──────────────────────────────────────────────────────────────────────────
  // Player Event Handlers
  // ──────────────────────────────────────────────────────────────────────────
  const handleReady = () => {
    setReady(true);
    /* Seek to previous checkpoint (if any) */
    if (!isNearlyEqual(startAt, 0)) {
      playerRef.current?.seekTo(startAt, 'seconds');
    }

    emitEvent('LecturePlayerReady');
  };

  const handlePlayPause = () => {
    setPlaying((p) => {
      const next = !p;
      emitEvent(next ? 'LectureResumed' : 'LecturePaused', {
        at: roundTime(progress.playedSeconds),
      });
      return next;
    });
  };

  const handleVolume = () => setMuted((m) => !m);

  const handleProgress = (state) => {
    setProgress(state);
    throttledSaveProgress(state.playedSeconds);
  };

  const handleBuffer = () => setBuffering(true);
  const handleBufferEnd = () => setBuffering(false);

  const handleEnded = async () => {
    setPlaying(false);
    emitEvent('LectureCompleted', { duration: roundTime(progress.playedSeconds) });
    try {
      await api.post(`/courses/${courseId}/lectures/${lectureId}/complete`);
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error('Failed marking lecture complete', e);
    }
  };

  const handleError = (e) => {
    setError(e?.message || 'Unknown error');
    emitEvent('LecturePlaybackError', { message: e?.message });
  };

  // ──────────────────────────────────────────────────────────────────────────
  // Fullscreen
  // ──────────────────────────────────────────────────────────────────────────
  const toggleFullscreen = () => {
    if (screenfull.isEnabled && containerRef.current) {
      screenfull.toggle(containerRef.current);
    }
  };

  useEffect(() => {
    if (!screenfull.isEnabled) return;

    const onChange = () => setIsFullscreen(screenfull.isFullscreen);
    screenfull.on('change', onChange);
    return () => screenfull.off('change', onChange);
  }, []);

  // ──────────────────────────────────────────────────────────────────────────
  // Cleanup on Unmount
  // ──────────────────────────────────────────────────────────────────────────
  useEffect(
    () => () => {
      throttledSaveProgress.cancel();
      /* On unmount, persist the latest progress synchronously */
      saveProgress(progress.playedSeconds);
      emitEvent('LecturePlayerUnmount', { at: roundTime(progress.playedSeconds) });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  // ──────────────────────────────────────────────────────────────────────────
  // Render
  // ──────────────────────────────────────────────────────────────────────────
  return (
    <Box
      ref={containerRef}
      sx={{
        position: 'relative',
        backgroundColor: 'black',
        aspectRatio: '16/9',
        width: '100%',
        borderRadius: 1,
        overflow: 'hidden',
      }}
    >
      {/* Video Layer */}
      <ReactPlayer
        ref={playerRef}
        url={src}
        light={poster}
        playing={playing}
        controls={false} // Custom controls
        width="100%"
        height="100%"
        muted={muted}
        volume={volume}
        onReady={handleReady}
        onPlay={() => emitEvent('LecturePlayed')}
        onPause={() => emitEvent('LecturePaused')}
        onError={handleError}
        onProgress={handleProgress}
        onBuffer={handleBuffer}
        onBufferEnd={handleBufferEnd}
        onEnded={handleEnded}
        config={{
          file: {
            attributes: {
              crossOrigin: 'anonymous',
              poster,
            },
            tracks: captionSrc
              ? [
                  {
                    kind: 'subtitles',
                    src: captionSrc,
                    srcLang: 'en',
                    default: true,
                  },
                ]
              : [],
          },
        }}
      />

      {/* Buffering indicator */}
      {buffering && (
        <Box
          sx={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: '100%',
          }}
        >
          <LinearProgress color="secondary" />
        </Box>
      )}

      {/* Error overlay */}
      {error && (
        <Stack
          spacing={1}
          alignItems="center"
          justifyContent="center"
          sx={{
            position: 'absolute',
            inset: 0,
            backdropFilter: 'blur(3px)',
            color: 'common.white',
            textAlign: 'center',
          }}
        >
          <ErrorOutline fontSize="large" />
          <Typography variant="h6">Playback error</Typography>
          <Typography variant="body2">{error}</Typography>
        </Stack>
      )}

      {/* Control Bar */}
      <Stack
        direction="row"
        alignItems="center"
        sx={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          width: '100%',
          bgcolor: 'rgba(0, 0, 0, 0.6)',
          px: 1,
          py: 0.5,
        }}
      >
        {/* Play / Pause */}
        <Tooltip title={playing ? 'Pause' : 'Play'}>
          <IconButton color="inherit" onClick={handlePlayPause} size="large">
            {playing ? <Pause /> : <PlayArrow />}
          </IconButton>
        </Tooltip>

        {/* Volume */}
        <Tooltip title={muted ? 'Unmute' : 'Mute'}>
          <IconButton color="inherit" onClick={handleVolume} size="large">
            {muted ? <VolumeOff /> : <VolumeUp />}
          </IconButton>
        </Tooltip>

        {/* Progress Bar */}
        <Box sx={{ flexGrow: 1, mx: 2 }}>
          <LinearProgress
            variant="determinate"
            value={progress.played * 100}
            sx={{
              height: 6,
              borderRadius: 3,
              '& .MuiLinearProgress-bar': { transition: 'none' },
            }}
          />
        </Box>

        <Typography variant="caption" color="grey.300" sx={{ minWidth: 70 }}>
          {formatTimestamp(progress.playedSeconds)}
        </Typography>

        {/* Fullscreen */}
        {screenfull.isEnabled && (
          <Tooltip title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}>
            <IconButton color="inherit" onClick={toggleFullscreen} size="large">
              {isFullscreen ? <FullscreenExit /> : <Fullscreen />}
            </IconButton>
          </Tooltip>
        )}
      </Stack>
    </Box>
  );
};

// ────────────────────────────────────────────────────────────────────────────────
// Utils
// ────────────────────────────────────────────────────────────────────────────────
/**
 * Format seconds -> HH:MM:SS string
 */
export const formatTimestamp = (seconds) => {
  const s = Math.floor(seconds % 60)
    .toString()
    .padStart(2, '0');
  const m = Math.floor((seconds / 60) % 60)
    .toString()
    .padStart(2, '0');
  const h = Math.floor(seconds / 3600)
    .toString()
    .padStart(2, '0');
  return h > 0 ? `${h}:${m}:${s}` : `${m}:${s}`;
};

// ────────────────────────────────────────────────────────────────────────────────
// PropTypes
// ────────────────────────────────────────────────────────────────────────────────
LecturePlayer.propTypes = {
  courseId: PropTypes.string.isRequired,
  lectureId: PropTypes.string.isRequired,
  src: PropTypes.string.isRequired,
  poster: PropTypes.string,
  captionSrc: PropTypes.string,
  startAt: PropTypes.number,
  autoPlay: PropTypes.bool,
};

export default LecturePlayer;
```