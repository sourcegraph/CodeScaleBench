```javascript
// pulselearn-campus-hub/frontend/src/components/layout/Sidebar.js

/**
 * Sidebar component for PulseLearn Campus Hub
 *
 * Features
 *  - Adaptive navigation based on user role (student | teacher | admin)
 *  - Collapsible behaviour with persisted UI preference (localStorage)
 *  - Active route highlighting via react-router <NavLink>
 *  - Real-time badge counter for unread notifications
 *  - Accessibility-friendly (aria-labels, keyboard navigable)
 */

import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
  Fragment,
} from 'react';
import PropTypes from 'prop-types';
import { NavLink, useLocation } from 'react-router-dom';
import styled, { css } from 'styled-components';
import classNames from 'classnames';

// MUI Icons — tree-shaken when using @mui v5+
import DashboardIcon from '@mui/icons-material/Dashboard';
import SchoolIcon from '@mui/icons-material/School';
import ForumIcon from '@mui/icons-material/Forum';
import NotificationsIcon from '@mui/icons-material/Notifications';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import MenuOpenIcon from '@mui/icons-material/MenuOpen';
import MenuIcon from '@mui/icons-material/Menu';

// A tiny debounce helper to avoid localStorage thrashing
const debounce = (fn, ms = 300) => {
  let id;
  return (...args) => {
    clearTimeout(id);
    id = setTimeout(() => fn(...args), ms);
  };
};

// Styled-Components
/* ----------------------------------------------------------------------- */

const SidebarContainer = styled.aside`
  position: fixed;
  inset: 0 auto 0 0;
  width: ${({ $collapsed }) => ($collapsed ? '4.5rem' : '15rem')};
  background: #0f213f;
  color: #ffffff;
  display: flex;
  flex-direction: column;
  transition: width 200ms ease;
  overflow: hidden;
  z-index: 1000;
`;

const Branding = styled.div`
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  font-size: 1.1rem;
  font-weight: 600;
  white-space: nowrap;
  svg {
    font-size: 1.75rem;
  }
`;

const Nav = styled.nav`
  flex: 1 1 auto;
  margin-top: 0.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding-inline: 0.25rem;
  overflow-y: auto;
`;

const NavItem = styled(NavLink).attrs(() => ({
  role: 'menuitem',
  tabIndex: 0,
}))`
  display: grid;
  grid-template-columns: 2.75rem 1fr auto;
  align-items: center;
  gap: 1rem;
  padding: 0.75rem 1rem;
  border-radius: 0.375rem;
  color: #d1d9e6;
  font-size: 0.925rem;
  text-decoration: none;
  transition: background 150ms ease, color 150ms ease;
  &:hover,
  &.active {
    background: #1d2d52;
    color: #ffffff;
  }
  svg {
    font-size: 1.45rem;
  }
  ${({ $collapsed }) =>
    $collapsed &&
    css`
      justify-content: center;
      grid-template-columns: 1fr;
      padding: 0.75rem 0.5rem;
      span,
      .badge {
        display: none;
      }
    `}
`;

const Badge = styled.span`
  background: #f2545b;
  color: #ffffff;
  border-radius: 999rem;
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.1rem 0.55rem;
  line-height: 1.35;
  justify-self: end;
`;

const Footer = styled.div`
  padding: 0.75rem 0.25rem 1rem;
  display: flex;
  justify-content: ${({ $collapsed }) =>
    $collapsed ? 'center' : 'flex-end'};
`;

const ToggleButton = styled.button.attrs(() => ({
  type: 'button',
  'aria-label': 'Toggle sidebar',
}))`
  border: 0;
  background: transparent;
  color: #ffffff;
  display: grid;
  place-items: center;
  border-radius: 0.375rem;
  padding: 0.55rem;
  width: 2.75rem;
  height: 2.75rem;
  cursor: pointer;
  &:hover {
    background: #1d2d52;
  }
  svg {
    font-size: 1.45rem;
  }
`;

/* ----------------------------------------------------------------------- */

// ROLE-BASED NAVIGATION
const NAV_DEFINITION = [
  {
    key: 'dashboard',
    label: 'Dashboard',
    to: '/dashboard',
    icon: DashboardIcon,
    roles: ['student', 'teacher', 'admin'],
  },
  {
    key: 'courses',
    label: 'My Courses',
    to: '/courses',
    icon: SchoolIcon,
    roles: ['student', 'teacher'],
  },
  {
    key: 'discussions',
    label: 'Discussions',
    to: '/discussions',
    icon: ForumIcon,
    roles: ['student', 'teacher'],
  },
  {
    key: 'notifications',
    label: 'Notifications',
    to: '/notifications',
    icon: NotificationsIcon,
    roles: ['student', 'teacher', 'admin'],
    badgeKey: 'unreadNotifications',
  },
  {
    key: 'admin',
    label: 'Admin Panel',
    to: '/admin',
    icon: AdminPanelSettingsIcon,
    roles: ['admin'],
  },
];

/**
 * Custom hook that returns a live counter of unread notifications.
 * In production the source could be Redux, SWR, graphQL subscription, or Socket.IO.
 */
const useUnreadNotifications = () => {
  const [count, setCount] = useState(0);

  useEffect(() => {
    // Handler for custom DOM event
    const handler = (e) => {
      const { unreadCount } = e.detail || {};
      if (typeof unreadCount === 'number') setCount(unreadCount);
    };

    window.addEventListener('pl:notifications', handler);

    // Fetch initial count from API. We keep it simple here.
    fetch('/api/notifications/unread-count', { credentials: 'include' })
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((json) => {
        if (typeof json?.count === 'number') setCount(json.count);
      })
      .catch(() => {
        /* noop — keep silent, not critical */
      });

    return () => window.removeEventListener('pl:notifications', handler);
  }, []);

  return count;
};

/**
 * Sidebar component
 */
const Sidebar = ({ initialCollapsed }) => {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(() => {
    // Preserve user preference
    const stored = localStorage.getItem('pl.sidebar.collapsed');
    return stored !== null ? JSON.parse(stored) : !!initialCollapsed;
  });

  // Example: we would derive the role from auth context / redux
  const role =
    (window.__PL_ROLE__ && String(window.__PL_ROLE__)) || 'student'; // placeholder fallback

  const unreadNotifications = useUnreadNotifications();

  // Memoized navigation for performance
  const navItems = useMemo(
    () =>
      NAV_DEFINITION.filter((item) => item.roles.includes(role)).map((item) => {
        const IconComponent = item.icon;

        return {
          ...item,
          IconComponent,
          badge:
            item.badgeKey === 'unreadNotifications' && unreadNotifications > 0
              ? unreadNotifications
              : null,
        };
      }),
    [role, unreadNotifications]
  );

  const toggleSidebar = useCallback(() => {
    setCollapsed((prev) => !prev);
  }, []);

  // Persist preference (debounced)
  useEffect(() => {
    const savePreference = debounce((value) => {
      try {
        localStorage.setItem('pl.sidebar.collapsed', JSON.stringify(value));
      } catch (_) {
        /* Storage could be unavailable (private mode) */
      }
    }, 350);
    savePreference(collapsed);
  }, [collapsed]);

  // Close sidebar automatically when navigating on small devices
  useEffect(() => {
    const unlisten = () => {
      if (window.innerWidth < 992 && !collapsed) {
        setCollapsed(true);
      }
    };
    // react-router does not provide a "listen" in v6; we rely on location changes
    unlisten(); // run on location change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  return (
    <SidebarContainer $collapsed={collapsed}>
      <Branding>
        <img
          src="/logo.svg"
          alt="PulseLearn"
          width={30}
          height={30}
          aria-hidden="true"
        />
        {!collapsed && <span>PulseLearn</span>}
      </Branding>

      <Nav role="menu" aria-label="Main navigation">
        {navItems.map(({ key, label, to, IconComponent, badge }) => (
          <NavItem
            end
            key={key}
            to={to}
            className={({ isActive }) =>
              classNames({ active: isActive })
            }
            $collapsed={collapsed}
          >
            <IconComponent />
            <span>{label}</span>
            {badge !== null && <Badge className="badge">{badge}</Badge>}
          </NavItem>
        ))}
      </Nav>

      <Footer $collapsed={collapsed}>
        <ToggleButton onClick={toggleSidebar}>
          {collapsed ? <MenuIcon /> : <MenuOpenIcon />}
        </ToggleButton>
      </Footer>
    </SidebarContainer>
  );
};

Sidebar.propTypes = {
  /**
   * Initial collapsed state *when localStorage has no value yet*.
   * Useful for SSR or resetting preferences.
   */
  initialCollapsed: PropTypes.bool,
};

Sidebar.defaultProps = {
  initialCollapsed: false,
};

export default Sidebar;
```