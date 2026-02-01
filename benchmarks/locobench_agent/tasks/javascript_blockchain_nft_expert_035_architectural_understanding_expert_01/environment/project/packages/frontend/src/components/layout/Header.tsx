```tsx
/* eslint-disable react-hooks/exhaustive-deps */
import React, { FC, useCallback, useEffect, useMemo, useState } from 'react';
import styled, { css } from 'styled-components';
import { Link, useLocation } from 'react-router-dom';
import { FiWifiOff } from 'react-icons/fi';
import { AiOutlineLoading, AiFillFire } from 'react-icons/ai';
import { MdOutlineAccountBalanceWallet } from 'react-icons/md';

import { useWallet } from '@/hooks/useWallet';
import { useEventBus } from '@/hooks/useEventBus';
import { useLiveShow } from '@/hooks/useLiveShow';
import { logger } from '@/utils/logger';
import { NETWORK } from '@/config/network';

/**
 * Header
 *
 * The global navigation bar rendered on every screen in the dApp. Displays:
 *  • StellarStage Carnival logo linking to Home
 *  • Live show status + show title
 *  • Route navigation (if user is connected)
 *  • Wallet connection button / account summary
 *  • Realtime network + websocket connectivity indicators
 *
 * All data layers are read-only; mutations are delegated to dedicated hooks
 * that implement thin Use-Case adapters (e.g. connectWallet).
 */
const Header: FC = () => {
  const { pathname } = useLocation();

  /* ─────────────────────────────────── Wallet ────────────────────────────────────── */
  const {
    address,
    ensName,
    network,
    isConnecting,
    connect,
    disconnect,
    isCorrectNetwork,
  } = useWallet();

  /* ─────────────────────────────────── Live Show ─────────────────────────────────── */
  const { show, status: showStatus } = useLiveShow();

  /* ─────────────────────────────────── Connectivity ──────────────────────────────── */
  const { isSocketConnected } = useEventBus();

  const [isMounted, setMounted] = useState(false);

  // One-shot mount flag for CSS transitions
  useEffect(() => setMounted(true), []);

  /* ─────────────────────────────────── Handlers ──────────────────────────────────── */
  const handleWalletClick = useCallback(async () => {
    try {
      if (address) {
        await disconnect();
      } else {
        await connect();
      }
    } catch (err) {
      logger.error('Wallet connect/disconnect failed: ', err);
    }
  }, [address, connect, disconnect]);

  /* ─────────────────────────────────── Derived UI State ─────────────────────────── */
  const livePill = useMemo(() => {
    switch (showStatus) {
      case 'LIVE':
        return {
          icon: <AiFillFire />,
          text: 'Live Now',
          color: '#ff3162',
        };
      case 'PAUSED':
        return {
          icon: <AiOutlineLoading className="animate-spin" />,
          text: 'Intermission',
          color: '#F59E0B',
        };
      case 'ENDED':
        return {
          icon: <FiWifiOff />,
          text: 'Ended',
          color: '#9CA3AF',
        };
      default:
        return null;
    }
  }, [showStatus]);

  const currentTitle = show?.title ?? '– No Active Show –';

  /* ─────────────────────────────────── Render ────────────────────────────────────── */
  return (
    <Container isMounted={isMounted}>
      {/* Brand */}
      <Brand to="/">StellarStage Carnival</Brand>

      {/* Live Show Status */}
      <ShowStatus>
        {livePill && <LiveBadge color={livePill.color}>{livePill.icon} {livePill.text}</LiveBadge>}
        <Title>{currentTitle}</Title>
      </ShowStatus>

      {/* Navigation */}
      {address && (
        <Nav>
          <NavItem to="/arena" active={pathname.startsWith('/arena')}>
            Arena
          </NavItem>
          <NavItem to="/governance" active={pathname.startsWith('/governance')}>
            Governance
          </NavItem>
          <NavItem to="/inventory" active={pathname.startsWith('/inventory')}>
            Inventory
          </NavItem>
        </Nav>
      )}

      {/* Right Side Controls */}
      <Controls>
        {/* Socket / RPC Status */}
        <NetworkStatus>
          {!isSocketConnected && <FiWifiOff title="Disconnected from live stream" />}
          {isSocketConnected && isCorrectNetwork && <Dot color="#10B981" />}
          {isSocketConnected && !isCorrectNetwork && (
            <Dot color="#F59E0B" title={`Switch to ${NETWORK.name}`} />
          )}
        </NetworkStatus>

        {/* Wallet button */}
        <WalletBtn
          disabled={isConnecting}
          onClick={handleWalletClick}
          title={address ? 'Disconnect' : 'Connect Wallet'}
        >
          {isConnecting && <AiOutlineLoading className="animate-spin" />}
          {!isConnecting && <MdOutlineAccountBalanceWallet />}
          <span>
            {address ? ensName ?? address.slice(0, 6) + '…' + address.slice(-4) : 'Connect Wallet'}
          </span>
        </WalletBtn>
      </Controls>
    </Container>
  );
};

export default Header;

/* ─────────────────────────────────── Styled Components ─────────────────────────── */

const Container = styled.header<{ isMounted: boolean }>`
  position: sticky;
  top: 0;
  z-index: 50;
  backdrop-filter: blur(8px);
  background: rgba(15, 23, 42, 0.85);
  color: #ffffff;
  display: flex;
  align-items: center;
  padding: 0 1.5rem;
  height: 64px;
  transition: transform 250ms ease-out;

  ${({ isMounted }) =>
    !isMounted &&
    css`
      transform: translateY(-100%);
    `}
`;

const Brand = styled(Link)`
  font-size: 1.1rem;
  font-weight: 600;
  color: #fff;
  text-decoration: none;
  margin-right: 1.75rem;

  &:hover {
    opacity: 0.85;
  }
`;

const ShowStatus = styled.div`
  display: flex;
  align-items: center;
  flex: 1 1 auto;
  min-width: 0; /* ensure text truncation works */
`;

const LiveBadge = styled.span<{ color: string }>`
  display: flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0 0.5rem;
  height: 18px;
  border-radius: 8px;
  background: ${({ color }) => color};
  margin-right: 0.75rem;
`;

const Title = styled.h1`
  font-size: 0.9rem;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const Nav = styled.nav`
  display: flex;
  gap: 1.5rem;
  margin-right: 1.5rem;
`;

const NavItem = styled(Link) <{ active: boolean }>`
  position: relative;
  font-size: 0.85rem;
  font-weight: 500;
  color: ${({ active }) => (active ? '#F9FAFB' : '#9CA3AF')};
  text-decoration: none;

  &:hover {
    color: #f9fafb;
  }

  &::after {
    content: '';
    position: absolute;
    bottom: -10px;
    left: 0;
    height: 2px;
    width: 100%;
    background: ${({ active }) => (active ? '#F9FAFB' : 'transparent')};
    transition: background 200ms ease-in-out;
  }
`;

const Controls = styled.div`
  display: flex;
  align-items: center;
  gap: 0.75rem;
`;

const NetworkStatus = styled.div`
  display: flex;
  align-items: center;
  font-size: 1.15rem;
  color: #9ca3af;
`;

const Dot = styled.span<{ color: string }>`
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: ${({ color }) => color};
`;

const WalletBtn = styled.button`
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.4rem 0.8rem;
  background: #111827;
  color: #f9fafb;
  border: 1px solid #374151;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 500;
  flex-shrink: 0;

  &:hover:not(:disabled) {
    background: #1f2937;
  }

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  svg {
    font-size: 1.15rem;
  }
`;
```