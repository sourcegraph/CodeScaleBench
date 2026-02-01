```javascript
/**
 * File: frontend/src/components/dashboard/ProgressChart.js
 * Description:
 *   Real-time bar chart that visualises the authenticated learner’s course-level
 *   completion percentages. The component establishes a resilient WebSocket
 *   connection to the Campus-Hub progress-stream so that updates are rendered
 *   immediately after micro-services emit AssignmentSubmitted, BadgeAwarded,
 *   or any other progress-altering events.
 *
 *   Dependencies
 *     – react                      (UI rendering)
 *     – recharts                   (charting lib)
 *     – prop-types                 (runtime prop validation)
 *
 *   The component is fully self-contained but relies on the backend exposing:
 *     wss://api.pulselearn.com/ws/progress/:userId
 *
 *   Author: PulseLearn FE Team
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LabelList,
  Cell,
} from 'recharts';

// ---------- Constants -------------------------------------------------------

/**
 * Colors are pulled from the PulseLearn design-token palette.
 * The array is cycled so that we always have a deterministic,
 * but distinct, colour per bar – regardless of the number of courses.
 */
const BAR_COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#845EC2'];

/**
 * Interval (ms) used for the initial reconnect attempt. Each subsequent
 * retry doubles this interval until maxReconnectInterval is reached.
 */
const INITIAL_RECONNECT_INTERVAL = 1_000;     // 1 second
const MAX_RECONNECT_INTERVAL = 30_000;        // 30 seconds

// ---------- Hooks -----------------------------------------------------------

/**
 * useProgressStream
 * Opens a WebSocket to the backend for real-time learner progress.
 * Handles automatic reconnect with exponential back-off.
 *
 * @param {string} userId – currently authenticated user
 * @returns {{data: Array, loading: boolean, error: string|null}}
 */
function useProgressStream(userId) {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(Boolean(userId));
  const [error, setError] = useState(null);

  const wsRef = useRef(/** @type {WebSocket|null} */ (null));
  const reconnectIntervalRef = useRef(INITIAL_RECONNECT_INTERVAL);

  /**
   * Normalises backend events to match our chart’s expected shape.
   * @param {object} rawEvent
   * @returns {{course: string, percent: number}|null}
   */
  const mapEventToDatum = useCallback((rawEvent) => {
    if (!rawEvent || !rawEvent.payload) return null;

    const {
      payload: { courseName, completion },
    } = rawEvent;

    return {
      course: courseName,
      percent: completion,
    };
  }, []);

  useEffect(() => {
    if (!userId) {
      setLoading(false);
      return undefined;
    }

    let forcedClose = false; // true when unmounting – stops reconnect loop

    const connect = () => {
      const wsUrl = `wss://api.pulselearn.com/ws/progress/${encodeURIComponent(
        userId,
      )}`;
      const ws = new WebSocket(wsUrl);

      wsRef.current = ws;

      ws.addEventListener('open', () => {
        setLoading(false);
        setError(null);
        // Reset reconnect back-off on successful connection
        reconnectIntervalRef.current = INITIAL_RECONNECT_INTERVAL;
      });

      ws.addEventListener('message', (msg) => {
        try {
          const json = JSON.parse(msg.data);

          /**
           * Backend sends snapshot events (array) or granular events (single).
           * We accept both.
           */
          const payloadArray = Array.isArray(json) ? json : [json];
          const mapped = payloadArray
            .map(mapEventToDatum)
            .filter(Boolean)
            // Ensure we only keep the highest percent per course
            .reduce((acc, curr) => {
              const existing = acc.find((d) => d.course === curr.course);
              if (!existing || existing.percent < curr.percent) {
                return [...acc.filter((d) => d.course !== curr.course), curr];
              }
              return acc;
            }, data);

          setData(mapped);
        } catch (e) {
          // eslint-disable-next-line no-console
          console.error('Progress stream JSON parse error 🐛', e);
        }
      });

      ws.addEventListener('close', () => {
        if (forcedClose) return;

        setLoading(true);
        // escalate reconnect interval w/ exponential back-off
        const timeout = reconnectIntervalRef.current;
        reconnectIntervalRef.current = Math.min(
          reconnectIntervalRef.current * 2,
          MAX_RECONNECT_INTERVAL,
        );

        setTimeout(connect, timeout);
      });

      ws.addEventListener('error', (e) => {
        // We close WS. 'close' listener handles reconnection logic.
        ws.close();
        setError('Connection lost. Reconnecting…');
        // eslint-disable-next-line no-console
        console.error('Progress WS error', e);
      });
    };

    connect();

    // Clean up on component unmount
    return () => {
      forcedClose = true;
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.close();
      }
    };
  }, [userId, mapEventToDatum]);

  return { data, loading, error };
}

// ---------- Components ------------------------------------------------------

/**
 * ProgressChart
 *
 * @param {{
 *   userId: string,
 *   height?: number,
 *   maxCourses?: number,
 *   placeholderData?: Array<{course: string, percent: number}>
 * }} props
 */
export default function ProgressChart({
  userId,
  height = 320,
  maxCourses = 8,
  placeholderData = [],
}) {
  const { data, loading, error } = useProgressStream(userId);

  // Prefer live data; fallback to placeholder if no WS yet
  const chartData = data.length ? data : placeholderData;

  const renderContent = () => {
    if (error) {
      return (
        <div
          style={{
            padding: 16,
            color: 'var(--color-danger)',
            fontSize: 14,
            textAlign: 'center',
          }}
        >
          {error}
        </div>
      );
    }

    if (loading && !chartData.length) {
      return (
        <div
          style={{
            padding: 16,
            fontSize: 14,
            textAlign: 'center',
            opacity: 0.7,
          }}
        >
          Loading progress…
        </div>
      );
    }

    if (!chartData.length) {
      return (
        <div
          style={{
            padding: 16,
            fontSize: 14,
            textAlign: 'center',
          }}
        >
          No activity yet. 🚀
        </div>
      );
    }

    // Limit number of courses to keep chart readable
    const slicedData = chartData
      .sort((a, b) => b.percent - a.percent)
      .slice(0, maxCourses);

    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart
          data={slicedData}
          margin={{ top: 8, right: 16, left: 16, bottom: 24 }}
          barCategoryGap={20}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            strokeOpacity={0.15}
            vertical={false}
          />
          <XAxis
            dataKey="course"
            tickLine={false}
            axisLine={false}
            angle={-15}
            textAnchor="end"
            interval={0}
            height={50}
            style={{ fontSize: 12 }}
          />
          <YAxis
            tickFormatter={(v) => `${v}%`}
            axisLine={false}
            tickLine={false}
            style={{ fontSize: 12 }}
            domain={[0, 100]}
          />
          <Tooltip
            formatter={(value) => `${value}% complete`}
            cursor={{ fill: 'rgba(0,0,0,0.05)' }}
          />
          <Bar
            dataKey="percent"
            radius={[4, 4, 0, 0]}
            animationDuration={400}
            isAnimationActive={!loading}
          >
            <LabelList
              dataKey="percent"
              position="top"
              formatter={(v) => `${v}%`}
              style={{ fontSize: 12, fill: '#555' }}
            />
            {slicedData.map((_, idx) => (
              <Cell
                key={/* eslint-disable-line react/no-array-index-key */ idx}
                fill={BAR_COLORS[idx % BAR_COLORS.length]}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  };

  return (
    <section
      aria-label="Learner progress chart"
      style={{
        background: 'var(--color-surface-0)',
        borderRadius: 8,
        boxShadow: 'var(--elevation-1)',
        width: '100%',
        height,
      }}
    >
      {renderContent()}
    </section>
  );
}

ProgressChart.propTypes = {
  /**
   * Authenticated user’s identifier (required for WS endpoint).
   */
  userId: PropTypes.string.isRequired,

  /**
   * Pixel height of the chart wrapper.
   */
  height: PropTypes.number,

  /**
   * Maximum number of courses displayed at once.
   */
  maxCourses: PropTypes.number,

  /**
   * Optional placeholder data to show before WS snapshot arrives.
   */
  placeholderData: PropTypes.arrayOf(
    PropTypes.shape({
      course: PropTypes.string.isRequired,
      percent: PropTypes.number.isRequired,
    }),
  ),
};
```