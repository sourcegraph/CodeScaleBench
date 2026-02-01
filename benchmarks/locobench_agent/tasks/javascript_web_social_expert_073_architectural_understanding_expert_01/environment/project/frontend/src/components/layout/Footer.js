```javascript
/**
 * PulseLearn Campus Hub
 * -----------------------------------------
 * Global footer displayed on every public/private route.
 *
 * Responsibilities:
 *  • Render legal & help links as well as dynamic navigation items.
 *  • Display build metadata (version, commit SHA, build date).
 *  • Surface real-time health status of the WebSocket/event-bus connection.
 *  • Conditionally render admin tools where permitted.
 *
 * NOTE: This component purposefully contains *no* API calls; it relies on
 *       existing hooks (`useAuth`, `useEventBus`) that are consumed across
 *       the application. This keeps the component easily testable and
 *       prevents circular dependencies.
 */

import React, { useEffect, useState, useCallback } from 'react';
import PropTypes from 'prop-types';
import { Link, useLocation } from 'react-router-dom';
import styled, { css } from 'styled-components';
import { FiWifi, FiWifiOff } from 'react-icons/fi'; // Connection status icons
import { useAuth } from '../../hooks/useAuth';
import { useEventBus } from '../../hooks/useEventBus';
import { COLORS, BREAKPOINTS } from '../../styles/constants';

// ---------- Styled Components -------------------------------------------------

const FooterWrapper = styled.footer`
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 2rem 1.5rem;
  background-color: ${({ theme }) => theme.colors.neutral900};
  color: ${({ theme }) => theme.colors.neutral100};
  font-size: 0.875rem;
  border-top: 4px solid ${({ theme }) => theme.colors.primary500};

  @media (min-width: ${BREAKPOINTS.tablet}) {
    flex-direction: row;
    align-items: center;
  }
`;

const FooterSection = styled.div`
  display: flex;
  align-items: center;
  margin-bottom: 1rem;

  @media (min-width: ${BREAKPOINTS.tablet}) {
    margin-bottom: 0;
  }
`;

const FooterLink = styled(Link)`
  color: inherit;
  margin-right: 1.25rem;
  text-decoration: none;

  &:hover {
    color: ${({ theme }) => theme.colors.primary300};
    text-decoration: underline;
  }

  ${({ $isActive }) =>
    $isActive &&
    css`
      font-weight: 600;
    `}
`;

const BuildMeta = styled.span`
  opacity: 0.65;
  margin-left: 0.75rem;
`;

const StatusIcon = styled.span`
  display: inline-flex;
  align-items: center;
  margin-right: 0.5rem;
  color: ${({ $online, theme }) =>
    $online ? theme.colors.success400 : theme.colors.error400};
`;

// ---------- Constants & Helpers ----------------------------------------------

const COPYRIGHT_START_YEAR = 2023;
const NOW_YEAR = new Date().getFullYear();

const getCopyrightString = () =>
  COPYRIGHT_START_YEAR === NOW_YEAR
    ? `${NOW_YEAR}`
    : `${COPYRIGHT_START_YEAR}-${NOW_YEAR}`;

const FALLBACK_METADATA = {
  version: '0.0.0',
  gitSha: '———',
  buildDate: 'N/A',
};

// ---------- Component ---------------------------------------------------------

export default function Footer() {
  const { pathname } = useLocation();
  const { user } = useAuth(); // { role: 'student' | 'teacher' | 'admin', ... }
  const { isOnline, subscribe } = useEventBus();

  const [connectionOnline, setConnectionOnline] = useState(isOnline);

  // Build metadata injected via CI/CD (see webpack.DefinePlugin or Vite define)
  const {
    REACT_APP_VERSION: version,
    REACT_APP_GIT_SHA: gitSha,
    REACT_APP_BUILD_DATE: buildDate,
  } = process.env;

  const meta = {
    version: version || FALLBACK_METADATA.version,
    gitSha: gitSha || FALLBACK_METADATA.gitSha,
    buildDate: buildDate || FALLBACK_METADATA.buildDate,
  };

  // -------- Event-bus connection state --------------------------------------

  const handleConnectionChange = useCallback(
    (status) => setConnectionOnline(status),
    [],
  );

  useEffect(() => {
    // Subscribe to global connectivity events (defined in EventBusProvider)
    const unsub = subscribe('connection:status', handleConnectionChange);
    return () => unsub();
  }, [subscribe, handleConnectionChange]);

  // -------- Dynamic navigation items ---------------------------------------

  const baseLinks = [
    { to: '/help/faq', label: 'FAQ' },
    { to: '/help/contact', label: 'Support' },
    { to: '/legal/privacy', label: 'Privacy' },
    { to: '/legal/terms', label: 'Terms' },
  ];

  const adminLinks =
    user?.role === 'admin'
      ? [{ to: '/admin', label: 'Admin Panel' }]
      : [];

  const navLinks = [...baseLinks, ...adminLinks];

  // --------------------------------------------------------------------------

  return (
    <FooterWrapper role="contentinfo">
      {/* Left side — Copyright + Build metadata */}
      <FooterSection>
        <span>
          © {getCopyrightString()} PulseLearn&nbsp;Campus&nbsp;Hub
        </span>
        <BuildMeta>
          build&nbsp;{meta.version} ({meta.gitSha}) — {meta.buildDate}
        </BuildMeta>
      </FooterSection>

      {/* Center — Event-bus Connection health */}
      <FooterSection>
        <StatusIcon $online={connectionOnline} title="Realtime connection">
          {connectionOnline ? <FiWifi size={16} /> : <FiWifiOff size={16} />}
        </StatusIcon>
        <span>{connectionOnline ? 'Live' : 'Offline'}</span>
      </FooterSection>

      {/* Right side — Navigation links */}
      <FooterSection as="nav" aria-label="Footer navigation">
        {navLinks.map(({ to, label }) => (
          <FooterLink
            key={to}
            to={to}
            $isActive={pathname.startsWith(to)}
            aria-current={pathname.startsWith(to) ? 'page' : undefined}
          >
            {label}
          </FooterLink>
        ))}
      </FooterSection>
    </FooterWrapper>
  );
}

Footer.propTypes = {
  // No props currently, but reserved for future extensibility.
};

// ---------- Default export ---------------------------------------------------

// Intentionally exported above for IDE autocompletion & tree-shaking.
// eslint-disable-next-line import/no-default-export
export { Footer as Component };
```