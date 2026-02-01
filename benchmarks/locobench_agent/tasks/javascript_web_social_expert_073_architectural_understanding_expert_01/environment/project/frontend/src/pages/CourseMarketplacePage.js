```javascript
/**
 * PulseLearn Campus Hub
 * Course Marketplace Page
 *
 * Shows a searchable, filterable list of public courses that the user
 * can preview or add to their cart. Listens to the real-time
 * `CoursePublished` event so that newly published courses appear instantly.
 *
 * NOTE: All environment variables, contexts, hooks and services referenced
 * here are defined elsewhere in the PulseLearn frontend code-base.
 */

import React, {
  useState,
  useMemo,
  useCallback,
  useEffect,
  useRef,
} from 'react';
import {
  Box,
  Container,
  Grid,
  Card,
  CardContent,
  CardMedia,
  Typography,
  Button,
  Chip,
  TextField,
  CircularProgress,
  Snackbar,
  Pagination,
  Tooltip,
} from '@mui/material';
import { styled } from '@mui/material/styles';
import ShoppingCartIcon from '@mui/icons-material/ShoppingCart';
import StarIcon from '@mui/icons-material/Star';
import { useNavigate } from 'react-router-dom';
import { io } from 'socket.io-client';
import axios from 'axios';
import { useQuery, useQueryClient } from 'react-query';
import debounce from 'lodash.debounce';

import { API_BASE_URL, SOCKET_URL } from '@/configs/env';
import useAuth from '@/hooks/useAuth';
import { useCart } from '@/context/CartContext';
import { trackEvent } from '@/services/analytics';

/* -------------------------------------------------------------------------- */
/*                              Styled components                             */
/* -------------------------------------------------------------------------- */

const CourseCard = styled(Card)(({ theme }) => ({
  height: '100%',
  display: 'flex',
  flexDirection: 'column',
  position: 'relative',
}));

const CourseMedia = styled(CardMedia)({
  paddingTop: '56.25%', // 16:9
});

const PriceTag = styled(Chip)(({ theme }) => ({
  position: 'absolute',
  top: theme.spacing(2),
  right: theme.spacing(2),
  fontWeight: 700,
}));

const RatingChip = styled(Chip)(({ theme }) => ({
  position: 'absolute',
  top: theme.spacing(2),
  left: theme.spacing(2),
  backgroundColor: theme.palette.success.main,
  color: theme.palette.common.white,
}));

/* -------------------------------------------------------------------------- */
/*                                  Helpers                                   */
/* -------------------------------------------------------------------------- */

/**
 * Builds a params object from local state so that it can be memoised by
 * React Query while keeping the key serialisable.
 */
const buildQueryParams = (search, category, page) => {
  const params = { page };
  if (search) params.q = search;
  if (category) params.category = category;
  return params;
};

/**
 * Fetch list of marketplace courses from the back-end.
 */
const fetchCourses = async ({ queryKey }) => {
  const [, params] = queryKey;
  const { data } = await axios.get(`${API_BASE_URL}/courses/marketplace`, {
    params,
    withCredentials: true,
  });
  return data.courses;
};

/* -------------------------------------------------------------------------- */
/*                               Main component                               */
/* -------------------------------------------------------------------------- */

const CourseMarketplacePage = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { user, isAuthenticated } = useAuth();
  const { addToCart } = useCart();

  /* ------------------------------- Local state ----------------------------- */

  const [search, setSearch] = useState('');
  const [category, setCategory] = useState(null);
  const [page, setPage] = useState(1);
  const [toast, setToast] = useState({
    open: false,
    message: '',
    severity: 'success',
  });

  /* ----------------------------- Debounced search -------------------------- */

  const debouncedSearch = useRef(
    debounce((value) => {
      // Reset pagination when search changes
      setPage(1);
      queryClient.invalidateQueries([
        'marketplaceCourses',
        buildQueryParams(value, category, 1),
      ]);
    }, 400),
  ).current;

  const handleSearchChange = (e) => {
    setSearch(e.target.value);
    debouncedSearch(e.target.value);
  };

  /* --------------------------- Data-fetching hook -------------------------- */

  const queryParams = useMemo(
    () => buildQueryParams(search, category, page),
    [search, category, page],
  );

  const {
    data: courses,
    isLoading,
    isError,
    error,
  } = useQuery(['marketplaceCourses', queryParams], fetchCourses, {
    keepPreviousData: true,
    staleTime: 1000 * 60 * 5, // 5 minutes
    onError: (e) => console.error('Failed to fetch courses:', e),
  });

  /* ---------------------------- Real-time events --------------------------- */

  useEffect(() => {
    const socket = io(SOCKET_URL, {
      auth: { token: user?.token },
      transports: ['websocket'],
    });

    socket.on('CoursePublished', (newCourse) => {
      // Prepend new course to current cache
      queryClient.setQueryData(
        ['marketplaceCourses', queryParams],
        (old = []) => [newCourse, ...old],
      );
    });

    socket.on('connect_error', (err) =>
      console.warn('Socket connection failed:', err.message),
    );

    return () => socket.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.token, queryClient, queryParams]);

  /* ------------------------------- Handlers -------------------------------- */

  const handleCategoryClick = (cat) => {
    setCategory(category === cat ? null : cat);
    setPage(1);
  };

  const handleAddToCart = useCallback(
    (course) => {
      try {
        addToCart(course);
        setToast({
          open: true,
          severity: 'success',
          message: `"${course.title}" added to cart.`,
        });
        trackEvent('COURSE_ADDED_TO_CART', { courseId: course.id });
      } catch (e) {
        console.error(e);
        setToast({
          open: true,
          severity: 'error',
          message: 'Failed to add course to cart.',
        });
      }
    },
    [addToCart],
  );

  const handleCourseClick = (id) => navigate(`/courses/${id}`);

  const handleToastClose = () => setToast({ ...toast, open: false });

  /* ---------------------------- Derived values ----------------------------- */

  const categories = useMemo(() => {
    if (!courses) return [];
    const set = new Set();
    courses.forEach((c) => set.add(c.category));
    return [...set];
  }, [courses]);

  /* -------------------------------- Render --------------------------------- */

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      {/* Search & category filter */}
      <Box sx={{ display: 'flex', flexDirection: 'column', mb: 3 }}>
        <TextField
          label="Search courses"
          variant="outlined"
          size="small"
          value={search}
          onChange={handleSearchChange}
          sx={{ maxWidth: 400 }}
        />

        <Box sx={{ mt: 2, display: 'flex', gap: 1, flexWrap: 'wrap' }}>
          {categories.map((cat) => (
            <Chip
              key={cat}
              clickable
              label={cat}
              color={cat === category ? 'primary' : 'default'}
              onClick={() => handleCategoryClick(cat)}
            />
          ))}
        </Box>
      </Box>

      {/* Course grid */}
      {isLoading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 6 }}>
          <CircularProgress />
        </Box>
      ) : isError ? (
        <Typography color="error">
          Failed to load courses: {error?.message}
        </Typography>
      ) : courses?.length ? (
        <>
          <Grid container spacing={3}>
            {courses.map((course) => (
              <Grid item xs={12} sm={6} md={4} key={course.id}>
                <CourseCard>
                  <CourseMedia
                    image={course.thumbnailUrl}
                    title={course.title}
                    onClick={() => handleCourseClick(course.id)}
                    sx={{ cursor: 'pointer' }}
                  />
                  <RatingChip
                    icon={<StarIcon fontSize="small" />}
                    label={course.rating.toFixed(1)}
                    size="small"
                  />
                  <PriceTag
                    label={course.price === 0 ? 'Free' : `$${course.price}`}
                    color={course.price === 0 ? 'success' : 'warning'}
                    size="small"
                  />

                  <CardContent sx={{ flexGrow: 1 }}>
                    <Tooltip title={course.title}>
                      <Typography
                        variant="h6"
                        component="div"
                        noWrap
                        sx={{ cursor: 'pointer' }}
                        onClick={() => handleCourseClick(course.id)}
                      >
                        {course.title}
                      </Typography>
                    </Tooltip>

                    <Typography variant="body2" color="text.secondary" gutterBottom>
                      {course.shortDescription}
                    </Typography>

                    <Button
                      variant="contained"
                      color="primary"
                      startIcon={<ShoppingCartIcon />}
                      fullWidth
                      disabled={!isAuthenticated}
                      onClick={() => handleAddToCart(course)}
                    >
                      {isAuthenticated ? 'Add to Cart' : 'Login to Purchase'}
                    </Button>
                  </CardContent>
                </CourseCard>
              </Grid>
            ))}
          </Grid>

          {/* Pagination (mocked total pages; should come from API) */}
          <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
            <Pagination
              count={10}
              page={page}
              onChange={(_, newPage) => setPage(newPage)}
              color="primary"
            />
          </Box>
        </>
      ) : (
        <Typography variant="h6">No courses found.</Typography>
      )}

      {/* Feedback toast */}
      <Snackbar
        open={toast.open}
        autoHideDuration={4000}
        onClose={handleToastClose}
        message={toast.message}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      />
    </Container>
  );
};

export default CourseMarketplacePage;
```