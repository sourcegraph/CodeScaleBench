```javascript
/**
 * PulseLearn Campus Hub
 * File: frontend/src/components/layout/Header.js
 *
 * Global Header (a.k.a. Top-Bar) that renders:
 *   • Brand logo / title
 *   • Drawer toggle button (mobile)
 *   • Live notifications badge (WebSocket-driven)
 *   • User account dropdown (profile / logout)
 *
 * The component is fully self-contained but relies on several
 * application-level hooks/contexts.  Stubs for those utilities
 * are documented below so that this component compiles even when
 * imported in isolation (i.e. during Storybook / unit-tests).
 *
 * Design system: Material-UI v5
 */

import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
  Fragment
} from 'react';
import PropTypes from 'prop-types';

import {
  AppBar,
  Avatar,
  Badge,
  Box,
  Divider,
  IconButton,
  Link,
  Menu,
  MenuItem,
  Toolbar,
  Tooltip,
  Typography
} from '@mui/material';

import MenuIcon from '@mui/icons-material/Menu';
import NotificationsIcon from '@mui/icons-material/Notifications';
import LogoutIcon from '@mui/icons-material/Logout';
import AccountCircleIcon from '@mui/icons-material/AccountCircle';
import { useNavigate } from 'react-router-dom';

/* -------------------------------------------------------------------------- */
/*                        Application-level Context Hooks                     */
/* -------------------------------------------------------------------------- */

/**
 * NOTE:
 *  In the real project these hooks come from dedicated modules.
 *  They are mocked here to avoid unresolved imports in isolation.
 */
let _didWarnOnce = false;
const warnOnce = (msg) => {
  if (_didWarnOnce) return;
  // eslint-disable-next-line no-console
  console.warn(`[Mock-Stub] ${msg}`);
  _didWarnOnce = true;
};

const useAuth = () => {
  warnOnce('useAuth hook is running in stub mode – replace with real impl.');
  return {
    user: {
      id: 'mock-123',
      name: 'John Doe',
      avatarUrl: null // Intentionally null to exercise fallback rendering
    },
    logout: async () => {
      /* no-op */
    },
    isAuthenticated: true
  };
};

const useNotifications = () => {
  warnOnce(
    'useNotifications hook is running in stub mode – replace with real impl.'
  );
  return {
    unreadCount: 0,
    notifications: [],
    markAllRead: () => {},
    subscribe: () => () => {} // returns unsubscribe
  };
};

/* -------------------------------------------------------------------------- */
/*                                Header Component                            */
/* -------------------------------------------------------------------------- */

const Header = ({ onToggleSidebar }) => {
  const navigate = useNavigate();

  /* ---------- Auth/Notifications State ---------- */
  const { user, isAuthenticated, logout } = useAuth();
  const {
    unreadCount,
    markAllRead,
    subscribe: subscribeNotifications
  } = useNotifications();

  /* ---------- Component Local State ------------- */
  const [anchorElUser, setAnchorElUser] = useState(null);

  /* ---------- Event Handlers -------------------- */
  const handleOpenUserMenu = (event) => {
    setAnchorElUser(event.currentTarget);
  };

  const handleCloseUserMenu = () => setAnchorElUser(null);

  const handleLogout = useCallback(async () => {
    handleCloseUserMenu();
    try {
      await logout();
      navigate('/login');
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('Logout failed:', err);
    }
  }, [logout, navigate]);

  const handleViewProfile = () => {
    handleCloseUserMenu();
    navigate('/profile');
  };

  const handleNotificationClick = () => {
    markAllRead();
    navigate('/notifications');
  };

  /* ---------- Real-time Notifications ----------- */
  useEffect(() => {
    /**
     * Subscribe to WebSocket channel.
     * Each time a new notification is pushed, the global
     * `useNotifications` hook should update `unreadCount`.
     */
    const unsubscribe = subscribeNotifications();

    // cleanup on unmount
    return () => {
      try {
        unsubscribe?.();
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error('Failed to unsubscribe from notifications:', err);
      }
    };
  }, [subscribeNotifications]);

  /* ---------- Derived Rendering Helpers --------- */
  const userInitials = useMemo(() => {
    if (!user?.name) return '?';
    return user.name
      .split(' ')
      .map((n) => n[0])
      .join('')
      .substring(0, 2)
      .toUpperCase();
  }, [user]);

  /* ---------------------------------------------------------------------- */
  /*                                RENDER                                  */
  /* ---------------------------------------------------------------------- */
  return (
    <AppBar
      position="sticky"
      color="primary"
      elevation={1}
      sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}
    >
      <Toolbar variant="dense" disableGutters>
        {/* ---- Left: Drawer Toggle / Brand ---- */}
        <IconButton
          edge="start"
          aria-label="open navigation"
          color="inherit"
          onClick={onToggleSidebar}
          sx={{ mx: 1 }}
        >
          <MenuIcon />
        </IconButton>

        <Link
          href="/"
          underline="none"
          color="inherit"
          sx={{ display: 'flex', alignItems: 'center' }}
        >
          <Box component="img"
               src="/static/logo.svg"
               alt="PulseLearn Logo"
               sx={{ height: 24, mr: 1 }}
          />
          <Typography variant="h6" component="span" noWrap>
            PulseLearn
          </Typography>
        </Link>

        {/* spacer */}
        <Box sx={{ flexGrow: 1 }} />

        {/* ---- Right: Notification bell & User avatar ---- */}
        {isAuthenticated && (
          <Fragment>
            <Tooltip title="Notifications">
              <IconButton
                size="large"
                aria-label={`show ${unreadCount} new notifications`}
                color="inherit"
                onClick={handleNotificationClick}
              >
                <Badge badgeContent={unreadCount} color="error">
                  <NotificationsIcon />
                </Badge>
              </IconButton>
            </Tooltip>

            <Tooltip title="Account settings">
              <IconButton
                onClick={handleOpenUserMenu}
                size="large"
                sx={{ ml: 1 }}
                color="inherit"
              >
                {user?.avatarUrl ? (
                  <Avatar
                    src={user.avatarUrl}
                    alt={user.name}
                    sx={{ width: 32, height: 32 }}
                  />
                ) : (
                  <Avatar sx={{ width: 32, height: 32 }}>
                    {userInitials}
                  </Avatar>
                )}
              </IconButton>
            </Tooltip>

            {/* ---------------- User Menu ---------------- */}
            <Menu
              sx={{ mt: '32px' }}
              id="menu-appbar"
              anchorEl={anchorElUser}
              anchorOrigin={{
                vertical: 'top',
                horizontal: 'right'
              }}
              keepMounted
              transformOrigin={{
                vertical: 'top',
                horizontal: 'right'
              }}
              open={Boolean(anchorElUser)}
              onClose={handleCloseUserMenu}
            >
              <MenuItem disabled sx={{ pointerEvents: 'none' }}>
                <Box sx={{ display: 'flex', alignItems: 'center' }}>
                  {user?.avatarUrl ? (
                    <Avatar
                      src={user.avatarUrl}
                      alt={user.name}
                      sx={{ width: 32, height: 32, mr: 1 }}
                    />
                  ) : (
                    <Avatar sx={{ width: 32, height: 32, mr: 1 }}>
                      {userInitials}
                    </Avatar>
                  )}
                  <Box>
                    <Typography variant="subtitle2">
                      {user?.name ?? '–'}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {user?.email ?? ' '}
                    </Typography>
                  </Box>
                </Box>
              </MenuItem>

              <Divider />

              <MenuItem onClick={handleViewProfile}>
                <AccountCircleIcon sx={{ mr: 1 }} fontSize="small" />
                Profile
              </MenuItem>

              <MenuItem onClick={handleLogout}>
                <LogoutIcon sx={{ mr: 1 }} fontSize="small" />
                Logout
              </MenuItem>
            </Menu>
          </Fragment>
        )}
      </Toolbar>
    </AppBar>
  );
};

Header.propTypes = {
  /**
   * Callback fired when the hamburger icon is clicked.
   * Should toggle the sidebar / drawer in parent layout.
   */
  onToggleSidebar: PropTypes.func
};

Header.defaultProps = {
  onToggleSidebar: () => {}
};

export default React.memo(Header);
```