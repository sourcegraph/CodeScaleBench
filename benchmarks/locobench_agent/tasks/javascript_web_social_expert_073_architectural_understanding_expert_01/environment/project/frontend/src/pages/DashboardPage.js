```javascript
/**
 * PulseLearn Campus Hub – DashboardPage
 * --------------------------------------
 * The Dashboard presents real-time learning analytics, recent activity,
 * and gamification stats for the authenticated user. Data is delivered
 * via a REST API for the initial payload and a WebSocket channel for
 * subsequent domain-events (e.g. BadgeAwarded, AssignmentSubmitted).
 *
 * Production-quality considerations:
 *  • Graceful handling of auth/session time-outs
 *  • Clean up of async side-effects (fetch / socket)
 *  • Responsive layout with styled-components
 *  • Separation of concerns via a thin service layer
 *  • Defensive error boundaries and optimistic UI patterns
 */

import React, {
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  memo,
} from 'react';
import PropTypes from 'prop-types';
import { useNavigate } from 'react-router-dom';
import styled from 'styled-components';
import { io } from 'socket.io-client';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

import { AuthContext } from '../contexts/AuthProvider';
import DashboardService from '../services/DashboardService';
import { toast } from '../components/Toast';
import LoadingSpinner from '../components/LoadingSpinner';

// ---------- Styled Components ----------

const PageWrapper = styled.main`
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  padding: 2rem;
  height: 100%;
  box-sizing: border-box;
`;

const Section = styled.section`
  background: #ffffff;
  border-radius: 8px;
  box-shadow: ${({ theme }) => theme.shadows.medium};
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  min-height: ${({ minHeight }) => minHeight || 'auto'};
`;

const MetricsGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 1rem;
`;

const Card = styled.div`
  background: ${({ theme }) => theme.palette.primary.light};
  color: ${({ theme }) => theme.palette.primary.contrastText};
  border-radius: 6px;
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
`;

const MetricValue = styled.span`
  font-size: 2rem;
  font-weight: 600;
`;

const MetricLabel = styled.span`
  font-size: 0.9rem;
  opacity: 0.85;
`;

const ActivityList = styled.ul`
  list-style: none;
  margin: 0;
  padding: 0;
`;

const ActivityItem = styled.li`
  padding: 0.75rem 0;
  border-bottom: 1px solid ${({ theme }) => theme.palette.grey[200]};
  font-size: 0.95rem;

  &:last-child {
    border-bottom: none;
  }
`;

// ---------- Helper Components ----------

const MetricCard = memo(({ label, value }) => (
  <Card>
    <MetricValue>{value}</MetricValue>
    <MetricLabel>{label}</MetricLabel>
  </Card>
));

MetricCard.propTypes = {
  label: PropTypes.string.isRequired,
  value: PropTypes.oneOfType([PropTypes.number, PropTypes.string]).isRequired,
};

// ---------- DashboardPage ----------

const DashboardPage = () => {
  const navigate = useNavigate();
  const { token, signOut, user } = useContext(AuthContext);

  const [metrics, setMetrics] = useState(null);
  const [activityFeed, setActivityFeed] = useState([]);
  const [progressData, setProgressData] = useState([]);
  const [loading, setLoading] = useState(true);

  // Store socket instance in a ref to avoid re-connect storms
  const socketRef = useRef(null);
  const abortControllerRef = useRef(null);

  /**
   * Fetch dashboard snapshot (metrics + feed + chart data) from API
   */
  const fetchDashboardSnapshot = useCallback(async () => {
    setLoading(true);
    abortControllerRef.current = new AbortController();
    try {
      const snapshot = await DashboardService.getSnapshot({
        token,
        signal: abortControllerRef.current.signal,
      });
      setMetrics(snapshot.metrics);
      setActivityFeed(snapshot.activity);
      setProgressData(snapshot.progress);
    } catch (error) {
      if (error.name === 'AbortError') return; // request was cancelled
      handleServiceError(error);
    } finally {
      setLoading(false);
    }
  }, [token]);

  /**
   * Handle technical or business errors in a single place
   */
  const handleServiceError = useCallback(
    (error) => {
      /* eslint-disable no-console */
      console.error('[DashboardPage] Service Error:', error);
      /* eslint-enable no-console */
      if (error?.response?.status === 401) {
        toast.error('Session expired. Please sign in again.');
        signOut();
        navigate('/login');
      } else {
        toast.error(
          error.message || 'Unable to load dashboard. Please try again later.'
        );
      }
    },
    [navigate, signOut]
  );

  /**
   * Initialize WebSocket connection for real-time events
   */
  const initSocket = useCallback(() => {
    if (socketRef.current || !token) return;

    socketRef.current = io(process.env.REACT_APP_WS_ENDPOINT, {
      auth: { token },
      transports: ['websocket'],
    });

    socketRef.current.on('connect_error', (err) => {
      handleServiceError(err);
    });

    socketRef.current.on('dashboard-event', (domainEvent) => {
      // Domain events contain { type, payload, timestamp }
      switch (domainEvent.type) {
        case 'BadgeAwarded':
          toast.success(`🏆 You earned a badge: ${domainEvent.payload.name}`);
          setMetrics((prev) => ({
            ...prev,
            badges: (prev.badges || 0) + 1,
          }));
          break;
        case 'AssignmentSubmitted':
          setMetrics((prev) => ({
            ...prev,
            assignmentsSubmitted: (prev.assignmentsSubmitted || 0) + 1,
          }));
          break;
        case 'ProgressUpdated':
          setProgressData(domainEvent.payload.chartData);
          break;
        case 'FeedItem':
          setActivityFeed((prev) => [domainEvent.payload, ...prev].slice(0, 30));
          break;
        default:
          // Ignore unknown events but log for diagnostics
          /* eslint-disable no-console */
          console.warn('Unhandled dashboard-event:', domainEvent);
          /* eslint-enable no-console */
      }
    });
  }, [token, handleServiceError]);

  /**
   * Clean up on unmount
   */
  const cleanupResources = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    if (socketRef.current) {
      socketRef.current.disconnect();
      socketRef.current = null;
    }
  };

  // ---------- Life-Cycle ----------

  useEffect(() => {
    if (!token) {
      navigate('/login');
      return undefined;
    }

    fetchDashboardSnapshot();
    initSocket();

    return () => {
      cleanupResources();
    };
  }, [token, fetchDashboardSnapshot, initSocket, navigate]);

  // ---------- Render ----------

  if (loading) return <LoadingSpinner fullScreen />;

  return (
    <PageWrapper data-testid="dashboard-page">
      {/* Metrics Section */}
      <Section aria-labelledby="metrics-heading">
        <h2 id="metrics-heading">Your Highlights</h2>
        <MetricsGrid>
          <MetricCard label="Completed Courses" value={metrics?.courses || 0} />
          <MetricCard
            label="Assignments Submitted"
            value={metrics?.assignmentsSubmitted || 0}
          />
          <MetricCard label="Badges" value={metrics?.badges || 0} />
          <MetricCard
            label="Avg. Quiz Score"
            value={`${metrics?.avgQuizScore || 0}%`}
          />
        </MetricsGrid>
      </Section>

      {/* Progress Chart */}
      <Section aria-labelledby="progress-heading" minHeight="280px">
        <h2 id="progress-heading">Weekly Learning Progress</h2>
        {progressData.length === 0 ? (
          <span>No progress yet.</span>
        ) : (
          <ResponsiveContainer width="100%" height={250}>
            <AreaChart data={progressData} margin={{ top: 10, right: 30 }}>
              <defs>
                <linearGradient id="colorProgress" x1="0" y1="0" x2="0" y2="1">
                  <stop
                    offset="5%"
                    stopColor="#8884d8"
                    stopOpacity={0.8}
                  />
                  <stop
                    offset="95%"
                    stopColor="#8884d8"
                    stopOpacity={0}
                  />
                </linearGradient>
              </defs>
              <XAxis dataKey="day" />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Area
                type="monotone"
                dataKey="minutes"
                stroke="#8884d8"
                fillOpacity={1}
                fill="url(#colorProgress)"
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </Section>

      {/* Activity Feed */}
      <Section aria-labelledby="feed-heading">
        <h2 id="feed-heading">Recent Activity</h2>
        {activityFeed.length === 0 ? (
          <span>No activity yet.</span>
        ) : (
          <ActivityList>
            {activityFeed.map((item) => (
              <ActivityItem key={item.id}>{item.description}</ActivityItem>
            ))}
          </ActivityList>
        )}
      </Section>
    </PageWrapper>
  );
};

export default DashboardPage;

/* ============================================================================
 * Service Layer (DashboardService)
 * Inject dependency via default export for tree-shaking friendliness.
 * Can be moved to its own file (`src/services/DashboardService.js`).
 ============================================================================ */

export class DashboardApi {
  static async getSnapshot({ token, signal }) {
    const res = await fetch(`${process.env.REACT_APP_API_URL}/dashboard`, {
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      signal,
    });

    if (!res.ok) {
      const errorBody = await res.json().catch(() => ({}));
      throw Object.assign(new Error('Failed to fetch dashboard.'), {
        response: res,
        ...errorBody,
      });
    }

    return res.json();
  }
}

const DashboardService = {
  getSnapshot: DashboardApi.getSnapshot,
};

export { DashboardService };
```