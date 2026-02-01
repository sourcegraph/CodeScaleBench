```javascript
/**
 * AdminPanelPage.js
 * PulseLearn Campus Hub – Admin Panel (React)
 *
 * This page is only accessible to authenticated admin users.  It provides:
 *   1.  Real-time platform metrics
 *   2.  CRUD operations for users
 *   3.  A streaming event log for operational insight
 *   4.  Basic platform settings management
 *
 * The component uses a tabbed layout and integrates REST + WebSocket data-sources.
 * Only the most essential UI code is included; styling is handled by Material-UI’s
 * default theme or the parent application’s ThemeProvider.
 */

import React, {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useState,
} from 'react';
import PropTypes from 'prop-types';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
  Snackbar,
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TablePagination,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import {
  Delete as DeleteIcon,
  Edit as EditIcon,
  Refresh as RefreshIcon,
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';

import api from '../services/api'; // Axios instance with interceptors
import useAuth from '../hooks/useAuth'; // Supplies { user, logout }
import useWebSocket from '../hooks/useWebSocket'; // Lightweight abstraction
import useIsMounted from '../hooks/useIsMounted'; // Prevents setState on unmounted
import validateEmail from '../utils/validateEmail'; // Email validator fn

/* -------------------------------------------------------------------------- */
/* Helpers                                                                    */
/* -------------------------------------------------------------------------- */

const initialSnackbar = { open: false, message: '', severity: 'success' };

function snackbarReducer(state, action) {
  switch (action.type) {
    case 'SHOW':
      return { open: true, message: action.message, severity: action.severity };
    case 'HIDE':
      return { ...state, open: false };
    default:
      return state;
  }
}

/* -------------------------------------------------------------------------- */
/* AdminPanelPage                                                             */
/* -------------------------------------------------------------------------- */

export default function AdminPanelPage() {
  const navigate = useNavigate();
  const isMounted = useIsMounted();
  const { user, logout } = useAuth(); // Must supply role property

  const [tab, setTab] = useState(0);

  // Metrics
  const [metrics, setMetrics] = useState(null);
  const [metricsLoading, setMetricsLoading] = useState(true);

  // Users
  const [usersLoading, setUsersLoading] = useState(false);
  const [users, setUsers] = useState([]);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(10);
  const [totalUsers, setTotalUsers] = useState(0);

  // User dialog state
  const [editingUser, setEditingUser] = useState(null);
  const [isUserDialogOpen, setIsUserDialogOpen] = useState(false);

  // Event log
  const [events, setEvents] = useState([]);

  // Snackbar
  const [snackbarState, dispatchSnackbar] = useReducer(
    snackbarReducer,
    initialSnackbar,
  );

  /* ---------------------------------------------------------------------- */
  /* Guard: must be admin                                                   */
  /* ---------------------------------------------------------------------- */

  useEffect(() => {
    if (!user) {
      return;
    }
    if (user.role !== 'ADMIN') {
      navigate('/403', { replace: true });
    }
  }, [user, navigate]);

  /* ---------------------------------------------------------------------- */
  /* Metrics (REST)                                                         */
  /* ---------------------------------------------------------------------- */

  const fetchMetrics = useCallback(async () => {
    try {
      setMetricsLoading(true);
      const { data } = await api.get('/admin/metrics');
      if (isMounted.current) {
        setMetrics(data);
      }
    } catch (err) {
      console.error('Failed to fetch metrics', err);
      dispatchSnackbar({
        type: 'SHOW',
        severity: 'error',
        message: 'Failed to load metrics.',
      });
    } finally {
      if (isMounted.current) setMetricsLoading(false);
    }
  }, [isMounted]);

  useEffect(() => {
    fetchMetrics();
  }, [fetchMetrics]);

  /* ---------------------------------------------------------------------- */
  /* Users (REST)                                                           */
  /* ---------------------------------------------------------------------- */

  const fetchUsers = useCallback(
    async (pg = page, rpp = rowsPerPage) => {
      try {
        setUsersLoading(true);
        const { data } = await api.get('/admin/users', {
          params: { page: pg + 1, limit: rpp },
        });
        if (isMounted.current) {
          setUsers(data.items);
          setTotalUsers(data.total);
        }
      } catch (err) {
        console.error('Failed to fetch users', err);
        dispatchSnackbar({
          type: 'SHOW',
          severity: 'error',
          message: 'Unable to load user list.',
        });
      } finally {
        if (isMounted.current) setUsersLoading(false);
      }
    },
    [page, rowsPerPage, isMounted],
  );

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers, page, rowsPerPage]);

  /* ---------------------------------------------------------------------- */
  /* WebSocket: streaming event logs                                        */
  /* ---------------------------------------------------------------------- */

  useWebSocket('/ws/admin/events', {
    onMessage: (evt) => {
      const parsed = JSON.parse(evt.data);
      if (parsed.type === 'PLATFORM_EVENT') {
        setEvents((prev) => [parsed.payload, ...prev.slice(0, 299)]); // keep last 300
      }
    },
    onError: (err) => {
      console.error('WebSocket error', err);
      dispatchSnackbar({
        type: 'SHOW',
        severity: 'warning',
        message: 'Event stream disconnected.',
      });
    },
  });

  /* ---------------------------------------------------------------------- */
  /* Handlers                                                               */
  /* ---------------------------------------------------------------------- */

  const handleTabChange = (_, newValue) => setTab(newValue);

  const handleUserDialogClose = () => {
    setEditingUser(null);
    setIsUserDialogOpen(false);
  };

  const handleUserEdit = (userToEdit) => {
    setEditingUser(userToEdit);
    setIsUserDialogOpen(true);
  };

  const handleUserDelete = async (userToDelete) => {
    // eslint-disable-next-line no-alert
    if (!window.confirm(`Deactivate user "${userToDelete.email}"?`)) return;
    try {
      await api.delete(`/admin/users/${userToDelete.id}`);
      dispatchSnackbar({
        type: 'SHOW',
        severity: 'success',
        message: 'User deactivated.',
      });
      fetchUsers();
    } catch (err) {
      console.error('Failed to deactivate user', err);
      dispatchSnackbar({
        type: 'SHOW',
        severity: 'error',
        message: 'Could not deactivate user.',
      });
    }
  };

  const handleUserDialogSave = async (formState) => {
    try {
      if (editingUser) {
        await api.put(`/admin/users/${editingUser.id}`, formState);
        dispatchSnackbar({
          type: 'SHOW',
          severity: 'success',
          message: 'User updated.',
        });
      } else {
        await api.post('/admin/users', formState);
        dispatchSnackbar({
          type: 'SHOW',
          severity: 'success',
          message: 'User created.',
        });
      }
      handleUserDialogClose();
      fetchUsers();
    } catch (err) {
      console.error('Failed to save user', err);
      dispatchSnackbar({
        type: 'SHOW',
        severity: 'error',
        message: 'Unable to save user.',
      });
    }
  };

  /* ---------------------------------------------------------------------- */
  /* Memoized Components                                                    */
  /* ---------------------------------------------------------------------- */

  const metricCards = useMemo(() => {
    if (!metrics) return null;
    return (
      <Box
        sx={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 2,
          mb: 4,
        }}
      >
        {Object.entries(metrics).map(([key, value]) => (
          <Paper
            key={key}
            elevation={3}
            sx={{
              width: 160,
              height: 100,
              p: 2,
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'center',
              alignItems: 'center',
            }}
          >
            <Typography variant="h5" component="div" color="primary">
              {value}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {key.replace(/([A-Z])/g, ' $1')}
            </Typography>
          </Paper>
        ))}
      </Box>
    );
  }, [metrics]);

  /* ---------------------------------------------------------------------- */
  /* Render                                                                 */
  /* ---------------------------------------------------------------------- */

  return (
    <Fragment>
      <Typography variant="h4" sx={{ mb: 2 }}>
        Admin Panel
      </Typography>

      <Tabs value={tab} onChange={handleTabChange} sx={{ mb: 3 }}>
        <Tab label="Dashboard" />
        <Tab label="Users" />
        <Tab label="Events" />
        <Tab label="Settings" />
      </Tabs>

      {/* -------------------------- Dashboard TAB ------------------------- */}
      {tab === 0 && (
        <Box>
          <Button
            startIcon={<RefreshIcon />}
            variant="outlined"
            size="small"
            onClick={fetchMetrics}
            disabled={metricsLoading}
            sx={{ mb: 2 }}
          >
            Refresh
          </Button>

          {metricsLoading ? (
            <CircularProgress />
          ) : (
            metricCards
          )}
        </Box>
      )}

      {/* --------------------------- Users TAB ---------------------------- */}
      {tab === 1 && (
        <Box>
          <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1 }}>
            <Button
              variant="contained"
              onClick={() => setIsUserDialogOpen(true)}
            >
              Add User
            </Button>
          </Box>

          <Paper sx={{ width: '100%', overflow: 'hidden' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Email</TableCell>
                  <TableCell>Role</TableCell>
                  <TableCell>Created</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {usersLoading ? (
                  <TableRow>
                    <TableCell colSpan={4} align="center">
                      <CircularProgress size={24} />
                    </TableCell>
                  </TableRow>
                ) : users.length ? (
                  users.map((u) => (
                    <TableRow key={u.id}>
                      <TableCell>{u.email}</TableCell>
                      <TableCell>{u.role}</TableCell>
                      <TableCell>
                        {new Date(u.createdAt).toLocaleDateString()}
                      </TableCell>
                      <TableCell align="right">
                        <IconButton
                          aria-label="edit"
                          onClick={() => handleUserEdit(u)}
                          size="small"
                        >
                          <EditIcon fontSize="inherit" />
                        </IconButton>
                        <IconButton
                          aria-label="delete"
                          onClick={() => handleUserDelete(u)}
                          size="small"
                        >
                          <DeleteIcon fontSize="inherit" />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={4} align="center">
                      No users found.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>

            <TablePagination
              component="div"
              count={totalUsers}
              page={page}
              onPageChange={(_, newPage) => setPage(newPage)}
              rowsPerPage={rowsPerPage}
              onRowsPerPageChange={(e) => {
                setRowsPerPage(parseInt(e.target.value, 10));
                setPage(0);
              }}
              rowsPerPageOptions={[5, 10, 25]}
            />
          </Paper>
        </Box>
      )}

      {/* --------------------------- Events TAB --------------------------- */}
      {tab === 2 && (
        <Paper sx={{ p: 2, height: 480, overflowY: 'auto' }}>
          {events.length === 0 && (
            <Typography variant="body2" color="text.secondary">
              Waiting for events...
            </Typography>
          )}
          {events.map((evt, idx) => (
            <Box
              key={idx} // eslint-disable-line react/no-array-index-key
              sx={{
                display: 'flex',
                borderBottom: '1px solid #eee',
                pb: 1,
                mb: 1,
              }}
            >
              <Typography
                variant="caption"
                sx={{ width: 180, color: 'text.secondary' }}
              >
                {new Date(evt.timestamp).toLocaleString()}
              </Typography>
              <Typography
                component="span"
                sx={{ ml: 1, fontFamily: 'monospace' }}
              >
                {evt.type}:&nbsp;
              </Typography>
              <Typography component="span">{evt.summary}</Typography>
            </Box>
          ))}
        </Paper>
      )}

      {/* -------------------------- Settings TAB -------------------------- */}
      {tab === 3 && (
        <Box>
          <Typography variant="body1" sx={{ mb: 2 }}>
            (Coming soon) Manage platform-wide settings like feature flags,
            maintenance windows, and default roles.
          </Typography>
          <Button variant="outlined" onClick={logout}>
            Log out
          </Button>
        </Box>
      )}

      {/* -------------------------- User Dialog --------------------------- */}
      {isUserDialogOpen && (
        <UserDialog
          open={isUserDialogOpen}
          onClose={handleUserDialogClose}
          onSave={handleUserDialogSave}
          editingUser={editingUser}
        />
      )}

      {/* --------------------------- Snackbar ---------------------------- */}
      <Snackbar
        open={snackbarState.open}
        autoHideDuration={4000}
        onClose={() => dispatchSnackbar({ type: 'HIDE' })}
      >
        <Alert
          onClose={() => dispatchSnackbar({ type: 'HIDE' })}
          severity={snackbarState.severity}
          sx={{ width: '100%' }}
        >
          {snackbarState.message}
        </Alert>
      </Snackbar>
    </Fragment>
  );
}

/* -------------------------------------------------------------------------- */
/* UserDialog                                                                 */
/* -------------------------------------------------------------------------- */

function UserDialog({ open, onClose, onSave, editingUser }) {
  const isEdit = Boolean(editingUser);

  const [formState, setFormState] = useState({
    email: editingUser?.email || '',
    role: editingUser?.role || 'STUDENT',
    password: '',
  });

  const [errors, setErrors] = useState({});

  const validate = useCallback(() => {
    const errs = {};
    if (!validateEmail(formState.email)) {
      errs.email = 'Invalid e-mail address';
    }
    if (!isEdit && formState.password.length < 8) {
      errs.password = 'Minimum 8 characters';
    }
    setErrors(errs);
    return Object.keys(errs).length === 0;
  }, [formState, isEdit]);

  useEffect(() => {
    validate();
  }, [formState, validate]);

  const handleChange = (field) => (evt) =>
    setFormState((prev) => ({ ...prev, [field]: evt.target.value }));

  const handleSubmit = () => {
    if (!validate()) return;
    const payload = { ...formState };
    if (isEdit && !payload.password) delete payload.password; // do not send blank
    onSave(payload);
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{isEdit ? 'Edit User' : 'Add User'}</DialogTitle>
      <DialogContent>
        <TextField
          margin="dense"
          label="Email"
          fullWidth
          value={formState.email}
          onChange={handleChange('email')}
          error={Boolean(errors.email)}
          helperText={errors.email}
        />

        <TextField
          margin="dense"
          label="Role"
          select
          fullWidth
          value={formState.role}
          onChange={handleChange('role')}
        >
          <MenuItem value="STUDENT">Student</MenuItem>
          <MenuItem value="TEACHER">Teacher</MenuItem>
          <MenuItem value="ADMIN">Admin</MenuItem>
        </TextField>

        {!isEdit && (
          <TextField
            margin="dense"
            label="Password"
            type="password"
            fullWidth
            value={formState.password}
            onChange={handleChange('password')}
            error={Boolean(errors.password)}
            helperText={errors.password}
          />
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={Object.keys(errors).length > 0}
        >
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}

UserDialog.propTypes = {
  open: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  onSave: PropTypes.func.isRequired,
  editingUser: PropTypes.shape({
    id: PropTypes.string,
    email: PropTypes.string,
    role: PropTypes.string,
  }),
};

UserDialog.defaultProps = {
  editingUser: null,
};
```