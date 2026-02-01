/**
 * PulseLearn Campus Hub
 * frontend/src/pages/CourseDetailsPage.js
 *
 * A rich, real-time course details screen.  The component:
 *   • Fetches course metadata from the REST API
 *   • Listens to domain events over WebSocket for instant updates
 *   • Allows the learner to enroll / un-enroll
 *   • Shows loader & error states
 *
 * NOTE:  This file assumes the existence of several infrastructure helpers:
 *   – src/utils/axios.js          » pre-configured Axios instance
 *   – src/hooks/useEventListener  » custom hook for typed WS events
 *   – src/components/Toast        » global snackbar/notification system
 *   – src/components/PageLoader   » full-screen spinner
 *   – src/contexts/AuthContext    » authentication / current user
 *   – src/contexts/WebSocketContext » mqtt/kafka/nats → websocket bridge
 */

import React, {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import PropTypes from 'prop-types';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
  Chip,
  Container,
  Divider,
  Skeleton,
  Stack,
  Typography,
} from '@mui/material';
import SchoolIcon from '@mui/icons-material/School';
import PlayCircleIcon from '@mui/icons-material/PlayCircle';
import QuizIcon from '@mui/icons-material/Quiz';
import VerifiedIcon from '@mui/icons-material/Verified';

import axios from '../utils/axios';
import useEventListener from '../hooks/useEventListener';
import Toast from '../components/Toast';
import PageLoader from '../components/PageLoader';
import { AuthContext } from '../contexts/AuthContext';
import { WebSocketContext } from '../contexts/WebSocketContext';

const EVENT_TOPIC = 'course-stream';

/**
 * Skeleton placeholders while loading
 */
const LoadingSkeleton = () => (
  <Box>
    <Skeleton variant="rectangular" height={200} sx={{ mb: 2 }} />
    <Skeleton variant="text" width="60%" />
    <Skeleton variant="text" width="40%" />
    <Skeleton variant="text" width="80%" />
    <Divider sx={{ my: 3 }} />
    {[...Array(3)].map((_, idx) => (
      <Skeleton key={idx} variant="rectangular" height={60} sx={{ mb: 2 }} />
    ))}
  </Box>
);

const propTypes = {
  /** Optionally injected for SSR / tests */
  fetcher: PropTypes.func,
};

function CourseDetailsPage({ fetcher = axios }) {
  const { courseId } = useParams();
  const navigate = useNavigate();
  const { user } = useContext(AuthContext);
  const ws = useContext(WebSocketContext);

  const [course, setCourse] = useState(null);
  const [isEnrolled, setIsEnrolled] = useState(false);
  const [loading, setLoading] = useState(true);

  /**
   * Load course from REST API
   */
  const loadCourse = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await fetcher.get(`/api/courses/${courseId}`);
      setCourse(data.course);
      setIsEnrolled(data.enrolled);
    } catch (err) {
      Toast.error(
        err?.response?.data?.message || 'Unable to fetch course details.',
      );
      navigate('/404', { replace: true });
    } finally {
      setLoading(false);
    }
  }, [courseId, fetcher, navigate]);

  /**
   * Real-time event handler
   */
  const handleCourseEvent = useCallback(
    (event) => {
      // Ignore events for other courses
      if (event.payload.courseId !== courseId) return;

      switch (event.type) {
        case 'LectureUploaded':
          // Optimistically push new lecture into state
          setCourse((prev) => ({
            ...prev,
            lectures: [event.payload.lecture, ...prev.lectures],
          }));
          Toast.info(`New lecture "${event.payload.lecture.title}" added.`);
          break;

        case 'QuizAdded':
          setCourse((prev) => ({
            ...prev,
            quizzes: [event.payload.quiz, ...prev.quizzes],
          }));
          Toast.info(`A new quiz is now available.`);
          break;

        case 'CourseArchived':
          Toast.warning('This course has been archived by the instructor.');
          navigate('/courses', { replace: true });
          break;

        default:
          // Silent drop for unsupported events
          break;
      }
    },
    [courseId, navigate],
  );

  /**
   * Subscribe to course event stream via WS
   */
  useEventListener(ws, EVENT_TOPIC, handleCourseEvent);

  /**
   * Initial load
   */
  useEffect(() => {
    loadCourse();
  }, [loadCourse]);

  /**
   * Update document title
   */
  useEffect(() => {
    if (course?.title) {
      document.title = `${course.title} | PulseLearn`;
    }
  }, [course?.title]);

  /**
   * Enrollment / Un-enrollment action
   */
  const toggleEnrollment = async () => {
    // Guest users must log in
    if (!user) {
      Toast.info('Please sign in to enroll.');
      return navigate('/login', { state: { from: `/courses/${courseId}` } });
    }

    try {
      const url = isEnrolled
        ? `/api/courses/${courseId}/unenroll`
        : `/api/courses/${courseId}/enroll`;

      await fetcher.post(url);
      setIsEnrolled((v) => !v);

      Toast.success(
        isEnrolled
          ? 'You have been unenrolled.'
          : 'Welcome! You are now enrolled.',
      );
    } catch (err) {
      Toast.error(
        err?.response?.data?.message || 'Enrollment action failed. Try again.',
      );
    }
  };

  /**
   * Derived modules list with icon mapping
   */
  const modules = useMemo(() => {
    if (!course) return [];

    return [
      ...(course.lectures || []).map((l) => ({
        type: 'Lecture',
        icon: <PlayCircleIcon color="primary" />,
        title: l.title,
      })),
      ...(course.quizzes || []).map((q) => ({
        type: 'Quiz',
        icon: <QuizIcon color="secondary" />,
        title: q.title,
      })),
    ];
  }, [course]);

  /* ──────────────────────────── Render ──────────────────────────── */

  if (loading) {
    return (
      <Container maxWidth="md" sx={{ py: 4 }}>
        <LoadingSkeleton />
      </Container>
    );
  }

  if (!course) return null; // Should never happen, but TS might complain

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      {/* Cover Image */}
      <Box
        sx={{
          height: 240,
          borderRadius: 2,
          backgroundImage: `url(${course.coverImageUrl})`,
          backgroundPosition: 'center',
          backgroundSize: 'cover',
          mb: 3,
        }}
      />

      {/* Header Section */}
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        justifyContent="space-between"
        alignItems={{ xs: 'flex-start', sm: 'center' }}
        spacing={2}
        mb={3}
      >
        <Box>
          <Typography variant="h4" fontWeight={600}>
            {course.title}
          </Typography>
          <Stack direction="row" spacing={1} mt={1} alignItems="center">
            <SchoolIcon fontSize="small" color="action" />
            <Typography variant="body2" color="text.secondary">
              {course.instructor.name}
            </Typography>
          </Stack>
        </Box>

        <Button
          variant={isEnrolled ? 'outlined' : 'contained'}
          color="primary"
          size="large"
          onClick={toggleEnrollment}
        >
          {isEnrolled ? 'Un-enroll' : 'Enroll'}
        </Button>
      </Stack>

      {/* Course Meta */}
      <Stack direction="row" spacing={1} mb={2}>
        {course.tags.map((tag) => (
          <Chip key={tag} label={tag} variant="outlined" />
        ))}
        {course.certificationAvailable && (
          <Chip
            label="Certification"
            icon={<VerifiedIcon />}
            color="success"
          />
        )}
      </Stack>

      {/* Description */}
      <Typography variant="body1" sx={{ whiteSpace: 'pre-line' }}>
        {course.description}
      </Typography>

      <Divider sx={{ my: 4 }} />

      {/* Modules */}
      <Typography variant="h6" mb={2}>
        Modules
      </Typography>
      <Stack spacing={2}>
        {modules.map((m, idx) => (
          <Stack
            key={`${m.type}-${idx}`}
            direction="row"
            alignItems="center"
            spacing={2}
            sx={{
              p: 2,
              borderRadius: 1,
              bgcolor: (theme) => theme.palette.background.default,
            }}
          >
            {m.icon}
            <Typography variant="subtitle1" fontWeight={500}>
              {m.title}
            </Typography>
            <Chip
              label={m.type}
              variant="outlined"
              size="small"
              sx={{ ml: 'auto' }}
            />
          </Stack>
        ))}
      </Stack>
    </Container>
  );
}

CourseDetailsPage.propTypes = propTypes;
export default CourseDetailsPage;