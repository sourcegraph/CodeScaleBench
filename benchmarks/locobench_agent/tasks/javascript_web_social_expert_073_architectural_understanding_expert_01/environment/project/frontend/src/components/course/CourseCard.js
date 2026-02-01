```javascript
/*  pulselearn-campus-hub/frontend/src/components/course/CourseCard.js
 *  ------------------------------------------------------------------
 *  React component that renders a single course tile with enroll /
 *  continue / wishlist interactions. Integrates with the backend REST
 *  API and emits lightweight browser-level events that can be bridged
 *  to Kafka/NATS by the micro-front-end shell if desired.
 *
 *  Author: PulseLearn Front-end Team
 */
import React, { useState, useCallback, useMemo } from 'react';
import PropTypes from 'prop-types';
import {
  Card,
  CardMedia,
  CardContent,
  CardActions,
  Avatar,
  Typography,
  Chip,
  Button,
  Tooltip,
  LinearProgress,
  IconButton,
  Box,
  Stack,
} from '@mui/material';
import FavoriteBorderIcon from '@mui/icons-material/FavoriteBorder';
import FavoriteIcon from '@mui/icons-material/Favorite';
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline';
import SchoolIcon from '@mui/icons-material/School';
import { useSnackbar } from 'notistack';
import { useNavigate } from 'react-router-dom';
import apiClient from '../../services/apiClient'; // ← thin axios wrapper
import { useAuth } from '../../context/AuthContext'; // ← custom auth hook

/**
 * Emit a DOM CustomEvent so container apps or micro-front-ends can
 * bridge it to their own event bus without tight coupling.
 */
const emitDomainEvent = (type, detail = {}) =>
  window.dispatchEvent(new CustomEvent(type, { detail }));

const CourseCard = React.memo(function CourseCard({ course, onWishlistChange }) {
  const navigate = useNavigate();
  const { enqueueSnackbar } = useSnackbar();
  const { isAuthenticated, token } = useAuth();

  const [isEnrolling, setIsEnrolling] = useState(false);
  const [wishlist, setWishlist] = useState(Boolean(course.inWishlist));

  const {
    id,
    title,
    shortDescription,
    thumbnailUrl,
    author,
    progress = 0,
    isEnrolled = false,
    tags = [],
    rating,
    price,
  } = course;

  /**
   * POST /courses/:id/enroll
   */
  const handleEnroll = useCallback(async () => {
    if (!isAuthenticated) {
      enqueueSnackbar('Please login to enroll in this course.', { variant: 'info' });
      navigate('/login', { replace: true, state: { redirectTo: `/courses/${id}` } });
      return;
    }

    setIsEnrolling(true);
    try {
      await apiClient.post(
        `/courses/${id}/enroll`,
        {},
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      emitDomainEvent('CourseEnrollmentRequested', { courseId: id, userId: token?.sub });
      enqueueSnackbar('Enrollment successful! Redirecting…', { variant: 'success' });

      // Redirect user to course player
      navigate(`/courses/${id}`);
    } catch (err) {
      console.error('Enrollment error', err);
      enqueueSnackbar(
        err?.response?.data?.message || 'Unable to enroll at this time.',
        { variant: 'error' }
      );
    } finally {
      setIsEnrolling(false);
    }
  }, [id, token, isAuthenticated, enqueueSnackbar, navigate]);

  /**
   * Toggle wishlist
   */
  const handleWishlist = useCallback(async () => {
    if (!isAuthenticated) {
      enqueueSnackbar('Login to save courses to your wishlist.', { variant: 'info' });
      navigate('/login', { replace: true });
      return;
    }

    const nextState = !wishlist;
    setWishlist(nextState);

    // Notify parent early for optimistic UI
    onWishlistChange?.(id, nextState);

    try {
      await apiClient.patch(
        `/users/me/wishlist`,
        { courseId: id, add: nextState },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      emitDomainEvent('CourseWishlistToggled', { courseId: id, inWishlist: nextState });
    } catch (err) {
      console.error('Wishlist error', err);
      setWishlist(!nextState); // revert on failure
      onWishlistChange?.(id, !nextState);
      enqueueSnackbar('Could not update wishlist. Please try again.', { variant: 'error' });
    }
  }, [id, wishlist, token, isAuthenticated, enqueueSnackbar, onWishlistChange, navigate]);

  /**
   * Derived UI state
   */
  const progressLabel = useMemo(
    () => (progress > 0 ? `Progress: ${Math.floor(progress)}%` : null),
    [progress]
  );

  const enrollButtonLabel = isEnrolled
    ? progress > 0
      ? 'Continue'
      : 'Start Learning'
    : price && price > 0
    ? `Enroll • $${price.toFixed(2)}`
    : 'Enroll';

  return (
    <Card
      sx={{
        maxWidth: 345,
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        position: 'relative',
      }}
      elevation={3}
    >
      <CardMedia
        component="img"
        height="160"
        image={thumbnailUrl || '/static/images/course-placeholder.jpg'}
        alt={`${title} cover`}
        sx={{ cursor: 'pointer' }}
        onClick={() => navigate(`/courses/${id}`)}
      />
      <CardContent sx={{ flexGrow: 1 }}>
        <Stack direction="row" spacing={1} alignItems="center" mb={1}>
          <Avatar src={author?.avatar} alt={author?.name} sizes="24" />
          <Typography variant="subtitle2" color="text.secondary">
            {author?.name}
          </Typography>
        </Stack>

        <Tooltip title={title}>
          <Typography
            variant="h6"
            component="h2"
            gutterBottom
            sx={{
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {title}
          </Typography>
        </Tooltip>

        <Typography
          variant="body2"
          color="text.secondary"
          sx={{
            overflow: 'hidden',
            display: '-webkit-box',
            WebkitLineClamp: 3,
            WebkitBoxOrient: 'vertical',
          }}
        >
          {shortDescription}
        </Typography>

        {/* Tags */}
        <Box mt={1} sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
          {tags.slice(0, 3).map((tag) => (
            <Chip
              key={tag}
              label={tag}
              size="small"
              variant="outlined"
              color="primary"
              sx={{ pointerEvents: 'none' }}
            />
          ))}
        </Box>

        {/* Progress bar */}
        {isEnrolled && progress > 0 && (
          <Box mt={2}>
            <LinearProgress variant="determinate" value={progress} />
            <Typography variant="caption" color="text.secondary">
              {progressLabel}
            </Typography>
          </Box>
        )}
      </CardContent>

      {/* Bottom action row */}
      <CardActions sx={{ justifyContent: 'space-between', p: 2, pt: 0 }}>
        <Button
          aria-label={enrollButtonLabel}
          variant={isEnrolled ? 'outlined' : 'contained'}
          startIcon={isEnrolled ? <PlayCircleOutlineIcon /> : <SchoolIcon />}
          onClick={handleEnroll}
          disabled={isEnrolling}
        >
          {isEnrolling ? 'Please wait…' : enrollButtonLabel}
        </Button>

        {/* Wishlist button */}
        <IconButton
          aria-label={wishlist ? 'Remove from wishlist' : 'Add to wishlist'}
          onClick={handleWishlist}
          color="secondary"
        >
          {wishlist ? <FavoriteIcon /> : <FavoriteBorderIcon />}
        </IconButton>
      </CardActions>

      {/* Rating badge */}
      {rating && (
        <Box
          sx={{
            position: 'absolute',
            top: 8,
            right: 8,
            backgroundColor: 'rgba(0,0,0,0.7)',
            color: 'white',
            borderRadius: 1,
            px: 1,
            fontSize: 12,
            display: 'flex',
            alignItems: 'center',
          }}
        >
          ★ {rating.toFixed(1)}
        </Box>
      )}
    </Card>
  );
});

CourseCard.propTypes = {
  course: PropTypes.shape({
    id: PropTypes.string.isRequired,
    title: PropTypes.string.isRequired,
    shortDescription: PropTypes.string,
    thumbnailUrl: PropTypes.string,
    author: PropTypes.shape({
      name: PropTypes.string,
      avatar: PropTypes.string,
    }),
    progress: PropTypes.number,
    isEnrolled: PropTypes.bool,
    inWishlist: PropTypes.bool,
    tags: PropTypes.arrayOf(PropTypes.string),
    rating: PropTypes.number,
    price: PropTypes.number,
  }).isRequired,
  /**
   * Optional callback to notify parent that wishlist entry changed
   *    onWishlistChange(courseId: string, nowInWishlist: boolean)
   */
  onWishlistChange: PropTypes.func,
};

export default CourseCard;
```